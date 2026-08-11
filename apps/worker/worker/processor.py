"""Claim pending jobs, do the (simulated) work, record the outcome.

The claim uses ``SELECT ... FOR UPDATE SKIP LOCKED``, which is what makes the
worker horizontally scalable: two replicas polling the same table never hand
each other the same row, and neither of them blocks waiting for the other.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from worker.metrics import JOB_DURATION, JOBS_CLAIMED, JOBS_FAILED, JOBS_PROCESSED
from worker.models import STATUS_DONE, STATUS_FAILED, STATUS_PENDING, Job

logger = logging.getLogger("worker.processor")

#: Payloads beginning with this word fail on purpose. It keeps the failure
#: path demonstrable (and testable) without random flakiness in a demo.
FAILURE_MARKER = "fail"


class SimulatedJobError(RuntimeError):
    """Raised by the fake work function for payloads marked to fail."""


@dataclass(frozen=True)
class BatchResult:
    """What one poll accomplished."""

    claimed: int = 0
    processed: int = 0
    failed: int = 0

    @property
    def idle(self) -> bool:
        return self.claimed == 0


def simulate_work(job: Job, duration_seconds: float) -> None:
    """Stand-in for real work: burn a little wall-clock, then maybe fail."""
    if duration_seconds > 0:
        time.sleep(duration_seconds)
    if job.payload.strip().lower().startswith(FAILURE_MARKER):
        raise SimulatedJobError(f"payload for job {job.id} is marked to fail")


def claim_pending_jobs(session: Session, batch_size: int) -> list[Job]:
    """Lock up to ``batch_size`` pending rows, skipping ones already taken."""
    statement = (
        select(Job)
        .where(Job.status == STATUS_PENDING)
        .order_by(Job.id)
        .limit(batch_size)
        .with_for_update(skip_locked=True)
    )
    return list(session.execute(statement).scalars().all())


def process_batch(
    session_factory: sessionmaker[Session],
    batch_size: int = 5,
    work_duration_seconds: float = 0.2,
) -> BatchResult:
    """Run a single claim-work-complete cycle.

    The rows stay locked for the duration of the transaction, so a crash
    mid-batch rolls the jobs back to ``pending`` and another replica picks
    them up — at-least-once, which is why ``attempts`` is tracked.
    """
    processed = 0
    failed = 0

    with session_factory() as session, session.begin():
        jobs = claim_pending_jobs(session, batch_size)
        for job in jobs:
            job.attempts += 1
            started = time.perf_counter()
            try:
                simulate_work(job, work_duration_seconds)
            except Exception as exc:  # any failure marks the job failed, never the batch
                job.status = STATUS_FAILED
                failed += 1
                logger.warning(
                    "job failed",
                    extra={
                        "event": "job.failed",
                        "job_id": job.id,
                        "attempts": job.attempts,
                        "error": str(exc),
                    },
                )
            else:
                job.status = STATUS_DONE
                processed += 1
                logger.info(
                    "job done",
                    extra={
                        "event": "job.done",
                        "job_id": job.id,
                        "attempts": job.attempts,
                    },
                )
            finally:
                JOB_DURATION.observe(time.perf_counter() - started)
                job.updated_at = datetime.now(tz=timezone.utc)

    JOBS_PROCESSED.inc(processed)
    JOBS_FAILED.inc(failed)
    JOBS_CLAIMED.set(len(jobs))

    return BatchResult(claimed=len(jobs), processed=processed, failed=failed)
