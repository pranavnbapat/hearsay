# app/services/stt.py

from functools import lru_cache
from pathlib import Path
from typing import Tuple, List, Dict, Any

from app.core.config import settings


@lru_cache(maxsize=1)
def get_whisper_model():
    """
    Singleton Whisper model. Loaded once per process.
    """
    from faster_whisper import WhisperModel
    device = "cuda" if settings.FW_COMPUTE_TYPE.lower() in {"float16", "int8_float16"} else "cpu"
    return WhisperModel(
        settings.FW_MODEL,
        compute_type=settings.FW_COMPUTE_TYPE,
        device=device,            # auto / cpu / cuda
        cpu_threads=0,            # 0 = let library decide
        num_workers=1             # internal decoding workers per call
    )


def transcribe_file(audio_path: Path) -> Tuple[str, str, float, List[Dict[str, Any]]]:
    """
    Returns (full_text, detected_language, duration_sec, segments)
    Each segment: {"start": float, "end": float, "text": str}
    """
    if settings.STT_BACKEND == "faster-whisper":
        model = get_whisper_model()

        # language=None for auto-detect
        segments, info = model.transcribe(str(audio_path), beam_size=5, vad_filter=True, language=None)
        seg_list = []
        full_text_parts = []
        for s in segments:
            seg_list.append({"start": s.start, "end": s.end, "text": s.text})
            full_text_parts.append(s.text)
        full_text = " ".join(full_text_parts).strip()
        detected_lang = info.language or "unknown"
        duration = info.duration or 0.0
        return full_text, detected_lang, duration, seg_list

    else:
        raise ValueError(f"Unsupported STT_BACKEND: {settings.STT_BACKEND}")
