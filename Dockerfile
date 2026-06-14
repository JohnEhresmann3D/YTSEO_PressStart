FROM python:3.11-slim

# ffmpeg for audio extraction; ca-certificates for HTTPS to OAuth providers
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# uv = fast dep installer
RUN pip install --no-cache-dir uv

WORKDIR /app

# Install deps first (cache layer)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Then app source
COPY src ./src

# Persist uploads, audio, whisper model cache, and OAuth tokens here.
# Mount a volume at /data on the host (e.g. DO Droplet block storage).
ENV YTSEO_DATA_DIR=/data \
    HOST=0.0.0.0 \
    PORT=8000 \
    PROXY_HEADERS=1 \
    PYTHONUNBUFFERED=1

RUN mkdir -p /data

EXPOSE 8000

CMD ["uv", "run", "ytseo-web"]
