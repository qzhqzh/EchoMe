"""Add project constraint graph and artifact revisions.

Revision ID: 009
Revises: 008
Create Date: 2026-07-12
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "project_artifacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=128), nullable=False),
        sa.Column("logical_path", sa.String(length=1024), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("hash_algorithm", sa.String(length=16), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("source_uri", sa.String(length=2048), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("supersedes_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "kind IN ('requirement','design','document','issue','code','test','pr','commit','memory')",
            name="valid_project_artifact_kind",
        ),
        sa.CheckConstraint(
            "status IN ('current','stale','missing')", name="valid_project_artifact_status"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["supersedes_id"], ["project_artifacts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "project_id",
            "logical_path",
            "content_hash",
            name="uq_project_artifact_revision",
        ),
    )
    op.create_index(
        "idx_project_artifacts_project_status",
        "project_artifacts",
        ["user_id", "project_id", "status"],
    )
    op.create_index(
        "idx_project_artifacts_project_path",
        "project_artifacts",
        ["user_id", "project_id", "logical_path"],
    )

    op.create_table(
        "project_constraints",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=128), nullable=False),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("stability", sa.String(length=16), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("tags", postgresql.JSONB(), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("superseded_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "kind IN ('functional','nonfunctional','architecture','process','security','data','compatibility')",
            name="valid_project_constraint_kind",
        ),
        sa.CheckConstraint(
            "status IN ('proposed','active','uncertain','superseded','deprecated')",
            name="valid_project_constraint_status",
        ),
        sa.CheckConstraint(
            "stability IN ('invariant','evolving','temporary')",
            name="valid_project_constraint_stability",
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name="valid_constraint_confidence"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["superseded_by"], ["project_constraints.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_project_constraints_project_status",
        "project_constraints",
        ["user_id", "project_id", "status"],
    )
    op.create_index(
        "idx_project_constraints_project_kind",
        "project_constraints",
        ["user_id", "project_id", "kind"],
    )
    op.create_index(
        "idx_project_constraints_tags", "project_constraints", ["tags"], postgresql_using="gin"
    )

    op.create_table(
        "constraint_edges",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=128), nullable=False),
        sa.Column("source_constraint_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_constraint_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("relation", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "relation IN ('depends_on','conflicts_with','refines','supersedes','impacts')",
            name="valid_constraint_edge_relation",
        ),
        sa.ForeignKeyConstraint(["source_constraint_id"], ["project_constraints.id"]),
        sa.ForeignKeyConstraint(["target_constraint_id"], ["project_constraints.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "source_constraint_id",
            "target_constraint_id",
            "relation",
            name="uq_constraint_edge",
        ),
    )
    op.create_index("idx_constraint_edges_project", "constraint_edges", ["user_id", "project_id"])
    op.create_index("idx_constraint_edges_source", "constraint_edges", ["source_constraint_id"])
    op.create_index("idx_constraint_edges_target", "constraint_edges", ["target_constraint_id"])

    op.create_table(
        "constraint_evidence",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=128), nullable=False),
        sa.Column("constraint_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("artifact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("relation", sa.String(length=32), nullable=False),
        sa.Column("locator", postgresql.JSONB(), nullable=False),
        sa.Column("excerpt", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "relation IN ('originates_from','implemented_by','verified_by','discussed_in','violated_by')",
            name="valid_constraint_evidence_relation",
        ),
        sa.ForeignKeyConstraint(["artifact_id"], ["project_artifacts.id"]),
        sa.ForeignKeyConstraint(["constraint_id"], ["project_constraints.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "constraint_id",
            "artifact_id",
            "relation",
            name="uq_constraint_evidence",
        ),
    )
    op.create_index(
        "idx_constraint_evidence_project", "constraint_evidence", ["user_id", "project_id"]
    )
    op.create_index("idx_constraint_evidence_constraint", "constraint_evidence", ["constraint_id"])
    op.create_index("idx_constraint_evidence_artifact", "constraint_evidence", ["artifact_id"])


def downgrade() -> None:
    op.drop_table("constraint_evidence")
    op.drop_table("constraint_edges")
    op.drop_table("project_constraints")
    op.drop_table("project_artifacts")
