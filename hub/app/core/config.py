"""Application configuration via environment variables."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Hub application settings."""

    # App
    app_name: str = "EchoMe Hub"
    app_version: str = "0.1.0"
    debug: bool = False

    # Auth
    auth_token: str = "changeme"  # Single-tenant bearer token

    # Database
    database_url: str = "postgresql+asyncpg://echome:echome@localhost:5432/echome"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Embedding
    openai_api_key: str = ""
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536

    # Limits
    l0_max_tokens: int = 1500
    l0_max_count: int = 20
    l1_max_tokens: int = 2000
    l1_max_count: int = 30

    model_config = {"env_prefix": "ECHOME_", "env_file": ".env"}


settings = Settings()
