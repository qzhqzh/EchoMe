"""Add ai_review memory status.

Revision ID: 005
Revises: 004
Create Date: 2026-05-23
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


NEW_STATUS_CHECK = "status IN ('active','ai_review','pending','deprecated','archived')"
OLD_STATUS_CHECK = "status IN ('active','pending','deprecated','archived')"


def upgrade() -> None:
    op.drop_constraint("valid_status", "memories", type_="check")
    op.create_check_constraint("valid_status", "memories", NEW_STATUS_CHECK)


def downgrade() -> None:
    op.execute("UPDATE memories SET status = 'pending' WHERE status = 'ai_review'")
    op.drop_constraint("valid_status", "memories", type_="check")
    op.create_check_constraint("valid_status", "memories", OLD_STATUS_CHECK)
