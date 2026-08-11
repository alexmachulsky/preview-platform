"""initial schema: widgets and jobs

Revision ID: 0001
Revises:
Create Date: 2026-08-10

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "widgets",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("color", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_widgets"),
        sa.UniqueConstraint("name", name="uq_widgets_name"),
    )

    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("status IN ('pending', 'done', 'failed')", name="ck_jobs_status"),
        sa.PrimaryKeyConstraint("id", name="pk_jobs"),
    )
    # The worker polls WHERE status = 'pending' ORDER BY id, so this index is
    # what keeps SELECT ... FOR UPDATE SKIP LOCKED cheap as the table grows.
    op.create_index("ix_jobs_status_id", "jobs", ["status", "id"])


def downgrade() -> None:
    op.drop_index("ix_jobs_status_id", table_name="jobs")
    op.drop_table("jobs")
    op.drop_table("widgets")
