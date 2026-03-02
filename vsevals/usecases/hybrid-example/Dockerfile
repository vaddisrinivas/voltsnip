FROM python:3.12-slim

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

# Copy dependency specs first for layer caching
COPY pyproject.toml uv.lock ./

# Create .venv and install all deps (baked into the image — no runtime sync needed)
RUN UV_LINK_MODE=copy uv sync --frozen --group dev --no-install-project

# Bake in the full usecase source
COPY . .

ENV PYTHONUNBUFFERED=1
ENV PATH="/workspace/.venv/bin:${PATH}"
