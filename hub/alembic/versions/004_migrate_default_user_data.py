"""Migrate data from default user_id to first admin user.

When multi-user was added, existing data kept user_id='default'.
This migration reassigns all 'default' user data to the first admin user.
If no admin user exists yet, data stays as 'default' (will be claimed on first login).

Revision ID: 004
Revises: 003
Create Date: 2026-05-22
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Find the first admin user (if exists)
    conn = op.get_bind()
    result = conn.execute(
        sa.text("SELECT id FROM users WHERE role = 'admin' ORDER BY created_at LIMIT 1")
    )
    row = result.fetchone()

    if row is not None:
        admin_id = str(row[0])
        # Reassign all 'default' user data to the admin
        conn.execute(
            sa.text("UPDATE memories SET user_id = :uid WHERE user_id = 'default'"),
            {"uid": admin_id},
        )
        conn.execute(
            sa.text("UPDATE projects SET user_id = :uid WHERE user_id = 'default'"),
            {"uid": admin_id},
        )
        conn.execute(
            sa.text("UPDATE sync_log SET user_id = :uid WHERE user_id = 'default'"),
            {"uid": admin_id},
        )


def downgrade() -> None:
    # Can't reliably reverse - data stays assigned
    pass
