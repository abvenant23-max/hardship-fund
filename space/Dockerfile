# The Hugging Face Space: the web app and the API in one container on :7860.
# deploy/push_space.py copies this file to the Space's root as Dockerfile.

FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
# LightGBM needs the OpenMP runtime
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Spaces run the container as user 1000; models/ must be writable for downloads.
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user PATH=/home/user/.local/bin:$PATH PYTHONUNBUFFERED=1 \
    PORT=7860 HARDSHIP_WEB_DIR=/home/user/app/web
WORKDIR /home/user/app

COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt
COPY --chown=user backend ./backend
COPY --from=web --chown=user /web/dist ./web
RUN mkdir -p models

EXPOSE 7860
CMD ["sh", "-c", "exec uvicorn backend.web:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
