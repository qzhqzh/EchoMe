"""Initial schema: memories, projects, sync_log

Revision ID: 001
Revises: None
Create Date: 2026-05-21
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "memories",
        sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", sa.String(64), nullable=False, server_default="default"),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("layer", sa.String(4), nullable=False),
        sa.Column("scope_global", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("scope_projects", sa.dialects.postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("scope_exclude", sa.dialects.postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("priority", sa.SmallInteger(), nullable=False, server_default="5"),
        sa.Column("tags", sa.dialects.postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("source", sa.String(32), nullable=False, server_default="manual"),
        sa.Column("token_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("embedding", Vector(1024), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "type IN ('persona','workflow','tech','constraint','snippet',"
            "'decision','knowledge','interaction','project')",
            name="valid_type",
        ),
        sa.CheckConstraint("layer IN ('L0','L1','L2')", name="valid_layer"),
        sa.CheckConstraint("status IN ('active','ai_review','pending','deprecated','archived')", name="valid_status"),
        sa.CheckConstraint("priority BETWEEN 1 AND 10", name="valid_priority"),
    )

    op.create_index("idx_memories_user_type", "memories", ["user_id", "type"])
    op.create_index("idx_memories_user_layer", "memories", ["user_id", "layer"])
    op.create_index("idx_memories_user_status", "memories", ["user_id", "status"])
    op.create_index("idx_memories_tags", "memories", ["tags"], postgresql_using="gin")
    op.create_index("idx_memories_scope_projects", "memories", ["scope_projects"], postgresql_using="gin")

    op.create_table(
        "projects",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("user_id", sa.String(64), nullable=False, server_default="default"),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("git_remote", sa.String(512), nullable=True),
        sa.Column("path_patterns", sa.dialects.postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "sync_log",
        sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", sa.String(64), nullable=False, server_default="default"),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("memories_affected", sa.dialects.postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("client_info", sa.String(256), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )


def downgrade() -> None:
    op.drop_table("sync_log")
    op.drop_table("projects")
    op.drop_index("idx_memories_scope_projects", table_name="memories")
    op.drop_index("idx_memories_tags", table_name="memories")
    op.drop_index("idx_memories_user_status", table_name="memories")
    op.drop_index("idx_memories_user_layer", table_name="memories")
    op.drop_index("idx_memories_user_type", table_name="memories")
    op.drop_table("memories")
