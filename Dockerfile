# syntax=docker/dockerfile:1

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    HF_HOME=/models/hf \
    HF_HUB_DISABLE_XET=1 \
    FASTEMBED_CACHE_PATH=/models/fastembed \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    PATH="/app/.venv/bin:$PATH"

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir "uv==0.13.7"

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# Models are downloaded before copying the source so code changes do not invalidate
# this expensive layer. At runtime the plant has no internet.
COPY scripts/download_models.py scripts/download_models.py
ARG DOWNLOAD_LLM=0
ENV DOWNLOAD_LLM=${DOWNLOAD_LLM}
RUN mkdir -p /models \
 && HF_HUB_OFFLINE=0 TRANSFORMERS_OFFLINE=0 python scripts/download_models.py \
 && chmod -R a+rX /models

COPY . .

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# git is only needed to fetch the contract package; keeping it in its own layer after the
# models keeps that expensive layer cached.
RUN apt-get update \
 && apt-get install -y --no-install-recommends git \
 && rm -rf /var/lib/apt/lists/*

# The integration contract is installed with pip from the provided package. It must be
# installed AFTER uv sync: sync removes packages that are not in the lock. The models
# are never copied into this repository.
# The contract package is installed with pip from the source published by the course.
# The older ``academia2026-planta`` URL documented in the assignment returns 404; the
# package actually lives in ``academia2026-tp/contrato`` (planta_contrato 0.2.0).
ARG PLANTA_CONTRATO_GIT=git+https://github.com/NovitSoftware/academia2026-tp#subdirectory=contrato
RUN --mount=type=bind,from=contrato,target=/contrato \
    if [ -f /contrato/planta_contrato/__init__.py ]; then \
        cp -r /contrato /tmp/contrato-src && uv pip install --python /app/.venv/bin/python /tmp/contrato-src; \
    else \
        uv pip install --python /app/.venv/bin/python "$PLANTA_CONTRATO_GIT"; \
    fi

RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin appuser \
 && mkdir -p /app/var/media /data/media \
 && chown -R appuser:appuser /app /data

USER appuser
EXPOSE 8200 8300
CMD ["python", "-m", "app.main"]
