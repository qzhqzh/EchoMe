"""Project CRUD and canonical identity API routes."""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import verify_token
from app.core.database import get_session
from app.models.memory import Project
from app.models.project_knowledge import (
    ArtifactChunk,
    AutomationProposalRun,
    ConstraintRevalidationProposal,
    ContextQualitySnapshot,
    ContextRun,
    KnowledgeView,
    ProjectAlias,
    ProjectArtifact,
    ProjectConstraint,
    ProjectEvent,
)
from app.services.project_identity import normalize_project_hint, resolve_project

router = APIRouter(prefix="/projects", tags=["projects"])


# --- Schemas ---


class ProjectCreate(BaseModel):
    id: str = Field(..., max_length=128)
    name: str = Field(..., max_length=256)
    description: str | None = None
    git_remote: str | None = None
    path_patterns: list[str] = Field(default_factory=list)


class ProjectResponse(BaseModel):
    id: str
    name: str
    description: str | None
    git_remote: str | None
    path_patterns: list[str]

    model_config = {"from_attributes": True}


class ProjectResolveRequest(BaseModel):
    hint: str = Field(..., min_length=1, max_length=2048)
    alias_type: Literal["legacy_id", "name", "git_remote", "path", "client_hint"] | None = None


class ProjectAliasCreate(BaseModel):
    canonical_project_id: str = Field(..., min_length=1, max_length=128)
    alias_type: Literal["legacy_id", "name", "git_remote", "path", "client_hint"]
    alias_value: str = Field(..., min_length=1, max_length=2048)
    status: Literal["proposed"] = "proposed"
    source: Literal["manual", "ai", "imported", "bootstrap"] = "ai"
    confidence: float = Field(0.7, ge=0, le=1)


class ProjectAliasPatch(BaseModel):
    status: Literal["proposed", "active", "rejected", "archived"]


def _alias_payload(alias: ProjectAlias) -> dict[str, object]:
    return {
        "id": str(alias.id),
        "canonical_project_id": alias.canonical_project_id,
        "alias_type": alias.alias_type,
        "alias_value": alias.alias_value,
        "normalized_value": alias.normalized_value,
        "status": alias.status,
        "source": alias.source,
        "confidence": alias.confidence,
        "created_at": alias.created_at.isoformat(),
        "updated_at": alias.updated_at.isoformat(),
    }


# --- Routes ---


@router.get("", response_model=list[ProjectResponse])
async def list_projects(
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> list[Project]:
    """List all projects."""
    result = await session.execute(select(Project).where(Project.user_id == user_id))
    return list(result.scalars().all())


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    body: ProjectCreate,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> Project:
    """Create a new project."""
    # Check if exists
    existing = await session.get(Project, body.id)
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Project already exists")

    project = Project(
        id=body.id,
        user_id=user_id,
        name=body.name,
        description=body.description,
        git_remote=body.git_remote,
        path_patterns=body.path_patterns,
    )
    session.add(project)
    await session.flush()
    return project


@router.post("/resolve")
async def resolve_project_hint(
    body: ProjectResolveRequest,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> dict[str, object]:
    """Resolve one explicit client hint without modifying project history."""
    resolution = await resolve_project(session, user_id, body.hint, body.alias_type)
    return {
        "project": ProjectResponse.model_validate(resolution.project).model_dump(),
        "resolution": resolution.payload(body.hint),
    }


@router.get("/aliases")
async def list_project_aliases(
    project_id: str,
    include_inactive: bool = False,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> dict[str, object]:
    """List alias proposals and active mappings for one canonical project."""
    project = (await resolve_project(session, user_id, project_id)).project
    query = select(ProjectAlias).where(
        ProjectAlias.user_id == user_id,
        ProjectAlias.canonical_project_id == project.id,
    )
    if not include_inactive:
        query = query.where(ProjectAlias.status.in_(["proposed", "active"]))
    result = await session.execute(query.order_by(ProjectAlias.created_at))
    aliases = list(result.scalars().all())
    return {"canonical_project_id": project.id, "items": [_alias_payload(item) for item in aliases]}


@router.post("/aliases", status_code=status.HTTP_201_CREATED)
async def create_project_alias(
    body: ProjectAliasCreate,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> dict[str, object]:
    """Create an auditable alias proposal for later explicit review."""
    project = (await resolve_project(session, user_id, body.canonical_project_id)).project
    try:
        normalized = normalize_project_hint(body.alias_value, body.alias_type)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    existing = await session.scalar(
        select(ProjectAlias).where(
            ProjectAlias.user_id == user_id,
            ProjectAlias.alias_type == body.alias_type,
            ProjectAlias.normalized_value == normalized,
        )
    )
    if existing is not None:
        if existing.canonical_project_id != project.id:
            raise HTTPException(
                status_code=409,
                detail="Project alias is already assigned to another canonical project",
            )
        raise HTTPException(status_code=409, detail="Project alias already exists")
    alias = ProjectAlias(
        user_id=user_id,
        canonical_project_id=project.id,
        alias_type=body.alias_type,
        alias_value=body.alias_value.strip(),
        normalized_value=normalized,
        status=body.status,
        source=body.source,
        confidence=body.confidence,
    )
    session.add(alias)
    await session.flush()
    return _alias_payload(alias)


@router.patch("/aliases/{alias_id}")
async def update_project_alias(
    alias_id: uuid.UUID,
    body: ProjectAliasPatch,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> dict[str, object]:
    """Review an alias without changing the historical alias value."""
    alias = await session.scalar(
        select(ProjectAlias).where(ProjectAlias.id == alias_id, ProjectAlias.user_id == user_id)
    )
    if alias is None:
        raise HTTPException(status_code=404, detail="Project alias not found")
    alias.status = body.status
    await session.flush()
    return _alias_payload(alias)


@router.get("/{project_id:path}", response_model=ProjectResponse)
async def get_project(
    project_id: str,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> Project:
    """Get a canonical project by ID or active alias."""
    return (await resolve_project(session, user_id, project_id)).project


@router.put("/{project_id:path}", response_model=ProjectResponse)
async def update_project(
    project_id: str,
    body: ProjectCreate,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> Project:
    """Update a canonical project addressed by ID or active alias."""
    project = (await resolve_project(session, user_id, project_id)).project

    project.name = body.name
    project.description = body.description
    project.git_remote = body.git_remote
    project.path_patterns = body.path_patterns
    return project


@router.delete("/{project_id:path}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: str,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> None:
    """Delete an empty canonical project addressed by ID or active alias."""
    project = (await resolve_project(session, user_id, project_id)).project
    project_id = project.id
    knowledge_models = (
        ProjectArtifact,
        ProjectConstraint,
        ArtifactChunk,
        ContextRun,
        KnowledgeView,
        ConstraintRevalidationProposal,
        ProjectEvent,
        ContextQualitySnapshot,
        AutomationProposalRun,
        ProjectAlias,
    )
    for model in knowledge_models:
        if model is ProjectAlias:
            history_filter = model.canonical_project_id == project_id
        else:
            history_filter = model.project_id == project_id
        knowledge_exists = await session.scalar(
            select(model.id).where(model.user_id == user_id, history_filter).limit(1)
        )
        if knowledge_exists:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Project has Project Knowledge history and cannot be deleted",
            )
    await session.delete(project)
