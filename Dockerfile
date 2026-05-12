FROM python:3.12-slim

# System deps:
# - ffmpeg for mp3 transcode
# - curl + ca-certificates for NodeSource bootstrap
# - git for cloning the PO Token provider
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg \
        ca-certificates \
        curl \
        git \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Build the bgutil PO Token provider (HTTP server on :4416).
# Pinning to a release branch so builds are reproducible.
RUN git clone --depth 1 --single-branch --branch 1.3.1 \
        https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git /opt/pot-src \
    && cd /opt/pot-src/server \
    && npm ci \
    && npx tsc \
    && mkdir -p /opt/pot \
    && cp -r /opt/pot-src/server/build /opt/pot/ \
    && cp -r /opt/pot-src/server/node_modules /opt/pot/ \
    && rm -rf /opt/pot-src

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir --upgrade yt-dlp

COPY app/ app/

ENV PYTHONUNBUFFERED=1
ENV PORT=8000
EXPOSE 8000

# Start the PO Token provider in background, then uvicorn in foreground.
# If the provider crashes, uvicorn keeps serving; yt-dlp plugin will fall back
# (and we'll see degraded behavior, not an outage).
CMD ["sh", "-c", "node /opt/pot/build/main.js >/tmp/pot.log 2>&1 & exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
