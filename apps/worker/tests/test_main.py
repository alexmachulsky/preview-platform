"""The polling loop itself: draining, bounded runs, and database blips."""

from __future__ import annotations

import threading
from dataclasses import replace

import pytest
from prometheus_client import REGISTRY
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from worker.config import Settings
from worker.main import run_loop
from worker.models import STATUS_DONE, STATUS_FAILED, STATUS_PENDING, Job

FAST = Settings(poll_interval_seconds=0.0, batch_size=10, work_duration_seconds=0.0)


def _enqueue(session: Session, payload: str) -> Job:
    job = Job(payload=payload, status=STATUS_PENDING, attempts=0)
    session.add(job)
    session.commit()
    return job


def test_loop_drains_the_queue(session_factory, db_session: Session) -> None:
    done_job = _enqueue(db_session, "loop me")
    failed_job = _enqueue(db_session, "fail: loop me too")

    iterations = run_loop(
        FAST,
        threading.Event(),
        max_iterations=1,
        session_factory=session_factory,
    )

    assert iterations == 1
    db_session.refresh(done_job)
    db_session.refresh(failed_job)
    assert done_job.status == STATUS_DONE
    assert failed_job.status == STATUS_FAILED


def test_loop_counts_poll_iterations(session_factory) -> None:
    def value() -> float:
        return REGISTRY.get_sample_value("worker_poll_iterations_total") or 0.0

    before = value()
    run_loop(FAST, threading.Event(), max_iterations=3, session_factory=session_factory)
    assert value() == before + 3


def test_loop_exits_immediately_when_already_stopped(session_factory) -> None:
    stop_event = threading.Event()
    stop_event.set()

    assert run_loop(FAST, stop_event, max_iterations=5, session_factory=session_factory) == 0


def test_loop_survives_a_database_error() -> None:
    """A Postgres blip must not take the pod down — log, wait, poll again."""

    class BrokenFactory:
        calls = 0

        def __call__(self) -> Session:
            BrokenFactory.calls += 1
            raise OperationalError("SELECT 1", None, Exception("connection reset"))

    broken = BrokenFactory()
    iterations = run_loop(FAST, threading.Event(), max_iterations=3, session_factory=broken)

    assert iterations == 3
    assert BrokenFactory.calls == 3


@pytest.mark.parametrize(
    ("interval", "expected"),
    [("0.5", 0.5), ("", 5.0), ("not-a-number", 5.0)],
)
def test_poll_interval_parsing(
    monkeypatch: pytest.MonkeyPatch, interval: str, expected: float
) -> None:
    monkeypatch.setenv("POLL_INTERVAL_SECONDS", interval)
    assert Settings.from_env().poll_interval_seconds == expected


def test_settings_defaults_match_the_platform_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("DATABASE_URL", "GIT_SHA", "POLL_INTERVAL_SECONDS", "LOG_LEVEL", "METRICS_PORT"):
        monkeypatch.delenv(name, raising=False)

    settings = Settings.from_env()
    assert settings.git_sha == "dev"
    assert settings.poll_interval_seconds == 5.0
    assert settings.metrics_port == 9000
    assert settings.log_level == "INFO"
    assert settings.database_url.startswith("postgresql+psycopg://preview:")
    assert replace(settings, git_sha="x").git_sha == "x"
