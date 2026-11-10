FROM ghcr.io/astral-sh/uv:0.8.22 AS uv

FROM python:3.13-slim

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

COPY --from=uv /uv /uvx /bin/
COPY apps/api/pyproject.toml apps/api/uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

COPY apps/api/src ./src
COPY apps/api/alembic ./alembic
COPY apps/api/alembic.ini ./alembic.ini
RUN uv sync --locked --no-dev --no-editable \
    && useradd --system --uid 10001 --create-home --home-dir /home/bipme bipme \
    && chown -R 10001:10001 /app /home/bipme

USER 10001:10001

