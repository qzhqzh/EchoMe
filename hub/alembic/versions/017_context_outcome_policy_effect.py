"""Add explicit context policy effect signals.

Revision ID: 017
Revises: 016
Create Date: 2026-08-23
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "017"
down_revision: Union[str, None] = "016"
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


def _index_is_valid(name: str) -> bool | None:
    return (
        op.get_bind()
        .execute(
            sa.text(
                """
            SELECT index_row.indisvalid
            FROM pg_index AS index_row
            JOIN pg_class AS index_class ON index_class.oid = index_row.indexrelid
            JOIN pg_namespace AS namespace ON namespace.oid = index_class.relnamespace
            WHERE index_class.relname = :name
              AND namespace.nspname = current_schema()
            """
            ),
            {"name": name},
        )
        .scalar_one_or_none()
    )


def _ensure_concurrent_index(name: str, table: str, columns: list[str]) -> None:
    state = _index_is_valid(name)
    if state is False:
        with op.get_context().autocommit_block():
            op.drop_index(
                name,
                table_name=table,
                postgresql_concurrently=True,
            )
        state = None
    if state is None:
        with op.get_context().autocommit_block():
            op.create_index(
                name,
                table,
                columns,
                postgresql_concurrently=True,
            )


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {item["name"] for item in inspector.get_columns("context_outcomes")}
    if "policy_effect" not in columns:
        op.add_column(
            "context_outcomes",
            sa.Column("policy_effect", sa.String(16), nullable=True),
        )

    constraint_name = "valid_context_outcome_policy_effect"
    constraint_state = _constraint_is_validated(
        constraint_name,
        "context_outcomes",
    )
    if constraint_state is None:
        op.create_check_constraint(
            constraint_name,
            "context_outcomes",
            "policy_effect IS NULL OR policy_effect IN ('helpful','neutral','harmful','uncertain')",
            postgresql_not_valid=True,
        )
        constraint_state = False
    if constraint_state is False:
        op.execute(
            sa.text(
                "ALTER TABLE context_outcomes "
                "VALIDATE CONSTRAINT valid_context_outcome_policy_effect"
            )
        )

    _ensure_concurrent_index(
        "idx_context_outcomes_policy_effect_created",
        "context_outcomes",
        ["user_id", "policy_effect", "created_at"],
    )
    _ensure_concurrent_index(
        "idx_context_runs_user_status_created",
        "context_runs",
        ["user_id", "status", "created_at"],
    )


def downgrade() -> None:
    # Expand-only rollback preserves append-only policy evidence for newer code.
    pass
