"""Engine and session factory for the worker."""

from __future__ import annotations

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from worker.config import Settings


def create_worker_engine(settings: Settings) -> Engine:
    """Build the engine.

    ``pool_pre_ping`` matters more here than in the api: the worker holds a
    long-lived connection through quiet periods, and a Postgres pod that was
    rescheduled underneath it must not poison every future poll.
    """
    return create_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_size=2,
        max_overflow=2,
        pool_recycle=1800,
        future=True,
    )


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
