"""Add rebuildable context reliability assessments.

Revision ID: 016
Revises: 015
Create Date: 2026-08-23
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "016"
down_revision: Union[str, None] = "015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if "reliability_assessments" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "reliability_assessments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("project_id", sa.String(128), nullable=True),
        sa.Column("subject_type", sa.String(16), nullable=False),
        sa.Column("subject_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assessment_class", sa.String(24), nullable=False),
        sa.Column("support_state", sa.String(32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("reason_codes", postgresql.JSONB(), nullable=False),
        sa.Column("evidence_refs", postgresql.JSONB(), nullable=False),
        sa.Column("source_watermark", postgresql.JSONB(), nullable=False),
        sa.Column("source_fingerprint", sa.String(64), nullable=False),
        sa.Column("producer", sa.String(64), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("assessed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "subject_type IN ('memory','constraint','artifact')",
            name="valid_reliability_subject_type",
        ),
        sa.CheckConstraint(
            "assessment_class IN ('invariant','durable','environment_bound','volatile','episodic','unknown')",
            name="valid_reliability_assessment_class",
        ),
        sa.CheckConstraint(
            "support_state IN ('current_supported','historical','needs_verification','conflicting','dormant_scope','insufficient_evidence')",
            name="valid_reliability_support_state",
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="valid_reliability_confidence",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "subject_type",
            "subject_id",
            "source_fingerprint",
            name="uq_reliability_assessment_fingerprint",
        ),
    )
    op.create_index(
        "idx_reliability_subject_assessed",
        "reliability_assessments",
        ["user_id", "subject_type", "subject_id", "assessed_at"],
    )
    op.create_index(
        "idx_reliability_project_state",
        "reliability_assessments",
        ["user_id", "project_id", "support_state"],
    )


def downgrade() -> None:
    # Compatibility rollback keeps derived snapshots; they are safe to rebuild or ignore.
    pass
