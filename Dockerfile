# ===== base stage with system deps =====
FROM python:3.12-slim

# Core env & defaults
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    XDG_CACHE_HOME=/cache \
    FW_COMPUTE_TYPE=int8 \
    GUNICORN_CMD_ARGS="--timeout 120" \
    APP_HOST=0.0.0.0 \
    APP_PORT=10000 \
    GOOGLE_APPLICATION_CREDENTIALS=/app/creds/google.json

# System packages: ffmpeg for audio extract; ca-certs for HTTPS; curl for healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
      ffmpeg \
      ca-certificates \
      curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m -u 1000 appuser

WORKDIR /app

# Python deps
COPY requirements.txt ./
RUN pip install --upgrade pip && \
    pip install --no-cache-dir --upgrade yt-dlp && \
    pip install --no-cache-dir -r requirements.txt

# App code
COPY app ./app
COPY static ./static

# Runtime dirs & ownership
# - Create creds dir (empty; secret will be mounted at runtime)
# - Create workdir/uploads and cache
RUN mkdir -p /app/creds /app/workdir/uploads /cache \
 && chown -R appuser:appuser /app /cache

# Persist uploads & cache across restarts (anonymous volumes by default)
VOLUME ["/app/workdir", "/cache"]

# Drop privileges
USER appuser

EXPOSE 10000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=5 \
  CMD curl -fsS http://localhost:10000/healthz || exit 1

# Gunicorn (Uvicorn worker)
CMD gunicorn -k uvicorn.workers.UvicornWorker \
    -w 1 \
    -b ${APP_HOST}:${APP_PORT} \
    app.main:app
