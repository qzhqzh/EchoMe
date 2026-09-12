"""Opt-in PostgreSQL tests: isolated schemas in a dedicated disposable database."""

import os
import uuid
from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.database import get_session
from app.core.ratelimit import limiter
from app.main import app
from app.models import Base, User


@pytest_asyncio.fixture
async def database(monkeypatch, test_user_id_uuid):
    url = os.getenv("ECHOME_INTEGRATION_DATABASE_URL")
    if not url:
        pytest.skip("Set ECHOME_INTEGRATION_DATABASE_URL to a disposable echome_test database")
    if not (make_url(url).database or "").startswith("echome_test"):
        pytest.fail("Integration database name must start with echome_test")
    schema = "issue_" + uuid.uuid4().hex
    engine = create_async_engine(
        url,
        poolclass=NullPool,
        connect_args={"server_settings": {"search_path": f"{schema},public"}},
        execution_options={"schema_translate_map": {None: schema}},
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public")
            )
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            await connection.run_sync(Base.metadata.create_all)
        async with factory() as session:
            session.add(User(id=test_user_id_uuid, github_id=1, username="integration"))
            await session.commit()
        monkeypatch.setattr("app.core.database.async_session_factory", factory)
        monkeypatch.setattr("app.api.context_runtime.async_session_factory", factory)
        for path in (
            "app.api.memories.get_embedding",
            "app.services.memory_retrieval.get_embedding",
            "app.services.context_compiler.get_embedding",
        ):
            monkeypatch.setattr(path, AsyncMock(return_value=None))
        monkeypatch.setattr(limiter, "enabled", False)
        yield factory
    finally:
        async with engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await engine.dispose()


@pytest_asyncio.fixture
async def api(database, auth_headers):
    async def session_override():
        async with database() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_session] = session_override
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://integration/api/v1/",
            headers=auth_headers,
        ) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)
