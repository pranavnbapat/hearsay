# app/services/downloader.py

import re
import subprocess

from pathlib import Path

from urllib.parse import urlparse, parse_qs

from app.core.config import settings

_YT_ID_RE = re.compile(
    r"""
    (?:youtu\.be/|youtube\.com/(?:watch\?v=|embed/|shorts/))   # common URL forms
    ([0-9A-Za-z_-]{11})                                        # capture the 11-char ID
    """,
    re.VERBOSE,
)


def _parse_yt_time(t: str) -> int:
    """
    Accepts '55', '55s', '1m30s', '2h3m', '90' etc. Returns seconds as int.
    """
    if t.isdigit():
        return int(t)
    total = 0
    for part in re.findall(r'(\d+)([hms])', t.lower()):
        val, unit = int(part[0]), part[1]
        if unit == 'h':
            total += val * 3600
        elif unit == 'm':
            total += val * 60
        else:
            total += val
    # if nothing matched but something like "75" came with s, try stripping non-digits
    if total == 0:
        digits = re.findall(r'\d+', t)
        if digits:
            total = int(digits[0])
    return total


def parse_youtube_value(value: str) -> tuple[str, int | None]:
    """
    Accepts raw ID, various YouTube URLs, or 'ID&t=...' and returns (video_id, start_seconds or None).
    """
    value = value.strip()

    # Case 1: looks like a full URL
    if value.startswith(("http://", "https://")):
        u = urlparse(value)
        qs = parse_qs(u.query)
        # try to get ID from query (watch?v=...)
        vid = (qs.get("v") or [None])[0]
        if not vid:
            # try to extract from path (youtu.be/ID, /embed/ID, /shorts/ID)
            m = _YT_ID_RE.search(value)
            if m:
                vid = m.group(1)
        # start time
        start = None
        if "t" in qs:
            start = _parse_yt_time(qs["t"][0])
        elif "start" in qs:
            start = _parse_yt_time(qs["start"][0])
        return vid, start

    # Case 2: raw ID or ID with &t=...
    # e.g. "Q80-pwDrCVI" or "Q80-pwDrCVI&t=55s"
    if "&" in value:
        head, tail = value.split("&", 1)
        vid = head
        qs = parse_qs(tail)
        start = None
        if "t" in qs:
            start = _parse_yt_time(qs["t"][0])
        elif "start" in qs:
            start = _parse_yt_time(qs["start"][0])
        # sanity-check 11-char ID
        if re.fullmatch(r"[0-9A-Za-z_-]{11}", vid):
            return vid, start
        # last resort: try regex on the whole string
        m = _YT_ID_RE.search(value)
        return (m.group(1) if m else None), start

    # Case 3: plain 11-char ID
    if re.fullmatch(r"[0-9A-Za-z_-]{11}", value):
        return value, None

    # Fallback: try regex
    m = _YT_ID_RE.search(value)
    return (m.group(1) if m else None), None


def download_youtube_best_audio(youtube_value: str, out_dir: Path) -> Path:
    """
    Accepts full URL or raw ID (with optional t/start timestamp).
    Downloads best audio as m4a. If a start time is present, trims using yt-dlp.
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    vid, start_sec = parse_youtube_value(youtube_value)
    if not vid:
        raise ValueError(f"Could not parse a valid YouTube video ID from: {youtube_value}")

    # Build a canonical URL (preserving start for yt-dlp download sections)
    url = f"https://www.youtube.com/watch?v={vid}"

    out_tmpl = str(out_dir / "%(title)s_%(id)s.%(ext)s")

    cmd = [
        "yt-dlp",
        "-f", "bestaudio/best",
        "-x", "--audio-format", "m4a",
        "-o", out_tmpl,
        url,
    ]
    if settings.YT_EXTRACTOR_ARGS:
        cmd += ["--extractor-args", settings.YT_EXTRACTOR_ARGS]

    if start_sec is not None and start_sec > 0:
        # Download from start_sec to end
        cmd += ["--download-sections", f"*{start_sec}-"]

    subprocess.run(cmd, check=True)

    candidates = sorted(out_dir.glob(f"*_{vid}.m4a"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not candidates:
        candidates = sorted(out_dir.glob(f"*_{vid}.*"), key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]
