"""Add explicit project constraint versions.

Revision ID: 010
Revises: 009
Create Date: 2026-07-12
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "project_constraints",
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "project_constraints",
        sa.Column("previous_version_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_project_constraints_previous_version",
        "project_constraints",
        "project_constraints",
        ["previous_version_id"],
        ["id"],
    )
    op.create_index(
        "idx_project_constraints_previous_version",
        "project_constraints",
        ["previous_version_id"],
    )
    op.alter_column("project_constraints", "version", server_default=None)


def downgrade() -> None:
    op.drop_index("idx_project_constraints_previous_version", table_name="project_constraints")
    op.drop_constraint(
        "fk_project_constraints_previous_version", "project_constraints", type_="foreignkey"
    )
    op.drop_column("project_constraints", "previous_version_id")
    op.drop_column("project_constraints", "version")
