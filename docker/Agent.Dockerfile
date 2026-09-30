FROM python:3.12-slim-bookworm
WORKDIR /app
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 MEDIAHUB_PROJECT_ROOT=/app PYTHONPATH=/app:/app/backend
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl \
    && install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc \
    && chmod 0644 /etc/apt/keyrings/docker.asc \
    && printf 'Types: deb\nURIs: https://download.docker.com/linux/debian\nSuites: bookworm\nComponents: stable\nSigned-By: /etc/apt/keyrings/docker.asc\n' > /etc/apt/sources.list.d/docker.sources \
    && apt-get update && apt-get install -y --no-install-recommends docker-ce-cli docker-compose-plugin \
    && apt-get clean
# Use the shared media group as the primary GID: mergerfs may not resolve
# Docker-only supplementary groups when checking write access. Keep UID 10001
# so existing private Agent state and credentials remain owned by this user.
RUN groupadd --gid 1000 media && groupadd --gid 10001 mediahub \
    && useradd --uid 10001 --gid media --groups mediahub --no-create-home mediahub \
    && mkdir /state /storage && chown mediahub:mediahub /state /storage
COPY pyproject.toml README.md LICENSE ./
COPY backend/ ./backend/
COPY agent/ ./agent/
# Resolve the primary media GID AND supplementary private-state GID from the
# image account. An explicit :1000 would discard its mediahub group membership.
ARG MEDIAHUB_SOURCE_COMMIT=""
ENV MEDIAHUB_SOURCE_COMMIT=$MEDIAHUB_SOURCE_COMMIT
USER 10001
CMD ["python", "-m", "agent.main"]
