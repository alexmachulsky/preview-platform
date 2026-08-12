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
 && /opt/venv/bin/pip install -r /tmp/requirements.txt \
 # Strip the build tooling out of the venv that gets copied into the runtime
 # image. Nothing at runtime imports pip, setuptools or wheel.
 #
 # This is also the entire fix for the image's fixable CVEs. Both of them —
 # msgpack GHSA-6v7p-g79w-8964 and setuptools CVE-2025-47273 — were reported
 # against packages pip *vendors*, which Trivy reads from pip's dist-info;
 # neither was ever imported by this application, and no setuptools package
 # exists in the image at all. Verified by building with and without this
 # line against the same base: 2 fixable findings become 0.
 && /opt/venv/bin/pip uninstall --yes pip setuptools wheel

# ── Runtime stage ─────────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

LABEL org.opencontainers.image.title="preview-platform-worker" \
      org.opencontainers.image.description="Polling worker draining the jobs queue in ephemeral PR environments" \
      org.opencontainers.image.source="https://github.com/alexmachulsky/preview-platform"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

# Same fixed UID/GID as the api image; the chart pins runAsUser/runAsGroup.
RUN groupadd --gid 10001 app \
 && useradd --uid 10001 --gid 10001 --no-create-home --home-dir /app --shell /usr/sbin/nologin app

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY --chown=10001:10001 worker ./worker

USER 10001:10001

# Metrics and health live here; there is no application traffic port.
EXPOSE 9000

CMD ["python", "-m", "worker"]
