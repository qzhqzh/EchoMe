"""Project CRUD API routes."""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import verify_token
from app.core.database import get_session
from app.models.memory import Project
from app.models.project_knowledge import ProjectArtifact, ProjectConstraint

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


@router.get("/{project_id:path}", response_model=ProjectResponse)
async def get_project(
    project_id: str,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> Project:
    """Get a project by ID."""
    result = await session.execute(
        select(Project).where(Project.id == project_id, Project.user_id == user_id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project


@router.put("/{project_id:path}", response_model=ProjectResponse)
async def update_project(
    project_id: str,
    body: ProjectCreate,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> Project:
    """Update a project."""
    result = await session.execute(
        select(Project).where(Project.id == project_id, Project.user_id == user_id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

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
    """Delete a project."""
    result = await session.execute(
        select(Project).where(Project.id == project_id, Project.user_id == user_id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    knowledge_exists = await session.scalar(
        select(ProjectArtifact.id)
        .where(ProjectArtifact.user_id == user_id, ProjectArtifact.project_id == project_id)
        .limit(1)
    ) or await session.scalar(
        select(ProjectConstraint.id)
        .where(ProjectConstraint.user_id == user_id, ProjectConstraint.project_id == project_id)
        .limit(1)
    )
    if knowledge_exists:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Project has indexed artifacts or constraints and cannot be deleted",
        )
    await session.delete(project)
