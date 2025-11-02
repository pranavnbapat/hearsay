# app/main.py

import base64
import logging
import os
import secrets
import shutil

import aiofiles

from contextlib import asynccontextmanager
from pathlib import Path
from textwrap import dedent

from fastapi import FastAPI, UploadFile, Form, HTTPException, BackgroundTasks, File, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.core.auth import verify_basic_auth
from app.core.config import settings
from app.models.schemas import TranscriptionResponse, Segment
from app.services.media import is_audio, is_video, extract_audio_to_m4a
from app.services.downloader import download_youtube_best_audio
from app.services.stt import transcribe_file
from app.services.translate import translate_to_english

if settings.GOOGLE_APPLICATION_CREDENTIALS:
    os.environ.setdefault("GOOGLE_APPLICATION_CREDENTIALS", settings.GOOGLE_APPLICATION_CREDENTIALS)


logger = logging.getLogger("hearsay")
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(asctime)s %(name)s: %(message)s",
    )


# ---------- Branding & docs ----------
APP_DESCRIPTION = dedent("""
### What is **HearSay**?
HearSay converts **YouTube videos** and **uploaded audio/video** into an **English transcript**.  
It auto-detects the spoken language and can translate to English.

---
""")

# --- ABSOLUTE paths to avoid PermissionError with bind mounts ---
BASE_DIR = Path("/app")  # container base
TMP_DIR = Path(os.getenv("WORKDIR", "/app/workdir"))
# TMP_DIR = Path("workdir")
UPLOAD_DIR = TMP_DIR / "uploads"
YT_DIR = TMP_DIR / "yt"

@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.STT_BACKEND == "faster-whisper":
        from app.services.stt import get_whisper_model
        get_whisper_model()  # triggers load
    yield

app = FastAPI(
    title="HearSay",
    version="0.1.0",
    description=APP_DESCRIPTION,
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
    swagger_ui_parameters={
        "displayRequestDuration": True,
        "docExpansion": "list",
        "defaultModelsExpandDepth": -1,
        "defaultModelExpandDepth": 2,
        "deepLinking": True,
        "persistAuthorization": True,
        "syntaxHighlight.theme": "obsidian",
    },
)

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory="static"), name="static")


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=False,
    allow_methods=["POST", "OPTIONS"],
    allow_headers=["*"],
)

@app.middleware("http")
async def basic_auth_middleware(request: Request, call_next):
    # Allow CORS preflights through
    if request.method == "OPTIONS":
        return await call_next(request)

    # --- Basic Auth for EVERYTHING else ---
    auth = request.headers.get("Authorization")
    if not auth:
        return JSONResponse({"detail": "Authentication required"}, status_code=401,
                            headers={"WWW-Authenticate": 'Basic realm="HearSay"'})
    try:
        scheme, credentials = auth.split(" ", 1)
        if scheme.lower() != "basic":
            raise ValueError("Invalid scheme")
        decoded = base64.b64decode(credentials).decode("utf-8")
        username, password = decoded.split(":", 1)
    except Exception:
        return JSONResponse({"detail": "Invalid authentication header"}, status_code=401,
                            headers={"WWW-Authenticate": 'Basic realm="HearSay"'})
    if not (secrets.compare_digest(username, settings.AUTH_USERNAME)
            and secrets.compare_digest(password, settings.AUTH_PASSWORD)):
        return JSONResponse({"detail": "Invalid credentials"}, status_code=401,
                            headers={"WWW-Authenticate": 'Basic realm="HearSay"'})
    return await call_next(request)

def ensure_dirs():
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    YT_DIR.mkdir(parents=True, exist_ok=True)

def cleanup_paths(*paths: Path) -> None:
    for p in paths:
        try:
            if p.is_file():
                p.unlink(missing_ok=True)
            elif p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
        except Exception:
            pass


@app.get("/", include_in_schema=False)
def home() -> HTMLResponse:
    return HTMLResponse(dedent("""
    <html>
      <head>
        <title>HearSay</title>
        <meta name="viewport" content="width=device-width,initial-scale=1"/>
        <style>
          body { font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial; 
                 margin: 2rem auto; max-width: 900px; line-height: 1.55; color: #1f2937; }
          .hero { display:flex; gap:1.25rem; align-items:center; }
          .badge { background:#eef2ff; color:#3730a3; border-radius:999px; padding:.25rem .6rem; font-size:.8rem; }
          .card { border:1px solid #e5e7eb; border-radius:16px; padding:1rem 1.25rem; margin:1rem 0; background:#fff; box-shadow:0 1px 2px rgba(0,0,0,.04);}
          code, pre { background:#0b1021; color:#e5e7eb; border-radius:8px; padding:.5rem .75rem; display:block; overflow:auto; }
          a.btn { display:inline-block; padding:.6rem 1rem; border-radius:10px; text-decoration:none; background:#111827; color:#fff; }
          .grid { display:grid; grid-template-columns:repeat(auto-fit, minmax(280px,1fr)); gap:1rem; }
        </style>
      </head>
      <body>
        <div class="hero">
          <img src="/static/favicon.png" alt="logo" width="48" height="48" onerror="this.style.display='none'"/>
          <div>
            <h1>HearSay</h1>
            <div class="badge">Multilingual transcription → English</div>
          </div>
        </div>

        <div class="grid">
          <div class="card">
            <h3>Transcribe a YouTube link</h3>
            <pre>curl -X POST http://localhost:8000/transcribe/youtube \\\n  -H 'Content-Type: application/x-www-form-urlencoded' \\\n  -d 'youtube_value=https://www.youtube.com/watch?v=Q80-pwDrCVI&t=55s'</pre>
            <a class="btn" href="/docs#/%5BYouTube%5D/post_transcribe_youtube">Open in Swagger</a>
          </div>
          <div class="card">
            <h3>Transcribe an upload</h3>
            <pre>curl -X POST http://localhost:8000/transcribe/upload \\\n  -F 'file=@/path/to/video.mp4;type=video/mp4'</pre>
            <a class="btn" href="/docs#/%5BUpload%5D/post_transcribe_upload">Open in Swagger</a>
          </div>
        </div>

        <div class="card">
          <h3>What you get</h3>
          <ul>
            <li><strong>detected_language</strong>, <strong>duration_sec</strong></li>
            <li><strong>transcript_original</strong> and <strong>transcript_english</strong></li>
            <li><strong>segments</strong> with <code>start</code>/<code>end</code> timestamps</li>
          </ul>
          <a class="btn" href="/docs">Open API docs</a>
          &nbsp; <a class="btn" href="/redoc" style="background:#2563eb">Open ReDoc</a>
        </div>
      </body>
    </html>
    """))


@app.get("/healthz", tags=["System"])
def healthz():
    return {"status": "ok", "model": settings.FW_MODEL, "stt_backend": settings.STT_BACKEND}


@app.post(
    "/transcribe/youtube",
    response_model=TranscriptionResponse,
    tags=["YouTube"],
    summary="Transcribe from YouTube (URL or ID, optional t=...)",
)
async def transcribe_youtube(
    background_tasks: BackgroundTasks,
        youtube_value: str = Form(
            ...,
            example="https://www.youtube.com/watch?v=Q80-pwDrCVI&t=55s",
            description="Accepts watch / youtu.be / shorts / embed URLs or the 11-char ID. Optional `t=` timestamp."
        ),
):
    ensure_dirs()
    try:
        # accepts full URL or raw ID (with optional t=), downloader normalises it
        audio_path = download_youtube_best_audio(youtube_value, YT_DIR)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"yt-dlp failed: {e}")

    # STT → translate
    full_text, detected_lang, duration_sec, segments_raw = transcribe_file(audio_path)
    try:
        transcript_english = translate_to_english(full_text, detected_lang)
        translation_status = "ok"
    except Exception as e:
        transcript_english = full_text  # fallback: return original
        translation_status = "failed"
        logger.warning(f"Translation failed; returning original. Err: {e}")

    resp = TranscriptionResponse(
        source="youtube",
        detected_language=detected_lang,
        duration_sec=duration_sec,
        transcript_original=full_text,
        transcript_english=transcript_english,
        segments=[Segment(**s) for s in segments_raw] if segments_raw else None,
        translation_status=translation_status,
    )

    to_clean = (audio_path,)
    background_tasks.add_task(cleanup_paths, *to_clean)

    return JSONResponse(status_code=200, content=resp.model_dump())


@app.post(
    "/transcribe/upload",
    response_model=TranscriptionResponse,
    tags=["Upload"],
    summary="Transcribe from uploaded audio/video",
)
async def transcribe_upload(
    background_tasks: BackgroundTasks,
        file: UploadFile = File(
            ...,
            description="Audio: mp3/aac/wav/ogg/flac/m4a/aiff/opus/alac/amr · Video: mp4/avi/mov/mkv/webm/…",
        ),
):
    ensure_dirs()

    # Save upload to disk
    suffix = Path(file.filename or "").suffix or ""
    tmp_saved = UPLOAD_DIR / f"upload_{os.getpid()}_{id(file)}{suffix}"
    async with aiofiles.open(tmp_saved, "wb") as out:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            out.write(chunk)

    # Decide audio/video and normalise to m4a for STT
    mime = file.content_type or ""
    audio_path = tmp_saved.with_suffix(".m4a")
    if is_audio(mime) or is_video(mime):
        extract_audio_to_m4a(tmp_saved, audio_path)
    else:
        raise HTTPException(status_code=415, detail=f"Unsupported content type: {mime}")

    # STT → translate
    full_text, detected_lang, duration_sec, segments_raw = transcribe_file(audio_path)
    try:
        transcript_english = translate_to_english(full_text, detected_lang)
        translation_status = "ok"
    except Exception as e:
        transcript_english = full_text
        translation_status = "failed"
        logger.warning(f"Translation failed; returning original. Err: {e}")

    resp = TranscriptionResponse(
        source="upload",
        detected_language=detected_lang,
        duration_sec=duration_sec,
        transcript_original=full_text,
        transcript_english=transcript_english,
        segments=[Segment(**s) for s in segments_raw] if segments_raw else None,
        translation_status=translation_status,
    )

    to_clean = tuple(p for p in (tmp_saved, audio_path) if p is not None)
    background_tasks.add_task(cleanup_paths, *to_clean)

    return JSONResponse(status_code=200, content=resp.model_dump())
