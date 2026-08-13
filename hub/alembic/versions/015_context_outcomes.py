"""Add explicit append-only context outcomes.

Revision ID: 015
Revises: 014
Create Date: 2026-08-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "015"
down_revision: Union[str, None] = "014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if "context_outcomes" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "context_outcomes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("context_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("reported_by", sa.String(16), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("project_event_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "outcome IN ('success','partial','failed','corrected','no_signal')",
            name="valid_context_outcome",
        ),
        sa.CheckConstraint(
            "reported_by IN ('user','ai','system')", name="valid_context_outcome_reporter"
        ),
        sa.CheckConstraint(
            "source IN ('mcp','web','api','ci')", name="valid_context_outcome_source"
        ),
        sa.ForeignKeyConstraint(["context_run_id"], ["context_runs.id"]),
        sa.ForeignKeyConstraint(["project_event_id"], ["project_events.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "context_run_id",
            "idempotency_key",
            name="uq_context_outcome_idempotency",
        ),
    )
    op.create_index(
        "idx_context_outcomes_run_created",
        "context_outcomes",
        ["user_id", "context_run_id", "created_at"],
    )


def downgrade() -> None:
    # Expand-only compatibility rollback: outcomes are source evidence, not a derived cache.
    pass
