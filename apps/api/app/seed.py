"""Idempotent demo data.

Run as ``python -m app.seed`` from the api image. Safe to run on every
deploy: it only inserts rows that are not already there, so a restarted or
re-synced preview never accumulates duplicates.
"""

from __future__ import annotations

import logging
import sys

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_sessionmaker
from app.logging_config import configure_logging
from app.models import Job, Widget

logger = logging.getLogger("app.seed")

SEED_WIDGETS: tuple[tuple[str, str], ...] = (
    ("Ingress Controller", "#38bdf8"),
    ("Argo CD Application", "#f97316"),
    ("Prometheus Scrape", "#a855f7"),
    ("Grafana Dashboard", "#22c55e"),
    ("Namespace Quota", "#e11d48"),
)

SEED_JOBS: tuple[str, ...] = (
    "seed: reconcile widget inventory",
    "seed: warm the readiness cache",
    "seed: emit deployment heartbeat",
)


def seed(session: Session) -> tuple[int, int]:
    """Insert any missing demo rows. Returns ``(widgets_added, jobs_added)``."""
    existing_widgets = set(session.execute(select(Widget.name)).scalars().all())
    widgets_added = 0
    for name, color in SEED_WIDGETS:
        if name in existing_widgets:
            continue
        session.add(Widget(name=name, color=color))
        widgets_added += 1

    existing_jobs = set(session.execute(select(Job.payload)).scalars().all())
    jobs_added = 0
    for payload in SEED_JOBS:
        if payload in existing_jobs:
            continue
        session.add(Job(payload=payload, status="pending", attempts=0))
        jobs_added += 1

    session.commit()
    return widgets_added, jobs_added


def main() -> int:
    settings = get_settings()
    configure_logging(settings.log_level, service="seed", git_sha=settings.git_sha)
    try:
        with get_sessionmaker()() as session:
            widgets_added, jobs_added = seed(session)
    except SQLAlchemyError as exc:
        logger.error("seed failed", extra={"event": "seed.failed", "error": str(exc)})
        return 1

    logger.info(
        "seed complete",
        extra={"event": "seed.complete", "widgets_added": widgets_added, "jobs_added": jobs_added},
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
