"""Shared exclusion semantics for project-aware memory readers."""

from collections.abc import Iterable

from sqlalchemy import ColumnElement, and_, true

from app.models.memory import Memory


def exclude_projects(scope_ids: Iterable[str]) -> ColumnElement[bool]:
    """Exclusions override global/include scopes, including canonical aliases."""
    return and_(
        true(), *(~Memory.scope_exclude.contains([value]) for value in sorted(set(scope_ids)))
    )
