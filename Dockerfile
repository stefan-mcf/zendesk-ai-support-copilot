FROM ghcr.io/astral-sh/uv:0.11.16 AS uv

FROM python:3.12.11-slim-bookworm

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

COPY --from=uv /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY alembic.ini ./
COPY migrations ./migrations
COPY src ./src
COPY data ./data
RUN uv sync --frozen --no-dev

RUN groupadd --gid 10001 copilot && \
    useradd --uid 10001 --gid copilot --no-create-home copilot && \
    chown -R copilot:copilot /app

USER 10001:10001

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/v1/healthz', timeout=2)"]

ENTRYPOINT ["uvicorn", "copilot.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
