"""EchoMe Hub - FastAPI application entry point."""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import admin, auth, health, market, memories, projects, review, sync
from app.core.config import settings, validate_settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: startup and shutdown."""
    # Startup: validate critical config
    validate_settings()
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

# CORS: configurable via ECHOME_CORS_ORIGINS env var
_cors_origins = (
    ["*"] if settings.cors_origins == "*"
    else [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
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
app.include_router(market.router, prefix="/api/v1")
app.include_router(admin.router, prefix="/api/v1")
