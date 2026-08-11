"""The claim-work-complete cycle, including the failure path."""

from __future__ import annotations

import pytest
from prometheus_client import REGISTRY
from sqlalchemy.orm import Session

from worker.models import STATUS_DONE, STATUS_FAILED, STATUS_PENDING, Job
from worker.processor import (
    SimulatedJobError,
    claim_pending_jobs,
    process_batch,
    simulate_work,
)

NO_WAIT = 0.0


def _enqueue(session: Session, payload: str, status: str = STATUS_PENDING) -> Job:
    job = Job(payload=payload, status=status, attempts=0)
    session.add(job)
    session.commit()
    return job


def test_claims_and_completes_a_pending_job(session_factory, db_session: Session) -> None:
    job = _enqueue(db_session, "process me")

    result = process_batch(session_factory, batch_size=5, work_duration_seconds=NO_WAIT)

    assert result.claimed == 1
    assert result.processed == 1
    assert result.failed == 0

    db_session.refresh(job)
    assert job.status == STATUS_DONE
    assert job.attempts == 1


def test_failed_job_is_marked_failed_with_attempts_incremented(
    session_factory, db_session: Session
) -> None:
    job = _enqueue(db_session, "fail: simulated explosion")

    result = process_batch(session_factory, batch_size=5, work_duration_seconds=NO_WAIT)

    assert result.claimed == 1
    assert result.processed == 0
    assert result.failed == 1

    db_session.refresh(job)
    assert job.status == STATUS_FAILED
    assert job.attempts == 1


def test_one_failure_does_not_poison_the_rest_of_the_batch(
    session_factory, db_session: Session
) -> None:
    good_one = _enqueue(db_session, "healthy job a")
    bad_one = _enqueue(db_session, "FAIL: uppercase marker still fails")
    good_two = _enqueue(db_session, "healthy job b")

    result = process_batch(session_factory, batch_size=10, work_duration_seconds=NO_WAIT)

    assert (result.claimed, result.processed, result.failed) == (3, 2, 1)

    for job, expected in (
        (good_one, STATUS_DONE),
        (bad_one, STATUS_FAILED),
        (good_two, STATUS_DONE),
    ):
        db_session.refresh(job)
        assert job.status == expected


def test_empty_queue_is_idle(session_factory, db_session: Session) -> None:
    result = process_batch(session_factory, batch_size=5, work_duration_seconds=NO_WAIT)

    assert result.claimed == 0
    assert result.idle is True


def test_batch_size_caps_the_claim(session_factory, db_session: Session) -> None:
    jobs = [_enqueue(db_session, f"job {index}") for index in range(5)]

    first = process_batch(session_factory, batch_size=2, work_duration_seconds=NO_WAIT)
    assert first.claimed == 2

    second = process_batch(session_factory, batch_size=2, work_duration_seconds=NO_WAIT)
    assert second.claimed == 2

    for job in jobs:
        db_session.refresh(job)
    assert [job.status for job in jobs].count(STATUS_PENDING) == 1


def test_done_jobs_are_not_reclaimed(session_factory, db_session: Session) -> None:
    _enqueue(db_session, "already handled", status=STATUS_DONE)
    _enqueue(db_session, "already broken", status=STATUS_FAILED)

    result = process_batch(session_factory, batch_size=10, work_duration_seconds=NO_WAIT)

    assert result.claimed == 0


def test_claim_query_orders_by_id(session_factory, db_session: Session) -> None:
    first = _enqueue(db_session, "first")
    second = _enqueue(db_session, "second")

    claimed = claim_pending_jobs(db_session, batch_size=10)

    assert [job.id for job in claimed] == [first.id, second.id]


def test_metrics_counters_advance(session_factory, db_session: Session) -> None:
    def value(name: str) -> float:
        return REGISTRY.get_sample_value(name) or 0.0

    before_done = value("worker_jobs_processed_total")
    before_failed = value("worker_jobs_failed_total")

    _enqueue(db_session, "metric ok")
    _enqueue(db_session, "fail: metric bad")
    process_batch(session_factory, batch_size=10, work_duration_seconds=NO_WAIT)

    assert value("worker_jobs_processed_total") == before_done + 1
    assert value("worker_jobs_failed_total") == before_failed + 1
    assert value("worker_jobs_claimed_last_iteration") == 2


def test_simulate_work_raises_only_for_marked_payloads() -> None:
    ok = Job(id=1, payload="a perfectly fine payload", status=STATUS_PENDING, attempts=0)
    simulate_work(ok, 0.0)

    bad = Job(id=2, payload="  fail me please ", status=STATUS_PENDING, attempts=0)
    with pytest.raises(SimulatedJobError):
        simulate_work(bad, 0.0)
