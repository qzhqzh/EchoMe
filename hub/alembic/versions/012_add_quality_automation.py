"""Add quality snapshots and proposal-only automation runs.

Revision ID: 012
Revises: 011
Create Date: 2026-08-12
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "012"
down_revision: Union[str, None] = "011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "context_quality_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=128), nullable=False),
        sa.Column("dataset_schema_version", sa.Integer(), nullable=False),
        sa.Column("k", sa.Integer(), nullable=False),
        sa.Column("trigger", sa.String(length=16), nullable=False),
        sa.Column("dry_run", sa.Boolean(), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("metrics", postgresql.JSONB(), nullable=False),
        sa.Column("thresholds", postgresql.JSONB(), nullable=False),
        sa.Column("report", postgresql.JSONB(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "trigger IN ('manual','background','ci')", name="valid_quality_snapshot_trigger"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "project_id", "idempotency_key", name="uq_quality_snapshot_idempotency"
        ),
    )
    op.create_index(
        "idx_quality_snapshots_project_created",
        "context_quality_snapshots",
        ["user_id", "project_id", "created_at"],
    )
    op.create_table(
        "automation_proposal_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=128), nullable=False),
        sa.Column("dry_run", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("gate", postgresql.JSONB(), nullable=False),
        sa.Column("plans", postgresql.JSONB(), nullable=False),
        sa.Column("generated_proposal_ids", postgresql.JSONB(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('dry_run','generated','gate_rejected')",
            name="valid_automation_proposal_run_status",
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "project_id", "idempotency_key", name="uq_automation_run_idempotency"
        ),
    )
    op.create_index(
        "idx_automation_runs_project_created",
        "automation_proposal_runs",
        ["user_id", "project_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("automation_proposal_runs")
    op.drop_table("context_quality_snapshots")
