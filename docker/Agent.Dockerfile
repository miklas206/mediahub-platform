FROM python:3.12-slim-bookworm
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 MEDIAHUB_PROJECT_ROOT=/app PYTHONPATH=/app
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl \
    && install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc \
    && chmod 0644 /etc/apt/keyrings/docker.asc \
    && printf 'Types: deb\nURIs: https://download.docker.com/linux/debian\nSuites: bookworm\nComponents: stable\nSigned-By: /etc/apt/keyrings/docker.asc\n' > /etc/apt/sources.list.d/docker.sources \
    && apt-get update && apt-get install -y --no-install-recommends docker-ce-cli docker-compose-plugin \
    && apt-get clean
COPY pyproject.toml requirements.lock README.md LICENSE ./
COPY backend/ ./backend/
COPY agent/ ./agent/
RUN pip install --no-cache-dir -r requirements.lock && pip install --no-cache-dir --no-deps . \
    && groupadd --gid 10001 mediahub && useradd --uid 10001 --gid mediahub --no-create-home mediahub \
    && mkdir /state /storage && chown mediahub:mediahub /state /storage
USER 10001:10001
CMD ["python", "-m", "agent.main"]
