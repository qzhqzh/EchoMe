"""Add context compiler indexes, freshness views, and project events.

Revision ID: 011
Revises: 010
Create Date: 2026-08-12
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "011"
down_revision: Union[str, None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "uq_project_artifacts_current_path",
        "project_artifacts",
        ["user_id", "project_id", "logical_path"],
        unique=True,
        postgresql_where=sa.text("status = 'current'"),
    )
    op.create_unique_constraint(
        "uq_project_constraints_previous_version",
        "project_constraints",
        ["previous_version_id"],
    )
    op.add_column(
        "project_constraints",
        sa.Column("embedding", Vector(1024), nullable=True),
    )
    op.create_index(
        "idx_project_constraints_embedding_hnsw",
        "project_constraints",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )

    for table_name in ("constraint_edges", "constraint_evidence"):
        op.add_column(
            table_name,
            sa.Column("observed_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.add_column(
            table_name,
            sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        )
        op.add_column(
            table_name,
            sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        )
        op.add_column(
            table_name,
            sa.Column("invalidated_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.add_column(
            table_name,
            sa.Column(
                "source_metadata",
                postgresql.JSONB(),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
        )
        op.alter_column(table_name, "source_metadata", server_default=None)

    op.create_table(
        "artifact_chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=128), nullable=False),
        sa.Column("artifact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("locator", postgresql.JSONB(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("embedding", Vector(1024), nullable=True),
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('simple', content)", persisted=True),
            nullable=False,
        ),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("producer", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["artifact_id"], ["project_artifacts.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("artifact_id", "ordinal", name="uq_artifact_chunk_ordinal"),
    )
    op.create_index("idx_artifact_chunks_project", "artifact_chunks", ["user_id", "project_id"])
    op.create_index("idx_artifact_chunks_artifact", "artifact_chunks", ["artifact_id"])
    op.create_index(
        "idx_artifact_chunks_fts",
        "artifact_chunks",
        ["search_vector"],
        postgresql_using="gin",
    )
    op.create_index(
        "idx_artifact_chunks_embedding_hnsw",
        "artifact_chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )

    op.create_table(
        "context_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=128), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("changed_paths", postgresql.JSONB(), nullable=False),
        sa.Column("token_budget", sa.Integer(), nullable=False),
        sa.Column("token_used", sa.Integer(), nullable=False),
        sa.Column("candidates", postgresql.JSONB(), nullable=False),
        sa.Column("selected", postgresql.JSONB(), nullable=False),
        sa.Column("trace", postgresql.JSONB(), nullable=False),
        sa.Column("shadow", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("mode IN ('local','overview','impact')", name="valid_context_run_mode"),
        sa.CheckConstraint("status IN ('completed','failed')", name="valid_context_run_status"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_context_runs_project_created",
        "context_runs",
        ["user_id", "project_id", "created_at"],
    )

    op.create_table(
        "knowledge_views",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=128), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("query", sa.Text(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source_watermark", postgresql.JSONB(), nullable=False),
        sa.Column("refresh_mode", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("producer", sa.String(length=64), nullable=False),
        sa.Column("supersedes_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("stale_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "kind IN ('summary','mental_model','community')", name="valid_knowledge_view_kind"
        ),
        sa.CheckConstraint(
            "refresh_mode IN ('manual','derived')", name="valid_knowledge_view_refresh_mode"
        ),
        sa.CheckConstraint(
            "status IN ('current','stale','superseded')", name="valid_knowledge_view_status"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["supersedes_id"], ["knowledge_views.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_knowledge_views_project_status",
        "knowledge_views",
        ["user_id", "project_id", "status"],
    )

    op.create_table(
        "constraint_revalidation_proposals",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=128), nullable=False),
        sa.Column("constraint_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("base_version", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("proposal", postgresql.JSONB(), nullable=False),
        sa.Column("source_refs", postgresql.JSONB(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_by", sa.String(length=16), nullable=False),
        sa.Column("applied_constraint_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending','applied','rejected','expired')",
            name="valid_constraint_revalidation_status",
        ),
        sa.ForeignKeyConstraint(["applied_constraint_id"], ["project_constraints.id"]),
        sa.ForeignKeyConstraint(["constraint_id"], ["project_constraints.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "project_id",
            "idempotency_key",
            name="uq_constraint_revalidation_idempotency",
        ),
    )
    op.create_index(
        "idx_constraint_revalidation_project_status",
        "constraint_revalidation_proposals",
        ["user_id", "project_id", "status"],
    )

    op.create_table(
        "project_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=128), nullable=False),
        sa.Column("event_type", sa.String(length=24), nullable=False),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("source_ref", sa.String(length=2048), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "event_type IN ('issue','attempt','failure','fix','decision','test_result','deploy','note')",
            name="valid_project_event_type",
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "project_id", "idempotency_key", name="uq_project_event_idempotency"
        ),
    )
    op.create_index(
        "idx_project_events_project_time",
        "project_events",
        ["user_id", "project_id", "occurred_at"],
    )
    op.create_index(
        "idx_project_events_project_type",
        "project_events",
        ["user_id", "project_id", "event_type"],
    )

    op.create_table(
        "event_links",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=128), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_type", sa.String(length=16), nullable=False),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("relation", sa.String(length=32), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "target_type IN ('memory','constraint','artifact','event')",
            name="valid_event_link_target_type",
        ),
        sa.ForeignKeyConstraint(["event_id"], ["project_events.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "event_id",
            "target_type",
            "target_id",
            "relation",
            name="uq_event_link",
        ),
    )
    op.create_index("idx_event_links_project", "event_links", ["user_id", "project_id"])
    op.create_index("idx_event_links_event", "event_links", ["event_id"])
    op.create_index("idx_event_links_target", "event_links", ["target_type", "target_id"])


def downgrade() -> None:
    op.drop_table("event_links")
    op.drop_table("project_events")
    op.drop_table("constraint_revalidation_proposals")
    op.drop_table("knowledge_views")
    op.drop_table("context_runs")
    op.drop_table("artifact_chunks")

    for table_name in ("constraint_evidence", "constraint_edges"):
        op.drop_column(table_name, "source_metadata")
        op.drop_column(table_name, "invalidated_at")
        op.drop_column(table_name, "valid_to")
        op.drop_column(table_name, "valid_from")
        op.drop_column(table_name, "observed_at")

    op.drop_constraint(
        "uq_project_constraints_previous_version",
        "project_constraints",
        type_="unique",
    )
    op.drop_index("idx_project_constraints_embedding_hnsw", table_name="project_constraints")
    op.drop_column("project_constraints", "embedding")
    op.drop_index("uq_project_artifacts_current_path", table_name="project_artifacts")
