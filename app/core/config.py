# app/core/config.py

from typing import Optional, List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # STT backend: "faster-whisper"
    STT_BACKEND: str = "faster-whisper"
    # Model name for faster-whisper: tiny/base/small/medium/large-v3
    FW_MODEL: str = "large-v3"
    FW_COMPUTE_TYPE: str = "int8"  # "int8" for CPU; "float16"/"int8_float16" for GPU

    # DeepL
    DEEPL_API_KEY: Optional[str] = None

    # Max upload size (bytes) – you can enforce at reverse proxy too
    MAX_UPLOAD_BYTES: int = 500 * 1024 * 1024  # 500 MB

    # YT-DLP extractor tweak for SABR issues; set "" to disable
    YT_EXTRACTOR_ARGS: str = 'youtube:player_client=android'

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # --- Google SA path ---
    GOOGLE_APPLICATION_CREDENTIALS: Optional[str] = None

    # --- server & CORS ---
    UVICORN_HOST: str = "0.0.0.0"
    UVICORN_PORT: int = 8000
    CORS_ALLOW_ORIGINS: str = "*"

    AUTH_USERNAME: str = "admin"
    AUTH_PASSWORD: str = "K5C5R2wRPb6cKcU1"

    @property
    def cors_origins_list(self) -> List[str]:
        s = (self.CORS_ALLOW_ORIGINS or "").strip()
        if s in ("", "*"):
            return ["*"]
        return [x.strip() for x in s.split(",") if x.strip()]

settings = Settings()
