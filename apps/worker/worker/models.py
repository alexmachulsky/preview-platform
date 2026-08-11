"""The slice of the schema the worker cares about.

Only ``jobs`` is modelled here. Migrations are owned by the api service —
this is a read/write client of a table someone else creates, which is why
there is no Alembic directory in this image.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

STATUS_PENDING = "pending"
STATUS_DONE = "done"
STATUS_FAILED = "failed"


class Base(DeclarativeBase):
    """Declarative base for the worker's view of the schema."""


class Job(Base):
    """Unit of background work."""

    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'done', 'failed')",
            name="ck_jobs_status",
        ),
        Index("ix_jobs_status_id", "status", "id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=STATUS_PENDING)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<Job id={self.id} status={self.status!r}>"
