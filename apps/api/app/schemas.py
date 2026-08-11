"""Pydantic v2 request/response models."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class WidgetCreate(BaseModel):
    """Payload for ``POST /api/widgets``."""

    name: str = Field(min_length=1, max_length=100)
    color: str = Field(min_length=1, max_length=32)


class WidgetOut(BaseModel):
    """A widget as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    color: str
    created_at: datetime


class JobCreate(BaseModel):
    """Payload for ``POST /api/jobs``."""

    payload: str = Field(min_length=1, max_length=10_000)


class JobOut(BaseModel):
    """A job as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    payload: str
    status: str
    attempts: int
    created_at: datetime
    updated_at: datetime


class JobCounts(BaseModel):
    """How many jobs sit in each state."""

    pending: int = 0
    done: int = 0
    failed: int = 0

    @property
    def total(self) -> int:
        return self.pending + self.done + self.failed


class JobListOut(BaseModel):
    """``GET /api/jobs`` — the jobs themselves plus the status breakdown."""

    jobs: list[JobOut]
    counts: JobCounts


class VersionOut(BaseModel):
    """``GET /version`` — what a reviewer checks to confirm what is deployed."""

    service: str
    git_sha: str
    pr_number: str
    app_env: str


class HealthOut(BaseModel):
    """``GET /healthz`` and ``GET /readyz``."""

    status: str
    detail: str | None = None
