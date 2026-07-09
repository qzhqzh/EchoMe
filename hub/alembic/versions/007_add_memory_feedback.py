"""Add memory feedback table.

Revision ID: 007
Revises: 006
Create Date: 2026-07-09
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "memory_feedback",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("memory_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rating", sa.String(length=24), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("task_context", sa.Text(), nullable=True),
        sa.Column("used_by", sa.String(length=16), nullable=False, server_default="ai"),
        sa.Column("confidence", sa.String(length=8), nullable=False, server_default="medium"),
        sa.Column("source", sa.String(length=16), nullable=False, server_default="mcp"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "rating IN ('helpful','irrelevant','outdated','conflicting','wrong','important')",
            name="valid_memory_feedback_rating",
        ),
        sa.CheckConstraint(
            "confidence IN ('low','medium','high')",
            name="valid_memory_feedback_confidence",
        ),
        sa.CheckConstraint(
            "used_by IN ('ai','user','system')",
            name="valid_memory_feedback_used_by",
        ),
        sa.CheckConstraint(
            "source IN ('mcp','web','api')",
            name="valid_memory_feedback_source",
        ),
        sa.ForeignKeyConstraint(["memory_id"], ["memories.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_memory_feedback_user_memory", "memory_feedback", ["user_id", "memory_id"])
    op.create_index("idx_memory_feedback_user_rating", "memory_feedback", ["user_id", "rating"])
    op.create_index("idx_memory_feedback_created_at", "memory_feedback", ["created_at"])

    op.alter_column("memory_feedback", "used_by", server_default=None)
    op.alter_column("memory_feedback", "confidence", server_default=None)
    op.alter_column("memory_feedback", "source", server_default=None)


def downgrade() -> None:
    op.drop_index("idx_memory_feedback_created_at", table_name="memory_feedback")
    op.drop_index("idx_memory_feedback_user_rating", table_name="memory_feedback")
    op.drop_index("idx_memory_feedback_user_memory", table_name="memory_feedback")
    op.drop_table("memory_feedback")
