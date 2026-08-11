"""Worker entrypoint: poll the jobs table forever, expose metrics on :9000."""

from __future__ import annotations

import logging
import signal
import threading
from types import FrameType

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from worker.config import Settings
from worker.db import create_session_factory, create_worker_engine
from worker.httpserver import start_metrics_server
from worker.logging_config import configure_logging
from worker.metrics import BUILD_INFO, POLL_ITERATIONS
from worker.processor import process_batch

logger = logging.getLogger("worker.main")


def install_signal_handlers(stop_event: threading.Event) -> None:
    """Turn SIGTERM/SIGINT into a clean exit from the poll loop.

    Kubernetes sends SIGTERM on pod deletion; finishing the current batch and
    then stopping means an in-flight job is never left half-processed.
    """

    def _handle(signum: int, _frame: FrameType | None) -> None:
        logger.info(
            "shutdown signal received",
            extra={"event": "shutdown.signal", "signal": signal.Signals(signum).name},
        )
        stop_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, _handle)


def run_loop(
    settings: Settings,
    stop_event: threading.Event,
    max_iterations: int | None = None,
    session_factory: sessionmaker[Session] | None = None,
) -> int:
    """Poll until ``stop_event`` is set. Returns the iteration count.

    ``max_iterations`` and ``session_factory`` are seams for the tests: they
    let the suite drive a bounded number of polls against a transaction it can
    roll back, through exactly the code path production uses.
    """
    engine = create_worker_engine(settings) if session_factory is None else None
    if session_factory is None:
        session_factory = create_session_factory(engine)
    iterations = 0

    try:
        while not stop_event.is_set():
            iterations += 1
            POLL_ITERATIONS.inc()
            try:
                result = process_batch(
                    session_factory,
                    batch_size=settings.batch_size,
                    work_duration_seconds=settings.work_duration_seconds,
                )
            except SQLAlchemyError as exc:
                # A database blip must not kill the pod: log, back off, retry.
                logger.error(
                    "poll failed",
                    extra={"event": "poll.failed", "error": str(exc)},
                )
            else:
                if not result.idle:
                    logger.info(
                        "batch complete",
                        extra={
                            "event": "poll.batch",
                            "claimed": result.claimed,
                            "processed": result.processed,
                            "failed": result.failed,
                        },
                    )

            if max_iterations is not None and iterations >= max_iterations:
                break
            stop_event.wait(settings.poll_interval_seconds)
    finally:
        if engine is not None:
            engine.dispose()

    return iterations


def main() -> int:
    settings = Settings.from_env()
    configure_logging(
        settings.log_level,
        service="worker",
        git_sha=settings.git_sha,
        pr_number=settings.pr_number,
        app_env=settings.app_env,
    )
    BUILD_INFO.labels(
        git_sha=settings.git_sha,
        pr_number=settings.pr_number,
        app_env=settings.app_env,
    ).set(1)

    stop_event = threading.Event()
    install_signal_handlers(stop_event)
    start_metrics_server(settings.metrics_port)

    logger.info(
        "worker starting",
        extra={
            "event": "startup",
            "poll_interval_seconds": settings.poll_interval_seconds,
            "batch_size": settings.batch_size,
        },
    )
    iterations = run_loop(settings, stop_event)
    logger.info("worker stopped", extra={"event": "shutdown", "iterations": iterations})
    return 0
