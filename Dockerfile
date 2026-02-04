# syntax=docker/dockerfile:1.4
# =============================================================================
# Jarvis Ingestion - 4-LAYER OPTIMIZED Build with BuildKit Caching
# =============================================================================
# AGGRESSIVE OPTIMIZATIONS:
# 1. Layer 1: System deps (gcc, libpq) - RARELY CHANGES
# 2. Layer 2: Heavy ML packages (torch, transformers) - COMPILE ONCE, CACHE FOREVER
# 3. Layer 3: Core dependencies (FastAPI, SDKs) - MODERATE CHANGES
# 4. Layer 4: Application code - FREQUENT CHANGES (5-8 seconds rebuild)
#
# BuildKit persistent cache mounts with sharing=shared (survive prune + NAS SSH)
# Minimal base image (python:3.11-slim = 125MB)
#
# Performance targets:
# - First build: 6-8 minutes (ML compilation one-time)
# - Code-only rebuild: 5-8 seconds ⚡ (CACHED ML packages)
# - Cache-hit rebuild: <1 second (all layers cached)
#
# Usage: DOCKER_BUILDKIT=1 docker build --progress=tty .
# =============================================================================

# Stage 1: System Dependencies (Layer 1)
# ========= RARELY CHANGES (update Dockerfile) =========
FROM python:3.11-slim AS system-deps

WORKDIR /install

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked,id=apt-cache \
    --mount=type=cache,target=/var/lib/apt,sharing=locked,id=apt-lib \
    apt-get update && \
    apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    curl \
    build-essential && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Stage 2: Heavy ML Packages (Layer 2)
# ========= COMPILE ONCE, CACHE FOREVER (torch, transformers, etc) =========
FROM system-deps AS ml-deps

COPY pyproject.toml .

# Install ONLY heavy ML packages (Layer 2 from pyproject.toml)
# These have pinned versions and rarely change
RUN --mount=type=cache,target=/root/.cache/pip,sharing=shared,id=pip-cache-ml \
    pip install --prefix=/install --no-cache-dir \
    torch>=2.10.0 \
    transformers>=5.0.0 \
    sentence-transformers>=5.2.0 \
    qdrant-client>=1.16.0 \
    scikit-learn>=1.8.0 \
    scipy>=1.17.0 \
    numpy>=2.4.0

# Stage 3: Core Dependencies (Layer 3)
# ========= STABLE, MODERATE CHANGES =========
FROM ml-deps AS core-deps

# Install core framework + API clients (FastAPI, Anthropic, OpenAI, etc)
RUN --mount=type=cache,target=/root/.cache/pip,sharing=shared,id=pip-cache-core \
    pip install --prefix=/install --no-cache-dir \
    fastapi>=0.128.0 \
    uvicorn>=0.40.0 \
    pydantic>=2.12.0 \
    python-dotenv>=1.0.0 \
    aiohttp>=3.13.0 \
    python-multipart>=0.0.20 \
    psycopg2-binary>=2.9.0 \
    psutil>=7.2.0 \
    filelock>=3.20.0 \
    apscheduler>=3.10.0 \
    python-telegram-bot>=20.0.0 \
    meilisearch>=0.34.0 \
    paramiko>=3.4.0 \
    prometheus-client>=0.20.0 \
    pytz>=2024.1 \
    anthropic>=0.77.0 \
    openai>=1.0.0 \
    langfuse>=2.0.0 \
    google-api-python-client>=2.188.0 \
    google-auth>=2.48.0 \
    google-auth-oauthlib>=1.2.0 \
    google-auth-httplib2>=0.2.0 \
    beautifulsoup4>=4.12.0 \
    duckduckgo-search>=4.0.0 \
    google-cloud-storage>=2.20.0 \
    google-cloud-bigquery>=3.30.0 \
    requests>=2.32.0 \
    redis>=5.2.0 \
    pypdf>=3.0.0 \
    python-docx>=1.0.0 \
    radon>=6.0.0 \
    pylint>=3.0.0 \
    pytest>=8.0.0 \
    pytest-cov>=6.0.0

# Stage 4: Runtime (Layer 4)
# ========= APPLICATION CODE - CHANGES FREQUENTLY =========
FROM python:3.11-slim AS runtime

# TODO: Non-root user requires host volume permission setup:
# - chown -R 1000:1000 /volume1/BRAIN/index on NAS
# - Or use volume permission init container
# For now, running as root for volume compatibility
# ARG APP_USER=jarvis
# ARG APP_UID=1000
# ARG APP_GID=1000

WORKDIR /app

# Install minimal runtime system deps
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked,id=apt-cache \
    --mount=type=cache,target=/var/lib/apt,sharing=locked,id=apt-lib \
    apt-get update && \
    apt-get install -y --no-install-recommends \
    libpq5 \
    curl && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* && \
    chmod -R 755 /app

# Copy ALL compiled dependencies from core-deps stage
COPY --from=core-deps /install /usr/local

# Copy application code LAST (changes most frequently during development)
COPY app/ ./app

# Health check using curl (more reliable than Python requests)
# Note: --start-period=60s gives ML model time to load
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Production-optimized command (single worker for ML model memory efficiency)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
