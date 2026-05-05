# =============================================================================
# SKYMIRROR – Production Container
# MLSecOps hardening: non-root user, minimal surface, no secrets baked in
# =============================================================================

# ── Stage 1: dependency builder ───────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

# System libraries needed by Pillow
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libjpeg-dev libpng-dev libwebp-dev gcc \
    && rm -rf /var/lib/apt/lists/*

# Install build backend and package (layer-cached separately from source)
COPY pyproject.toml ./
RUN pip install --no-cache-dir hatchling

# Copy full source and install
COPY src/ ./src/
COPY governance/ ./governance/
COPY scripts/ ./scripts/
RUN pip install --no-cache-dir -e "."

# ── Stage 2: minimal runtime image ────────────────────────────────────────────
FROM python:3.11-slim AS runtime

# Security: system libraries only (no dev headers)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libjpeg62-turbo libpng16-16 libwebp7 \
        ca-certificates \
        tini \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Security: dedicated non-root user, no shell, no login
RUN groupadd -r skymirror \
    && useradd -r -g skymirror -d /app -s /sbin/nologin -c "SKYMIRROR service" skymirror

WORKDIR /app

# Copy installed Python packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code and static configs
COPY --from=builder --chown=skymirror:skymirror /build/src ./src
COPY --from=builder --chown=skymirror:skymirror /build/governance ./governance
COPY --from=builder --chown=skymirror:skymirror /build/scripts ./scripts
COPY --chown=skymirror:skymirror data/rag/ ./data/rag/
COPY --chown=skymirror:skymirror data/sources/ ./data/sources/

# Runtime-generated directories (mounted as volumes in production)
RUN mkdir -p \
        data/oa_log \
        data/reports \
        data/alerts \
        data/frames \
        data/dashboard \
    && chown -R skymirror:skymirror /app/data

# Drop privileges
USER skymirror

# Expose dashboard port (daemon mode uses no port)
EXPOSE 8000

# Healthcheck: verify governance policy loads cleanly
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "from skymirror.tools.governance import load_policy; load_policy(); print('ok')" \
    || exit 1

# tini as PID 1: proper signal forwarding + zombie reaping
ENTRYPOINT ["/usr/bin/tini", "--"]

# Default: run the camera analysis daemon
# Override with: docker run skymirror python -m skymirror.dashboard.server
CMD ["python", "-m", "skymirror.main"]
