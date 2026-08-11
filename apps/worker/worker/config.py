"""Environment-driven configuration.

Deliberately dependency-free — the worker has no HTTP framework and no
settings library, so a stdlib dataclass is the whole story.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_DATABASE_URL = "postgresql+psycopg://preview:preview@localhost:5432/preview"


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    """Everything the worker reads from its environment."""

    database_url: str = DEFAULT_DATABASE_URL
    git_sha: str = "dev"
    pr_number: str = "local"
    app_env: str = "local"
    log_level: str = "INFO"
    poll_interval_seconds: float = 5.0
    metrics_port: int = 9000
    batch_size: int = 5
    work_duration_seconds: float = 0.2

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            database_url=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL),
            git_sha=os.environ.get("GIT_SHA", "dev"),
            pr_number=os.environ.get("PR_NUMBER", "local"),
            app_env=os.environ.get("APP_ENV", "local"),
            log_level=os.environ.get("LOG_LEVEL", "INFO"),
            poll_interval_seconds=_env_float("POLL_INTERVAL_SECONDS", 5.0),
            metrics_port=_env_int("METRICS_PORT", 9000),
            batch_size=_env_int("BATCH_SIZE", 5),
            work_duration_seconds=_env_float("WORK_DURATION_SECONDS", 0.2),
        )
