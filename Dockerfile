# Dockerfile — Production image for the a-sdlc combined MCP + UI server.
#
# Build:
#   docker build -t a-sdlc .
#
# Run standalone (Docker):
#   docker run -p 8765:8765 -p 3847:3847 -v asdlc-data:/data a-sdlc
#
# Run on Railway:
#   Railway injects a PORT env var.  The CLI reads it automatically so the
#   MCP server binds to $PORT.  Configure a Railway Volume mounted at /data.
#
# The image exposes two ports:
#   8765 — MCP server (streamable-http, /health endpoint)
#   3847 — Web UI dashboard
#
# Data is stored under /data (set via A_SDLC_DATA_DIR).  Mount a named volume
# or host directory to persist across container restarts.

# ---------------------------------------------------------------------------
# Stage 1: Build — install uv, copy source, install package
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS builder

# Avoid interactive prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive

# Install uv (fast Python package installer)
RUN pip install --no-cache-dir uv

WORKDIR /build

# Copy only dependency metadata first for better layer caching
COPY pyproject.toml README.md ./
COPY src/ src/

# Install the package with all extras into the system Python.
# --system avoids creating a virtual environment inside the container.
RUN uv pip install --system --no-cache ".[all]"

# Build-time tripwire: fail the build if the Alembic migrations did not ship
# inside the installed package. Startup auto-migration depends on these files
# being importable from a_sdlc/migrations; a silent omission would otherwise
# only surface as a schema drift at runtime.
RUN python -c "from a_sdlc.core.alembic_config import MIGRATIONS_DIR; assert (MIGRATIONS_DIR / 'versions' / '0001_baseline_v15.py').is_file(), f'packaged migrations missing: {MIGRATIONS_DIR}'; print(f'migrations OK: {MIGRATIONS_DIR}')"

# ---------------------------------------------------------------------------
# Stage 2: Runtime — slim image with only the installed package
# ---------------------------------------------------------------------------
FROM python:3.12-slim

# Install curl for the health check probe
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin/a-sdlc /usr/local/bin/a-sdlc

# Create non-root user for security
RUN groupadd --gid 1000 asdlc \
    && useradd --uid 1000 --gid asdlc --create-home asdlc

# Create and set permissions on the data directory
RUN mkdir -p /data && chown asdlc:asdlc /data

# Set environment variables
ENV A_SDLC_DATA_DIR=/data
ENV PYTHONUNBUFFERED=1
ENV A_SDLC_NO_BROWSER=1

# Expose MCP and UI ports
EXPOSE 8765 3847

# Health check against the MCP /health endpoint (PORT env var for Railway)
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD sh -c 'curl -sf http://localhost:${PORT:-8765}/health || exit 1'

# Run as non-root
USER asdlc

# Start the combined MCP + UI server, binding to all interfaces
ENTRYPOINT ["a-sdlc", "serve", "--host", "0.0.0.0"]
