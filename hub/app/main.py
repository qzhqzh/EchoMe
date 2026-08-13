"""EchoMe Hub - FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api import (
    admin,
    auth,
    context_outcomes,
    context_runtime,
    feedback,
    health,
    market,
    memories,
    memory_sleep,
    observability,
    project_knowledge,
    projects,
    retrieval_debug,
    review,
    sync,
)
from app.core.config import settings, validate_settings
from app.core.ratelimit import limiter

# Configure logging
logging.basicConfig(
    level=logging.INFO if not settings.debug else logging.DEBUG,
    format="%(levelname)s:%(name)s:%(message)s",
)


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

# Rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS: configurable via ECHOME_CORS_ORIGINS env var
_cors_origins = (
    ["*"]
    if settings.cors_origins == "*"
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
app.include_router(context_runtime.router, prefix="/api/v1")
app.include_router(context_outcomes.router, prefix="/api/v1")
app.include_router(memories.router, prefix="/api/v1")
app.include_router(memory_sleep.router, prefix="/api/v1")
app.include_router(feedback.router, prefix="/api/v1")
app.include_router(observability.router, prefix="/api/v1")
app.include_router(retrieval_debug.router, prefix="/api/v1")
app.include_router(projects.router, prefix="/api/v1")
app.include_router(project_knowledge.router, prefix="/api/v1")
app.include_router(sync.router, prefix="/api/v1")
app.include_router(review.router, prefix="/api/v1")
app.include_router(market.router, prefix="/api/v1")
app.include_router(admin.router, prefix="/api/v1")
