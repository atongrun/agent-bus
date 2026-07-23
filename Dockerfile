FROM ghcr.io/astral-sh/uv:0.11.30 AS uv

FROM python:3.11.15-slim-bookworm AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_CACHE=1 \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /app

COPY --from=uv /uv /uvx /bin/
COPY pyproject.toml uv.lock README.md ./
COPY server ./server
COPY client ./client

RUN uv sync --locked --no-dev --no-editable

FROM python:3.11.15-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    AGENT_BUS_HOST=0.0.0.0 \
    AGENT_BUS_PORT=8800 \
    AGENT_BUS_DB_PATH=/data/agent-bus.db \
    PATH=/app/.venv/bin:$PATH

WORKDIR /app

RUN groupadd --gid 10001 agent-bus \
    && useradd --uid 10001 --gid agent-bus --no-create-home --home-dir /app --shell /usr/sbin/nologin agent-bus \
    && mkdir -p /data \
    && chown -R agent-bus:agent-bus /app /data

COPY --from=builder --chown=10001:10001 /app/.venv /app/.venv

USER agent-bus

EXPOSE 8800
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('AGENT_BUS_PORT', '8800') + '/health', timeout=2).read()"

CMD ["sh", "-c", "test -n \"$AGENT_BUS_AGENT_TOKENS\" || { echo 'AGENT_BUS_AGENT_TOKENS is required for Docker deployment' >&2; exit 64; }; exec python -m server.main"]
