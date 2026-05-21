"""EchoMe Hub - FastAPI application entry point."""

from fastapi import FastAPI

from app.api import health, memories, projects, sync
from app.core.config import settings

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Personal memory and context layer for AI CLI tools",
)

# Register routers
app.include_router(health.router)
app.include_router(memories.router, prefix="/api/v1")
app.include_router(projects.router, prefix="/api/v1")
app.include_router(sync.router, prefix="/api/v1")
