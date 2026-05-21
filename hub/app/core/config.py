"""Application configuration via environment variables."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Hub application settings."""

    # App
    app_name: str = "EchoMe Hub"
    app_version: str = "0.1.0"
    debug: bool = False
    port: int = 20000

    # Auth - legacy single-tenant bearer token (kept for backward compatibility)
    auth_token: str = "changeme"

    # GitHub OAuth
    github_client_id: str = ""
    github_client_secret: str = ""

    # JWT
    jwt_secret: str = "changeme-jwt-secret-at-least-32-chars"
    jwt_expire_days: int = 7

    # Database (default points to docker-compose service name)
    database_url: str = "postgresql+asyncpg://echome:echome@postgres:5432/echome"

    # Redis
    redis_url: str = "redis://redis:6379/0"

    # Embedding service
    embedding_url: str = "http://embedding:20002"
    embedding_dimensions: int = 1024  # BGE-M3 default dimension

    # Limits
    l0_max_tokens: int = 1500
    l0_max_count: int = 20
    l1_max_tokens: int = 2000
    l1_max_count: int = 30

    model_config = {"env_prefix": "ECHOME_", "env_file": ".env"}


settings = Settings()
