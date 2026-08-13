"""Add auditable canonical project aliases.

Revision ID: 013
Revises: 012
Create Date: 2026-08-12
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "013"
down_revision: Union[str, None] = "012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if "project_aliases" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "project_aliases",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("canonical_project_id", sa.String(length=128), nullable=False),
        sa.Column("alias_type", sa.String(length=16), nullable=False),
        sa.Column("alias_value", sa.String(length=2048), nullable=False),
        sa.Column("normalized_value", sa.String(length=2048), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "alias_type IN ('legacy_id','name','git_remote','path','client_hint')",
            name="valid_project_alias_type",
        ),
        sa.CheckConstraint(
            "status IN ('proposed','active','rejected','archived')",
            name="valid_project_alias_status",
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name="valid_project_alias_confidence"
        ),
        sa.ForeignKeyConstraint(["canonical_project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "alias_type",
            "normalized_value",
            name="uq_project_alias_normalized",
        ),
    )
    op.create_index(
        "idx_project_aliases_canonical_status",
        "project_aliases",
        ["user_id", "canonical_project_id", "status"],
    )


def downgrade() -> None:
    # Expand-only compatibility rollback: preserve user-reviewed alias evidence.
    pass
