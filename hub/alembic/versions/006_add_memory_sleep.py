"""Add memory sleep governance tables.

Revision ID: 006
Revises: 005
Create Date: 2026-06-04
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("memories", sa.Column("is_core", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column(
        "memories",
        sa.Column("sleep_state", sa.String(length=16), nullable=False, server_default="fresh"),
    )
    op.add_column("memories", sa.Column("last_accessed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "memories", sa.Column("access_count", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column("memories", sa.Column("superseded_by", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column(
        "memories",
        sa.Column(
            "derived_from",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.create_foreign_key(
        "fk_memories_superseded_by_memories",
        "memories",
        "memories",
        ["superseded_by"],
        ["id"],
    )
    op.create_check_constraint(
        "valid_sleep_state",
        "memories",
        "sleep_state IN ('fresh','reviewed','distilled','superseded')",
    )
    op.create_index("idx_memories_user_sleep_state", "memories", ["user_id", "sleep_state"])

    op.create_table(
        "sleep_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column(
            "candidate_memory_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("text_proposal", sa.Text(), nullable=True),
        sa.Column("json_proposal", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_by",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('draft','proposed','approved','applied','rejected')",
            name="valid_sleep_session_status",
        ),
        sa.CheckConstraint(
            "mode IN ('server_generated','client_generated')",
            name="valid_sleep_session_mode",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_sleep_sessions_user_status", "sleep_sessions", ["user_id", "status"])
    op.create_index("idx_sleep_sessions_user_project", "sleep_sessions", ["user_id", "project_id"])

    op.create_table(
        "memory_edges",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("source_memory_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_memory_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("relation", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("sleep_session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_by", sa.String(length=32), nullable=False, server_default="sleep"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "relation IN ('derived_from','supersedes','superseded_by','duplicates',"
            "'conflicts_with','specializes','related_to')",
            name="valid_memory_edge_relation",
        ),
        sa.ForeignKeyConstraint(["source_memory_id"], ["memories.id"]),
        sa.ForeignKeyConstraint(["target_memory_id"], ["memories.id"]),
        sa.ForeignKeyConstraint(["sleep_session_id"], ["sleep_sessions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_memory_edges_user_source", "memory_edges", ["user_id", "source_memory_id"])
    op.create_index("idx_memory_edges_user_target", "memory_edges", ["user_id", "target_memory_id"])
    op.create_index("idx_memory_edges_sleep_session", "memory_edges", ["sleep_session_id"])

    op.alter_column("memories", "is_core", server_default=None)
    op.alter_column("memories", "sleep_state", server_default=None)
    op.alter_column("memories", "access_count", server_default=None)
    op.alter_column("memories", "derived_from", server_default=None)


def downgrade() -> None:
    op.drop_index("idx_memory_edges_sleep_session", table_name="memory_edges")
    op.drop_index("idx_memory_edges_user_target", table_name="memory_edges")
    op.drop_index("idx_memory_edges_user_source", table_name="memory_edges")
    op.drop_table("memory_edges")

    op.drop_index("idx_sleep_sessions_user_project", table_name="sleep_sessions")
    op.drop_index("idx_sleep_sessions_user_status", table_name="sleep_sessions")
    op.drop_table("sleep_sessions")

    op.drop_index("idx_memories_user_sleep_state", table_name="memories")
    op.drop_constraint("valid_sleep_state", "memories", type_="check")
    op.drop_constraint("fk_memories_superseded_by_memories", "memories", type_="foreignkey")
    op.drop_column("memories", "derived_from")
    op.drop_column("memories", "superseded_by")
    op.drop_column("memories", "access_count")
    op.drop_column("memories", "last_accessed_at")
    op.drop_column("memories", "sleep_state")
    op.drop_column("memories", "is_core")
