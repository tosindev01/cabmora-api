# syntax=docker/dockerfile:1
#
# Cabmora API — FastAPI
#
# Multi-stage: wheels are built in a stage that carries the compilers, then
# installed into a slim runtime that does not. Keeps the final image small and
# free of build toolchain.

# ─────────────────────────────────────────────────────────────
# Stage 1 — build wheels
# ─────────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

# bcrypt / asyncpg / cryptography may need to compile if no wheel matches.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY requirements.txt .
RUN pip wheel --wheel-dir /wheels -r requirements.txt


# ─────────────────────────────────────────────────────────────
# Stage 2 — runtime
# ─────────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

# curl is used by the compose healthcheck.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Non-root. Containers should never run the app as uid 0.
RUN useradd --create-home --uid 1000 cabmora

WORKDIR /app

COPY --from=builder /wheels /wheels
COPY requirements.txt .
RUN pip install --no-index --find-links=/wheels -r requirements.txt \
    && rm -rf /wheels

COPY --chown=cabmora:cabmora . .

USER cabmora

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD curl -fsS http://localhost:${PORT:-8000}/api/v1/health || exit 1

# Migrations run once, before the app, and the container exits if they fail —
# far better than serving requests against a schema that is behind the code.
#
# Shell form is required, not stylistic: Railway injects PORT at runtime and
# exec form would pass the literal string "$PORT" to uvicorn.
#
# Workers: DDL no longer happens at boot (create_tables() is gone), so the
# single-worker constraint that used to exist here is lifted — `alembic upgrade`
# takes a lock and runs once regardless of worker count.
# --host 0.0.0.0, and do NOT "fix" this to `::`.
#
# That was tried (2026-09-02) on the theory that Railway's private network is
# IPv6-only and an IPv4 bind would refuse the nginx proxies. Both halves were
# wrong. Measured from inside the running container:
#
#   curl http://[::1]:8000/api/v1/health      -> 200
#   curl http://127.0.0.1:8000/api/v1/health  -> connection refused
#
# uvicorn's socket comes out V6ONLY even though the container has
# net.ipv6.bindv6only=0, so `::` serves the private mesh and refuses Railway's
# public edge, which connects over IPv4 — every public request 502s while the
# logs show a perfectly healthy "Application startup complete".
#
# 0.0.0.0 serves both: the public edge directly, and the private mesh, which
# reaches an IPv4-bound listener without complaint.
CMD alembic upgrade head && \
    uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
