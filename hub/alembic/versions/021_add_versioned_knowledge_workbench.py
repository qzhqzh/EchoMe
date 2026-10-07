"""add versioned knowledge workbench

Revision ID: 021
Revises: 020
Create Date: 2026-10-06 06:50:39.401878
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "021"
down_revision: Union[str, None] = "020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "knowledge_agent_tokens",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("revoked", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_knowledge_tokens_user", "knowledge_agent_tokens", ["user_id"], unique=False)
    op.create_table(
        "knowledge_assets",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("filename", sa.String(length=256), nullable=False),
        sa.Column("media_type", sa.String(length=128), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_knowledge_assets_user", "knowledge_assets", ["user_id"], unique=False)
    op.create_table(
        "knowledge_records",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("project_id", sa.String(length=128), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "kind IN ('project','question','entity','relation','predicate','page','source','placement','usage','deliverable','review','acceptance')",
            name="ck_knowledge_record_kind",
        ),
        sa.CheckConstraint("revision > 0", name="ck_knowledge_record_revision"),
        sa.CheckConstraint(
            "jsonb_typeof(payload) = 'object' AND status = payload->>'status'",
            name="ck_knowledge_payload_status",
        ),
        sa.CheckConstraint(
            "kind = 'project' OR project_id IS NULL", name="ck_knowledge_project_identity"
        ),
        sa.CheckConstraint(
            "kind <> 'relation' OR ((payload->>'object_entity_id' IS NOT NULL) <> (payload->>'object_value' IS NOT NULL))",
            name="ck_knowledge_relation_object",
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "user_id", "kind", name="uq_knowledge_record_kind"),
        sa.UniqueConstraint("id", "user_id", name="uq_knowledge_record_owner"),
        sa.UniqueConstraint("project_id"),
    )
    op.create_index(
        "ix_knowledge_records_payload",
        "knowledge_records",
        ["payload"],
        unique=False,
        postgresql_using="gin",
    )
    op.create_index(
        "ix_knowledge_records_user_kind",
        "knowledge_records",
        ["user_id", "kind", "status", "updated_at"],
        unique=False,
    )
    op.create_index(
        "uq_knowledge_review_fingerprint",
        "knowledge_records",
        ["user_id", "fingerprint"],
        unique=True,
    )
    op.create_table(
        "knowledge_overviews",
        sa.Column("page_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("target_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["page_id", "user_id"],
            ["knowledge_records.id", "knowledge_records.user_id"],
        ),
        sa.ForeignKeyConstraint(
            ["target_id", "user_id"],
            ["knowledge_records.id", "knowledge_records.user_id"],
        ),
        sa.PrimaryKeyConstraint("page_id"),
        sa.UniqueConstraint("target_id", name="uq_knowledge_overview_target"),
    )
    op.create_index(
        "ix_knowledge_overviews_user_target",
        "knowledge_overviews",
        ["user_id", "target_id"],
        unique=False,
    )
    op.create_table(
        "knowledge_versions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("record_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("actor", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("revision > 0", name="ck_knowledge_version_revision"),
        sa.ForeignKeyConstraint(
            ["record_id", "user_id"],
            ["knowledge_records.id", "knowledge_records.user_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("record_id", "revision", name="uq_knowledge_version_number"),
        sa.UniqueConstraint("record_id", "user_id", "revision", name="uq_knowledge_version_owner"),
    )
    op.create_index(
        "ix_knowledge_versions_user_record",
        "knowledge_versions",
        ["user_id", "record_id"],
        unique=False,
    )
    op.create_table(
        "knowledge_decisions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("review_id", sa.UUID(), nullable=False),
        sa.Column("review_revision", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("actor", sa.String(length=128), nullable=False),
        sa.Column("results", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["review_id", "user_id", "review_revision"],
            [
                "knowledge_versions.record_id",
                "knowledge_versions.user_id",
                "knowledge_versions.revision",
            ],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_knowledge_decisions_user_review",
        "knowledge_decisions",
        ["user_id", "review_id"],
        unique=False,
    )
    op.create_table(
        "knowledge_references",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("owner_revision", sa.Integer(), nullable=False),
        sa.Column("target_id", sa.UUID(), nullable=False),
        sa.Column("target_kind", sa.String(length=24), nullable=False),
        sa.Column("target_revision", sa.Integer(), nullable=False),
        sa.Column("slot", sa.String(length=96), nullable=False),
        sa.ForeignKeyConstraint(
            ["owner_id", "user_id", "owner_revision"],
            [
                "knowledge_versions.record_id",
                "knowledge_versions.user_id",
                "knowledge_versions.revision",
            ],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["target_id", "user_id", "target_kind"],
            ["knowledge_records.id", "knowledge_records.user_id", "knowledge_records.kind"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["target_id", "user_id", "target_revision"],
            [
                "knowledge_versions.record_id",
                "knowledge_versions.user_id",
                "knowledge_versions.revision",
            ],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_knowledge_refs_owner",
        "knowledge_references",
        ["user_id", "owner_id", "owner_revision"],
        unique=False,
    )
    op.create_index(
        "ix_knowledge_refs_target",
        "knowledge_references",
        ["user_id", "target_id", "target_revision"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_knowledge_refs_target", table_name="knowledge_references")
    op.drop_index("ix_knowledge_refs_owner", table_name="knowledge_references")
    op.drop_table("knowledge_references")
    op.drop_index("ix_knowledge_decisions_user_review", table_name="knowledge_decisions")
    op.drop_table("knowledge_decisions")
    op.drop_index("ix_knowledge_versions_user_record", table_name="knowledge_versions")
    op.drop_table("knowledge_versions")
    op.drop_index("ix_knowledge_overviews_user_target", table_name="knowledge_overviews")
    op.drop_table("knowledge_overviews")
    op.drop_index("uq_knowledge_review_fingerprint", table_name="knowledge_records")
    op.drop_index("ix_knowledge_records_user_kind", table_name="knowledge_records")
    op.drop_index(
        "ix_knowledge_records_payload", table_name="knowledge_records", postgresql_using="gin"
    )
    op.drop_table("knowledge_records")
    op.drop_index("ix_knowledge_assets_user", table_name="knowledge_assets")
    op.drop_table("knowledge_assets")
    op.drop_index("ix_knowledge_tokens_user", table_name="knowledge_agent_tokens")
    op.drop_table("knowledge_agent_tokens")
