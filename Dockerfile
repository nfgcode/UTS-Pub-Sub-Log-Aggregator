# =============================================================================
# Dockerfile — Pub-Sub Log Aggregator
# Base: python:3.11-slim | Non-root user | WAL SQLite dedup store
# =============================================================================

FROM python:3.11-slim

LABEL maintainer="student" \
      description="Pub-Sub Log Aggregator — UTS Sistem Terdistribusi"

# ---------------------------------------------------------------------------
# 1. System dependencies (minimal)
# ---------------------------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
    && rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------------------
# 2. Non-root user
# ---------------------------------------------------------------------------
RUN adduser --disabled-password --gecos '' appuser

# ---------------------------------------------------------------------------
# 3. Working directory & ownership
# ---------------------------------------------------------------------------
WORKDIR /app
RUN chown -R appuser:appuser /app

# ---------------------------------------------------------------------------
# 4. Persistent data directory (SQLite dedup store)
# ---------------------------------------------------------------------------
RUN mkdir -p /app/data && chown -R appuser:appuser /app/data
VOLUME ["/app/data"]

# ---------------------------------------------------------------------------
# 5. Switch ke non-root
# ---------------------------------------------------------------------------
USER appuser

# ---------------------------------------------------------------------------
# 6. Dependency caching layer (requirements.txt di-copy duluan)
# ---------------------------------------------------------------------------
COPY --chown=appuser:appuser requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# ---------------------------------------------------------------------------
# 7. Copy source code
# ---------------------------------------------------------------------------
COPY --chown=appuser:appuser src/ ./src/

# ---------------------------------------------------------------------------
# 8. Environment defaults
# ---------------------------------------------------------------------------
ENV DEDUP_DB_PATH=/app/data/dedup.db \
    QUEUE_MAX_SIZE=10000 \
    PORT=8080 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8080

# ---------------------------------------------------------------------------
# 9. Health check
# ---------------------------------------------------------------------------
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# ---------------------------------------------------------------------------
# 10. Entrypoint
# ---------------------------------------------------------------------------
CMD ["python", "-m", "src.main"]
