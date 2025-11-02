# app/services/downloader.py

import os
import re
import subprocess

from pathlib import Path
from shutil import copyfile
from tempfile import gettempdir

from urllib.parse import urlparse, parse_qs

from app.core.config import settings

_YT_ID_RE = re.compile(
    r"""
    (?:youtu\.be/|youtube\.com/(?:watch\?v=|embed/|shorts/))   # common URL forms
    ([0-9A-Za-z_-]{11})                                        # capture the 11-char ID
    """,
    re.VERBOSE,
)

COOKIES_PATH = os.getenv("YTDLP_COOKIES")

# A realistic mobile UA helps avoid bot checks on some DC IP ranges
MOBILE_UA = (
    "Mozilla/5.0 (Linux; Android 13; Pixel 7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/123.0 Mobile Safari/537.36"
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


def _writable_cookies_path(src: str | None) -> str | None:
    """
    If a cookies.txt is provided (read-only bind), copy it to a tmp path so yt-dlp
    can write back updated cookies without failing on RO filesystem.
    """
    if not src or not os.path.isfile(src):
        return None
    dst = os.path.join(gettempdir(), "ytdlp_cookies.txt")
    try:
        copyfile(src, dst)  # overwrite if exists
        return dst
    except Exception:
        return src  # fall back to original (may be read-only)


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

    cookiefile = _writable_cookies_path(COOKIES_PATH)
    using_cookies = bool(cookiefile and os.path.isfile(cookiefile))

    extractor_args = (
            (settings.YT_EXTRACTOR_ARGS or "").strip()
            or (
                "youtube:player_client=web,ios,mweb;player_skip=webpage"
                if using_cookies
                else "youtube:player_client=android,web,ios,mweb;player_skip=webpage"
            )
    )

    cmd = [
        "yt-dlp",
        "-f", "bestaudio/best",
        "-x", "--audio-format", "m4a",
        "-o", out_tmpl,
        "--extractor-args", extractor_args,
        "--user-agent", MOBILE_UA,
        "--add-header", "Accept-Language: en-GB,en;q=0.9",
        "--force-ipv4",
        "--no-playlist",
        "--geo-bypass",
        "--retries", "5",
        "--fragment-retries", "5",
        "--sleep-requests", "1",
    ]

    # Optional: only if a cookies file is mounted and readable (keeps default cookie-less)
    if using_cookies:
        cmd += ["--cookies", cookiefile]

    if start_sec is not None and start_sec > 0:
        cmd += ["--download-sections", f"*{start_sec}-"]

    cmd.append(url)

    try:
        _ = subprocess.run(cmd, check=True, text=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        msg = (e.stderr or e.stdout or str(e)).strip()
        # normalise apostrophes for matching
        low = msg.lower()
        if "confirm you’re not a bot" in low or "confirm you're not a bot" in low:
            raise ValueError(
                "YouTube requires human verification from this server. "
                "Retry later, provide cookies.txt, or change egress IP."
            )
        # propagate real yt-dlp message up to FastAPI
        raise ValueError(msg) from e

    candidates = sorted(out_dir.glob(f"*_{vid}.m4a"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not candidates:
        candidates = sorted(out_dir.glob(f"*_{vid}.*"), key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]
