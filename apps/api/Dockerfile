# syntax=docker/dockerfile:1

# ── Build stage ───────────────────────────────────────────────────────────────
# The venv is assembled here and copied whole into the runtime stage, so pip's
# working files and any transient build tooling never reach the shipped image.
FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build

COPY pyproject.toml ./

# pyproject.toml stays the single source of truth for the pins — the
# requirements list is derived from it rather than duplicated in a second file.
RUN python -m venv /opt/venv \
 && python -c "import tomllib; print('\n'.join(tomllib.load(open('pyproject.toml','rb'))['project']['dependencies']))" \
      > /tmp/requirements.txt \
 && /opt/venv/bin/pip install --upgrade pip \
 && /opt/venv/bin/pip install -r /tmp/requirements.txt

# ── Runtime stage ─────────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

LABEL org.opencontainers.image.title="preview-platform-api" \
      org.opencontainers.image.description="FastAPI demo workload for ephemeral PR environments" \
      org.opencontainers.image.source="https://github.com/alexmachulsky/preview-platform"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

# Fixed UID/GID 10001: the Helm chart pins runAsUser/runAsGroup to the same
# numbers, and the pod runs with runAsNonRoot.
RUN groupadd --gid 10001 app \
 && useradd --uid 10001 --gid 10001 --no-create-home --home-dir /app --shell /usr/sbin/nologin app

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY --chown=10001:10001 alembic.ini ./alembic.ini
COPY --chown=10001:10001 alembic ./alembic
COPY --chown=10001:10001 app ./app

USER 10001:10001

EXPOSE 8000

# Migrations run from this same image: `alembic upgrade head` with WORKDIR /app.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
