FROM node:22-bookworm-slim AS frontend
WORKDIR /build/frontend
RUN corepack enable && corepack prepare pnpm@11.19.0 --activate
# Keep package downloads cached when only the application version changes.
COPY frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
RUN pnpm fetch
COPY frontend/package.json ./
RUN pnpm install --offline --frozen-lockfile
COPY frontend/ ./
RUN pnpm build

FROM python:3.12-slim-bookworm
WORKDIR /app
# Match the Agent's dependency layer so Docker can reuse it for both images.
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 MEDIAHUB_DATA_DIR=/data MEDIAHUB_PROJECT_ROOT=/app PYTHONPATH=/app
COPY pyproject.toml README.md LICENSE ./
COPY backend/ ./backend/
COPY agent/ ./agent/
COPY apps/ ./apps/
COPY alembic.ini ./
RUN pip install --no-cache-dir --no-deps . \
    && groupadd --gid 10001 mediahub && useradd --uid 10001 --gid mediahub --no-create-home mediahub \
    && mkdir /data && chown mediahub:mediahub /data
COPY --from=frontend /build/frontend/dist ./frontend/dist
USER 10001:10001
EXPOSE 18765
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:18765/api/health',timeout=4)"
CMD ["mediahub", "serve", "--host", "0.0.0.0", "--port", "18765"]
