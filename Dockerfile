# syntax=docker/dockerfile:1

# Builder: has compilers and Rust so any dependency without a Python 3.15 wheel builds from source.
FROM python:3.15-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.12.17 /uv /usr/local/bin/uv
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential pkg-config curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN curl -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal
ENV PATH="/root/.cargo/bin:${PATH}" \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PYTHON=python3.15
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY ferret ./ferret
RUN uv sync --locked --no-dev --no-editable

# Runtime: no build tools.
FROM python:3.15-slim
RUN useradd --create-home --uid 1000 ferret
WORKDIR /app
COPY --from=builder --chown=ferret:ferret /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:${PATH}" PYTHONUNBUFFERED=1
USER ferret
EXPOSE 8000
CMD ["uvicorn", "ferret.web.app:app", "--host", "0.0.0.0", "--port", "8000"]
