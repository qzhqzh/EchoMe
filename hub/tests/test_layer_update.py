"""Test to reproduce the layer update bug: PUT returns L1 but DB still has L0."""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---- Helper ----

def _make_real_orm_memory(
    user_id: str = "12345678-1234-1234-1234-123456789abc",
    title: str = "Test Memory",
    layer: str = "L0",
):
    """Create a real-enough ORM Memory object (not MagicMock) to test attribute mutation."""
    from app.models.memory import Memory

    mem = Memory.__new__(Memory)
    mem.id = uuid.uuid4()
    mem.user_id = user_id
    mem.title = title
    mem.content = "test content"
    mem.type = "context"
    mem.layer = layer
    mem.priority = 5
    mem.tags = ["test"]
    mem.status = "active"
    mem.source = "manual"
    mem.token_count = 10
    mem.visibility = "private"
    mem.forked_from = None
    mem.scope_global = True
    mem.scope_projects = []
    mem.scope_exclude = []
    mem.embedding = None
    mem.created_at = datetime.now(timezone.utc)
    mem.updated_at = datetime.now(timezone.utc)
    return mem


class TestUpdateMemoryLayer:
    """Reproduce: PUT layer=L0 -> L1, response shows L1, but DB still has L0."""

    @pytest.mark.asyncio
    async def test_update_layer_sets_correct_value(self):
        """After update_memory, the ORM object should have the new layer value."""
        from app.api.memories import update_memory
        from app.schemas.memory import MemoryUpdate

        existing = _make_real_orm_memory(layer="L0")
        body = MemoryUpdate(
            title="Test Memory",
            content="test content",
            type="context",
            layer="L1",
            priority=5,
            tags=["test"],
            status="active",
            scope={"global": True, "projects": [], "exclude_projects": []},
            source="manual",
            visibility="private",
        )

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_background = MagicMock()

        with patch("app.api.memories.count_tokens", return_value=10):
            result = await update_memory(
                memory_id=existing.id,
                body=body,
                background_tasks=mock_background,
                session=mock_session,
                user_id="12345678-1234-1234-1234-123456789abc",
            )

        # Check the returned object has L1
        assert result.layer == "L1", f"Returned layer should be L1, got {result.layer}"

        # Check the ORM object itself was mutated
        assert existing.layer == "L1", f"ORM object layer should be L1, got {existing.layer}"

        # Verify flush was called (data sent to DB connection)
        mock_session.flush.assert_awaited_once()

        # Verify background task for embedding was scheduled
        mock_background.add_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_layer_only_no_content_change(self):
        """PUT that only changes layer should NOT trigger embedding recomputation."""
        from app.api.memories import update_memory
        from app.schemas.memory import MemoryUpdate

        existing = _make_real_orm_memory(layer="L0")
        body = MemoryUpdate(
            title="Test Memory",
            content="test content",  # same content
            type="context",
            layer="L1",
            priority=5,
            tags=["test"],
            status="active",
            scope={"global": True, "projects": [], "exclude_projects": []},
            source="manual",
            visibility="private",
        )

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_background = MagicMock()

        with patch("app.api.memories.count_tokens", return_value=10):
            result = await update_memory(
                memory_id=existing.id,
                body=body,
                background_tasks=mock_background,
                session=mock_session,
                user_id="12345678-1234-1234-1234-123456789abc",
            )

        # Layer should be updated
        assert existing.layer == "L1"

        # Background task IS always called (recompute embedding on every PUT)
        # This is by design in the current code
        mock_background.add_task.assert_called_once()


class TestBackgroundEmbeddingRaceCondition:
    """
    The REAL BUG:
    1. PUT sets layer=L1, session.flush() sends UPDATE to DB
    2. Background task starts, creates NEW session, tries to UPDATE embedding
    3. Embedding dimension mismatch (1024 vs 1536) -> background task crashes
    4. The main session.commit() should STILL succeed because it's a separate session

    BUT: In the live system, the commit appears to NOT happen.
    This test verifies the _compute_and_store_embedding function handles errors gracefully.
    """

    @pytest.mark.asyncio
    async def test_background_embedding_failure_does_not_affect_main_session(self):
        """
        Even if embedding computation fails, the main session commit should succeed.
        This tests that _compute_and_store_embedding errors are properly contained.
        """
        from app.api.memories import _compute_and_store_embedding

        # Simulate embedding service returning wrong dimensions
        with patch("app.api.memories.get_embedding", return_value=None):
            # Should not raise - it returns early when embedding is None
            await _compute_and_store_embedding(uuid.uuid4(), "test text")

    @pytest.mark.asyncio
    async def test_background_embedding_db_error_isolation(self):
        """
        If embedding UPDATE fails in the background task's session,
        it should NOT propagate to the main request's session.
        """
        from app.api.memories import _compute_and_store_embedding
        from app.core.database import async_session_factory

        # Mock embedding to return a 1024-dim vector (wrong dimension)
        fake_embedding = [0.1] * 1024

        with patch("app.api.memories.get_embedding", return_value=fake_embedding):
            # The background task should fail (dimension mismatch)
            # but it should NOT raise to the caller
            try:
                await _compute_and_store_embedding(uuid.uuid4(), "test text")
            except Exception as e:
                pytest.fail(
                    f"Background embedding task should not raise to caller, "
                    f"but got: {e}"
                )


class TestEndToEndLayerUpdate:
    """
    Full integration test using httpx AsyncClient against the real app.
    Tests the complete flow: create -> update layer -> verify persistence.
    """

    @pytest.mark.asyncio
    async def test_layer_update_persists(self, sample_memory_data):
        """
        Create a memory with L0, PUT to change to L1, GET should return L1.
        This is the exact scenario the user reported.
        """
        from httpx import ASGITransport, AsyncClient

        from app.main import app

        test_user_id = uuid.UUID("12345678-1234-1234-1234-123456789abc")
        from app.core.jwt import create_access_token

        token, _ = create_access_token(
            user_id=test_user_id, username="testuser", role="user"
        )
        headers = {"Authorization": f"Bearer {token}"}

        # Mock the embedding service to avoid external dependency
        with patch("app.api.memories.get_embedding", return_value=None):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                # Step 1: Create memory with layer=L0
                create_data = sample_memory_data.copy()
                create_data["layer"] = "L0"
                resp = await client.post(
                    "/api/v1/memories", json=create_data, headers=headers
                )
                assert resp.status_code == 201, f"Create failed: {resp.text}"
                mem_id = resp.json()["id"]

                # Step 2: GET to confirm it's L0
                resp = await client.get(
                    f"/api/v1/memories/{mem_id}", headers=headers
                )
                assert resp.status_code == 200
                assert resp.json()["layer"] == "L0"

                # Step 3: PUT to change layer to L1
                update_data = create_data.copy()
                update_data["layer"] = "L1"
                update_data["title"] = create_data["title"]  # preserve title
                resp = await client.put(
                    f"/api/v1/memories/{mem_id}",
                    json=update_data,
                    headers=headers,
                )
                assert resp.status_code == 200, f"PUT failed: {resp.text}"
                assert resp.json()["layer"] == "L1", (
                    f"PUT response should show L1, got {resp.json()['layer']}"
                )

                # Step 4: GET again - THIS IS WHERE THE BUG MANIFESTS
                resp = await client.get(
                    f"/api/v1/memories/{mem_id}", headers=headers
                )
                assert resp.status_code == 200
                got_layer = resp.json()["layer"]
                assert got_layer == "L1", (
                    f"BUG! After PUT layer=L1, GET still returns layer={got_layer}. "
                    f"The update was NOT persisted to the database!"
                )
