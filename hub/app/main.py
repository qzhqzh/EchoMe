"""EchoMe Hub - FastAPI application entry point."""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, health, memories, projects, review, sync
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

# CORS: allow web frontend to access the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Single-tenant, allow all origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(health.router)
app.include_router(auth.router, prefix="/api/v1")
app.include_router(memories.router, prefix="/api/v1")
app.include_router(projects.router, prefix="/api/v1")
app.include_router(sync.router, prefix="/api/v1")
app.include_router(review.router, prefix="/api/v1")
