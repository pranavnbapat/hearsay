# app/services/media.py

import subprocess

from pathlib import Path

from fastapi import HTTPException

AUDIO_EXTS  = {"mp3", "aac", "wav", "wma", "ogg", "flac", "m4a", "aiff", "opus", "alac", "amr"}
VIDEO_EXTS  = {"mp4", "avi", "mov", "wmv", "mpeg", "mpg", "mkv", "flv", "webm", "3gp", "mts", "m2ts", "vob", "rmvb"}


def is_video(mime: str) -> bool:
    return mime.startswith("video/")


def is_audio(mime: str) -> bool:
    return mime.startswith("audio/")


def validate_file_extension(file_path: Path):
    ext = file_path.suffix.lower().lstrip(".")
    if ext in AUDIO_EXTS or ext in VIDEO_EXTS:
        return
    raise HTTPException(status_code=415, detail=f"Unsupported file extension: .{ext}")


def extract_audio_to_m4a(input_path: Path, output_path: Path) -> Path:
    """Extracts audio to AAC/M4A at reasonable bitrate."""
    validate_file_extension(input_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-vn", "-ac", "1", "-ar", "16000",
        "-c:a", "aac", "-b:a", "96k",
        str(output_path)
    ]
    subprocess.run(cmd, check=True)
    return output_path

def download_direct_audio(url: str, out_path: Path) -> Path:
    """
    Download/record audio from a direct media URL (mp3/mp4/webm/m3u8, etc.)
    and normalise to m4a. This is NOT for YouTube pages.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # -vn drops video, we set mono 16kHz AAC ~96kbps for your STT
    cmd = [
        "ffmpeg", "-y",
        "-i", url,
        "-vn", "-ac", "1", "-ar", "16000",
        "-c:a", "aac", "-b:a", "96k",
        str(out_path)
    ]
    subprocess.run(cmd, check=True)
    return out_path
