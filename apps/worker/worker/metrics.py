"""Prometheus metrics for the worker.

Names are part of the platform contract — the Grafana dashboard and the
alert rules query them directly.
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

JOBS_PROCESSED = Counter(
    "worker_jobs_processed_total",
    "Jobs that completed successfully.",
)

JOBS_FAILED = Counter(
    "worker_jobs_failed_total",
    "Jobs that raised while being processed and were marked failed.",
)

POLL_ITERATIONS = Counter(
    "worker_poll_iterations_total",
    "Completed iterations of the polling loop, successful or not.",
)

JOBS_CLAIMED = Gauge(
    "worker_jobs_claimed_last_iteration",
    "Jobs claimed by the most recent poll — 0 means the queue was empty.",
)

JOB_DURATION = Histogram(
    "worker_job_duration_seconds",
    "Wall-clock time spent processing a single job.",
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

BUILD_INFO = Gauge(
    "worker_build_info",
    "Build and environment identity of the running worker, always 1.",
    ["git_sha", "pr_number", "app_env"],
)
