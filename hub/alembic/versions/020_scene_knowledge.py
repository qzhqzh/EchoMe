"""Add atomic, source-backed scene knowledge with revision history.

Revision ID: 020
Revises: 019
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "020"
down_revision: Union[str, None] = "019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "scene_knowledge",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("project_id", sa.String(128)),
        sa.Column("slug", sa.String(128), nullable=False),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("aliases", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("user_id", "slug", name="uq_scene_knowledge_user_slug"),
        sa.CheckConstraint("status IN ('active','archived')", name="valid_scene_knowledge_status"),
    )
    op.create_index(
        "idx_scene_knowledge_user_project", "scene_knowledge", ["user_id", "project_id"]
    )
    op.create_table(
        "scene_knowledge_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column(
            "scene_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("scene_knowledge.id"),
            nullable=False,
        ),
        sa.Column("category", sa.String(16), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source_ref", sa.Text(), nullable=False),
        sa.Column("origin_entry_id", postgresql.UUID(as_uuid=True)),
        sa.Column("evidence_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("validations", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("scene_id", "category", "number", name="uq_scene_entry_number"),
        sa.CheckConstraint(
            "category IN ('fact','observation','sop','caution','work')",
            name="valid_scene_entry_category",
        ),
        sa.CheckConstraint(
            "status IN ('active','needs_review','archived')", name="valid_scene_entry_status"
        ),
        sa.CheckConstraint("revision >= 1", name="valid_scene_entry_revision"),
    )
    op.create_index(
        "idx_scene_entries_user_scene",
        "scene_knowledge_entries",
        ["user_id", "scene_id", "category"],
    )
    op.create_table(
        "scene_knowledge_changes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column(
            "entry_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("scene_knowledge_entries.id"),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("entry_id", "revision", name="uq_scene_change_revision"),
        sa.CheckConstraint(
            "action IN ('add','correct','status')", name="valid_scene_change_action"
        ),
    )
    op.create_index(
        "idx_scene_changes_user_entry",
        "scene_knowledge_changes",
        ["user_id", "entry_id", "revision"],
    )


def downgrade() -> None:
    # Knowledge and correction history must not be silently destroyed by a downgrade.
    pass
