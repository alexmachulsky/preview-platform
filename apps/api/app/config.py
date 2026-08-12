"""Runtime configuration, sourced entirely from the environment.

Every value has a local-friendly default so the service can be started with
``uvicorn app.main:app`` without any environment set up at all.
"""

from __future__ import annotations

import hashlib
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_DATABASE_URL = "postgresql+psycopg://preview:preview@localhost:5432/preview"

#: 360° / φ — successive multiples land as far apart on the colour wheel as a
#: sequence can, which is what makes consecutive previews visually distinct.
GOLDEN_ANGLE_DEGREES = 137.50776405003785


class Settings(BaseSettings):
    """Environment-driven settings for the API service."""

    model_config = SettingsConfigDict(extra="ignore", case_sensitive=False)

    database_url: str = DEFAULT_DATABASE_URL
    git_sha: str = "dev"
    pr_number: str = "local"
    app_env: str = "local"
    log_level: str = "INFO"

    #: Port for the metrics-only server. Deliberately not the application port:
    #: the Ingress routes `/` to that one, so anything served there is public,
    #: and `/metrics` describes internal request rates, paths and latencies.
    #: Prometheus scrapes the Service directly and never goes through the
    #: Ingress, so a second port costs nothing. 0 disables the server, which is
    #: what the tests use.
    metrics_port: int = 9000

    @property
    def short_sha(self) -> str:
        """First seven characters of the git SHA, the way humans read it."""
        return self.git_sha[:7] if self.git_sha else "dev"

    @property
    def hue(self) -> int:
        """Deterministic hue (0-359) derived from the PR number.

        Two previews open at once must be *obviously* different side by side,
        which a plain ``hash % 360`` cannot promise — sha256("42") and
        sha256("43") both land on hue 188, so PRs 42 and 43 would come out
        identical. Stepping by the golden angle instead puts consecutive PR
        numbers ~137° apart, the maximally-separated sequence, and stays fully
        deterministic across restarts and replicas.

        Non-numeric values (``local``, a branch name) fall back to a digest,
        where the collision risk is irrelevant because there is only one.
        """
        raw = str(self.pr_number).strip()
        if raw.isdigit():
            return int(int(raw) * GOLDEN_ANGLE_DEGREES) % 360
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        return int(digest[:8], 16) % 360


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    return Settings()
