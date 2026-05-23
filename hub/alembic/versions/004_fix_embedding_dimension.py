"""Fix embedding dimension: 1536 -> 1024 to match bge-m3 model

Revision ID: 004
Revises: 003
Create Date: 2026-05-23
"""
from typing import Sequence, Union

from alembic import op
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # bge-m3 model outputs 1024 dimensions, not 1536
    # All existing embeddings are NULL, so safe to alter
    op.alter_column(
        "memories",
        "embedding",
        type_=Vector(1024),
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "memories",
        "embedding",
        type_=Vector(1536),
        nullable=True,
    )
