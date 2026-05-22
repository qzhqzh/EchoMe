"""Rename memory types and add reasoning type.

persona → identity
workflow → method
tech → stack
constraint → guardrail
snippet → template
knowledge → context
interaction → style
+ add: reasoning

Revision ID: 003
Revises: 002
Create Date: 2026-05-22
"""
from typing import Sequence, Union

from alembic import op

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Mapping: old → new
TYPE_RENAMES = [
    ("persona", "identity"),
    ("workflow", "method"),
    ("tech", "stack"),
    ("constraint", "guardrail"),
    ("snippet", "template"),
    ("knowledge", "context"),
    ("interaction", "style"),
]

NEW_TYPES = "('identity','method','stack','guardrail','template','decision','context','style','project','reasoning')"
OLD_TYPES = "('persona','workflow','tech','constraint','snippet','decision','knowledge','interaction','project')"


def upgrade() -> None:
    # Drop old constraint
    op.drop_constraint("valid_type", "memories", type_="check")

    # Rename existing type values
    for old, new in TYPE_RENAMES:
        op.execute(f"UPDATE memories SET type = '{new}' WHERE type = '{old}'")

    # Create new constraint with updated values
    op.create_check_constraint(
        "valid_type",
        "memories",
        f"type IN {NEW_TYPES}",
    )


def downgrade() -> None:
    # Drop new constraint
    op.drop_constraint("valid_type", "memories", type_="check")

    # Reverse rename
    for old, new in TYPE_RENAMES:
        op.execute(f"UPDATE memories SET type = '{old}' WHERE type = '{new}'")

    # Delete any 'reasoning' type memories (new type, can't revert)
    op.execute("DELETE FROM memories WHERE type = 'reasoning'")

    # Recreate old constraint
    op.create_check_constraint(
        "valid_type",
        "memories",
        f"type IN {OLD_TYPES}",
    )
