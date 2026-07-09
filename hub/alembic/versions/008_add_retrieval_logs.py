"""Add retrieval logs table.

Revision ID: 008
Revises: 007
Create Date: 2026-07-09
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "retrieval_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("client", sa.String(length=32), nullable=False, server_default="web"),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="debugger"),
        sa.Column("status_filter", sa.String(length=16), nullable=True),
        sa.Column("project_id", sa.String(length=128), nullable=True),
        sa.Column("limit", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("lightweight_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("semantic_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fallback_used", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "expected_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("expected_rank", sa.Integer(), nullable=True),
        sa.Column(
            "top_results",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "steps",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_retrieval_logs_user_created", "retrieval_logs", ["user_id", "created_at"])
    op.create_index("idx_retrieval_logs_user_client", "retrieval_logs", ["user_id", "client"])
    op.alter_column("retrieval_logs", "client", server_default=None)
    op.alter_column("retrieval_logs", "source", server_default=None)
    op.alter_column("retrieval_logs", "limit", server_default=None)
    op.alter_column("retrieval_logs", "lightweight_count", server_default=None)
    op.alter_column("retrieval_logs", "semantic_count", server_default=None)
    op.alter_column("retrieval_logs", "fallback_used", server_default=None)
    op.alter_column("retrieval_logs", "expected_ids", server_default=None)
    op.alter_column("retrieval_logs", "top_results", server_default=None)
    op.alter_column("retrieval_logs", "steps", server_default=None)


def downgrade() -> None:
    op.drop_index("idx_retrieval_logs_user_client", table_name="retrieval_logs")
    op.drop_index("idx_retrieval_logs_user_created", table_name="retrieval_logs")
    op.drop_table("retrieval_logs")
