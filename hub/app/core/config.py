"""Application configuration via environment variables."""

import logging
import sys

from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)

_INSECURE_JWT_SECRET = "changeme-jwt-secret-at-least-32-chars"


class Settings(BaseSettings):
    """Hub application settings."""

    # App
    app_name: str = "EchoMe Hub"
    app_version: str = "1.5.0"
    debug: bool = False
    port: int = 20000

    # Emergency auth token (disabled by default, set in .env for GitHub-down scenarios)
    # When set, allows Bearer token login mapped to first admin user.
    auth_token: str = ""

    # GitHub OAuth
    github_client_id: str = ""
    github_client_secret: str = ""

    # JWT
    jwt_secret: str = _INSECURE_JWT_SECRET
    jwt_expire_days: int = 3650

    # CORS (comma-separated origins, or "*" for all)
    cors_origins: str = "*"

    # Database (default points to docker-compose service name)
    database_url: str = "postgresql+asyncpg://echome:echome@postgres:5432/echome"

    # Embedding service
    embedding_url: str = "http://embedding:20002"
    embedding_dimensions: int = 1024  # Must match bge-m3 model output

    # Project context compiler (can be disabled for a no-data-loss query rollback)
    context_compiler_enabled: bool = True
    # Proposal-only automation remains opt-in even after quality gates pass.
    project_automation_enabled: bool = False

    # Limits
    l0_max_tokens: int = 1500
    l0_max_count: int = 20
    l1_max_tokens: int = 2000
    l1_max_count: int = 30

    model_config = {"env_prefix": "ECHOME_", "env_file": ".env", "extra": "ignore"}


settings = Settings()


def validate_settings() -> None:
    """Validate critical settings on startup. Called from app lifespan."""
    if settings.jwt_secret == _INSECURE_JWT_SECRET:
        if settings.debug:
            logger.warning(
                "⚠️  Using default JWT secret! Set ECHOME_JWT_SECRET in .env for production."
            )
        else:
            logger.critical(
                "🚨 ECHOME_JWT_SECRET is using the insecure default value! "
                "Set a strong random secret in .env before running in production. "
                'Use: python -c "import secrets; print(secrets.token_urlsafe(32))"'
            )
            sys.exit(1)

    if settings.auth_token:
        logger.info(
            "ℹ️  Emergency auth token is enabled (ECHOME_AUTH_TOKEN). "
            "This bypasses OAuth — use only when GitHub is unreachable."
        )
