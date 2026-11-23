# syntax=docker/dockerfile:1
FROM python:3.13.18-slim-trixie AS base
COPY --from=ghcr.io/astral-sh/uv:0.13.9 /uv /uvx /bin/
ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0 \
    PATH="/app/.venv/bin:$PATH"
WORKDIR /app

# Development: source is bind mounted, .venv lives in its own volume.
# Runs as uid 1000 (the usual WSL and Linux user), so files written into the bind mount stay deletable.
FROM base AS dev
ENV PYTHONDONTWRITEBYTECODE=1 UV_CACHE_DIR=/tmp/uv-cache
RUN useradd --create-home --uid 1000 dev && chown dev:dev /app
USER dev
COPY --chown=dev:dev pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/tmp/uv-cache,uid=1000 uv sync --locked
COPY --chown=dev:dev . .
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload", "--no-access-log"]

FROM base AS builder
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev

FROM python:3.13.18-slim-trixie AS prod
ENV PYTHONUNBUFFERED=1 PATH="/app/.venv/bin:$PATH"
WORKDIR /app
RUN useradd --system --uid 10001 app
COPY --from=builder /app/.venv /app/.venv
COPY app ./app
COPY prompts ./prompts
USER app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
