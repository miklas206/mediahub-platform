FROM node:22-bookworm-slim AS frontend-manifest
WORKDIR /manifest
COPY frontend/package.json ./
# Release metadata must not invalidate dependency installation or the UI build.
RUN node -e "const fs=require('fs');const p=JSON.parse(fs.readFileSync('package.json'));delete p.version;fs.writeFileSync('package.json',JSON.stringify(p))"

FROM node:22-bookworm-slim AS frontend
WORKDIR /build/frontend
RUN corepack enable && corepack prepare pnpm@11.19.0 --activate
# Keep package downloads cached when only the application version changes.
COPY frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
RUN pnpm fetch
COPY --from=frontend-manifest /manifest/package.json ./
RUN pnpm install --offline --frozen-lockfile
COPY backend/mediahub/fjordhub_scripts.json /build/backend/mediahub/fjordhub_scripts.json
COPY frontend/src/ ./src/
COPY frontend/public/ ./public/
COPY frontend/index.html frontend/tsconfig.json frontend/vite.config.ts ./
RUN pnpm build

FROM python:3.12-slim-bookworm
WORKDIR /app
# Match the Agent's dependency layer so Docker can reuse it for both images.
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 MEDIAHUB_DATA_DIR=/data MEDIAHUB_PROJECT_ROOT=/app PYTHONPATH=/app:/app/backend
RUN groupadd --gid 10001 mediahub && useradd --uid 10001 --gid mediahub --no-create-home mediahub \
    && mkdir /data && chown mediahub:mediahub /data \
    && printf '#!/bin/sh\nexec python -m mediahub.cli "$@"\n' > /usr/local/bin/mediahub \
    && chmod 0755 /usr/local/bin/mediahub
COPY pyproject.toml README.md LICENSE ./
COPY backend/ ./backend/
COPY agent/ ./agent/
COPY apps/ ./apps/
COPY alembic.ini ./
COPY --from=frontend /build/frontend/dist ./frontend/dist
USER 10001:10001
EXPOSE 18765
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:18765/api/health',timeout=4)"
CMD ["mediahub", "serve", "--host", "0.0.0.0", "--port", "18765"]
