# app/services/translate.py

import os
import time
import logging
import deepl
from google.cloud import translate_v2 as translate
from app.core.config import settings

logger = logging.getLogger(__name__)

DEEPL_SUPPORTED_LANGUAGES = {
    "BG", "CS", "DA", "DE", "EL", "EN", "EN-GB", "EN-US", "ES", "ET",
    "FI", "FR", "HU", "ID", "IT", "JA", "LT", "LV", "NL", "PL",
    "PT", "PT-PT", "PT-BR", "RO", "RU", "SK", "SL", "SV",
    "TR", "UK", "ZH"
}


class RateLimitError(Exception):
    """Custom exception for rate limiting."""
    pass


def deepl_translate(text, target_language, max_retries=3):
    """Translate via official DeepL SDK with retry and exponential backoff."""
    attempts = 0
    delay = 1
    deepl_api_key = settings.DEEPL_API_KEY or os.getenv("DEEPL_API_KEY")

    if not deepl_api_key:
        raise ValueError("DEEPL_API_KEY not set")

    translator = deepl.Translator(deepl_api_key)

    while attempts < max_retries:
        try:
            result = translator.translate_text(
                text,
                target_lang=target_language,
                tag_handling='html',
                ignore_tags=[]
            )
            return result.text
        except (deepl.DeepLException, ValueError) as e:
            logger.warning(f"DeepL error: {e}. Retry {attempts+1}/{max_retries}")
            attempts += 1
            time.sleep(delay)
            delay *= 2
    raise RateLimitError(f"DeepL translation failed after {max_retries} attempts.")


def google_translate(text, target_language, max_retries=3):
    """Fallback translation via Google Cloud Translate."""
    attempts = 0
    delay = 1
    client = translate.Client()

    while attempts < max_retries:
        try:
            result = client.translate(
                text,
                target_language=target_language,
                format_='html'
            )
            return result["translatedText"]
        except Exception as e:
            logger.warning(f"Google Translate error: {e}. Retry {attempts+1}/{max_retries}")
            attempts += 1
            time.sleep(delay)
            delay *= 2
    raise RateLimitError(f"Google Translate failed after {max_retries} attempts.")


def translate_text_with_backoff(text, target_language="EN-GB", max_retries=3):
    """
    Prefer DeepL when a key is configured; on ANY DeepL failure, fall back to Google
    within the same attempt. Retries use exponential backoff across attempts.
    """
    if not text or not isinstance(text, str):
        return text

    target_language = target_language.upper()
    if target_language == "EN":
        target_language = "EN-GB"
    if target_language == "PT":
        target_language = "PT-PT"

    delay = 1
    for attempt in range(1, max_retries + 1):
        try:
            # Try DeepL if configured
            if settings.DEEPL_API_KEY:
                try:
                    return deepl_translate(text, target_language, max_retries=1)
                except Exception as deepl_err:
                    logger.warning(f"DeepL failed (attempt {attempt}): {deepl_err}. Falling back to Google.")
            # Try Google (either no DeepL key, or DeepL failed)
            return google_translate(text, target_language, max_retries=1)

        except Exception as e:
            logger.warning(f"Translate attempt {attempt}/{max_retries} failed: {e}. Backing off {delay}s...")
            time.sleep(delay)
            delay *= 2

    # After all retries, give up with a clear signal to caller
    raise RateLimitError(f"Translation failed after {max_retries} attempts (DeepL & Google).")


def translate_to_english(text: str, source_lang: str | None = None) -> str:
    """
    Public wrapper used by the main app.
    Always translates to English (British).
    """
    return translate_text_with_backoff(text, target_language="EN-GB")
