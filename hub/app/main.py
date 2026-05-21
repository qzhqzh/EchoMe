"""EchoMe Hub - FastAPI application entry point."""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI

from app.api import health, memories, projects, review, sync
from app.core.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: startup and shutdown."""
    # Startup
    yield
    # Shutdown: close DB connections
    from app.core.database import engine

    await engine.dispose()


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Personal memory and context layer for AI CLI tools",
    lifespan=lifespan,
)

# Register routers
app.include_router(health.router)
app.include_router(memories.router, prefix="/api/v1")
app.include_router(projects.router, prefix="/api/v1")
app.include_router(sync.router, prefix="/api/v1")
app.include_router(review.router, prefix="/api/v1")
