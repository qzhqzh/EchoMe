"""Add composite workspaces and auditable project membership.

Revision ID: 018
Revises: 017
Create Date: 2026-08-31
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "018"
down_revision: Union[str, None] = "017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _constraint_is_validated(name: str, table: str) -> bool | None:
    return (
        op.get_bind()
        .execute(
            sa.text(
                """
            SELECT constraint_row.convalidated
            FROM pg_constraint AS constraint_row
            WHERE constraint_row.conname = :name
              AND constraint_row.conrelid = to_regclass(:table)
            """
            ),
            {"name": name, "table": table},
        )
        .scalar_one_or_none()
    )


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    project_columns = {item["name"] for item in inspector.get_columns("projects")}
    if "kind" not in project_columns:
        op.add_column(
            "projects",
            sa.Column(
                "kind",
                sa.String(length=16),
                nullable=False,
                server_default="repository",
            ),
        )

    project_kind_constraint = "valid_project_kind"
    constraint_state = _constraint_is_validated(project_kind_constraint, "projects")
    if constraint_state is None:
        op.create_check_constraint(
            project_kind_constraint,
            "projects",
            "kind IN ('repository','workspace')",
            postgresql_not_valid=True,
        )
        constraint_state = False
    if constraint_state is False:
        op.execute(sa.text("ALTER TABLE projects VALIDATE CONSTRAINT valid_project_kind"))

    if "project_relations" in inspector.get_table_names():
        return
    op.create_table(
        "project_relations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("parent_project_id", sa.String(length=128), nullable=False),
        sa.Column("child_project_id", sa.String(length=128), nullable=False),
        sa.Column(
            "relation_type",
            sa.String(length=16),
            nullable=False,
            server_default="contains",
        ),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="active",
        ),
        sa.Column(
            "source",
            sa.String(length=32),
            nullable=False,
            server_default="manual",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "parent_project_id <> child_project_id",
            name="project_relation_not_self",
        ),
        sa.CheckConstraint(
            "relation_type IN ('contains')",
            name="valid_project_relation_type",
        ),
        sa.CheckConstraint(
            "status IN ('active','archived')",
            name="valid_project_relation_status",
        ),
        sa.CheckConstraint(
            "source IN ('manual','ai','imported','bootstrap')",
            name="valid_project_relation_source",
        ),
        sa.ForeignKeyConstraint(["child_project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["parent_project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "parent_project_id",
            "child_project_id",
            "relation_type",
            name="uq_project_relation_edge",
        ),
    )
    op.create_index(
        "idx_project_relations_parent_status",
        "project_relations",
        ["user_id", "parent_project_id", "status"],
    )
    op.create_index(
        "idx_project_relations_child_status",
        "project_relations",
        ["user_id", "child_project_id", "status"],
    )


def downgrade() -> None:
    # Expand-only rollback preserves project composition history for newer clients.
    pass
