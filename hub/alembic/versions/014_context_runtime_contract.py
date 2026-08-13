"""Add the context runtime observability contract.

Revision ID: 014
Revises: 013
Create Date: 2026-08-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "014"
down_revision: Union[str, None] = "013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("context_runs")}
    runtime_columns = {
        "request_id",
        "client",
        "client_version",
        "route",
        "fallback",
        "error_code",
    }
    if runtime_columns.issubset(columns):
        return
    op.alter_column("context_runs", "project_id", existing_type=sa.String(128), nullable=True)
    op.drop_constraint("valid_context_run_mode", "context_runs", type_="check")
    op.create_check_constraint(
        "valid_context_run_mode",
        "context_runs",
        "mode IN ('personal','local','overview','impact','temporal')",
    )
    op.add_column("context_runs", sa.Column("request_id", sa.String(64), nullable=True))
    op.add_column("context_runs", sa.Column("client", sa.String(64), nullable=True))
    op.add_column("context_runs", sa.Column("client_version", sa.String(64), nullable=True))
    op.add_column("context_runs", sa.Column("route", sa.String(16), nullable=True))
    op.add_column("context_runs", sa.Column("fallback", sa.String(32), nullable=True))
    op.add_column("context_runs", sa.Column("error_code", sa.String(64), nullable=True))
    op.create_index("idx_context_runs_request_id", "context_runs", ["user_id", "request_id"])


def downgrade() -> None:
    # Expand-only compatibility rollback: old code tolerates the additive columns,
    # while personal runs and runtime diagnostics remain intact for a later re-upgrade.
    pass
