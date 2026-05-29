"""Unit tests for hub memories CRUD API endpoints."""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.models.memory import Memory


def _make_memory(
    user_id: str = "12345678-1234-1234-1234-123456789abc",
    title: str = "Test Memory",
    content: str = "Test content",
    mem_type: str = "context",
    layer: str = "L2",
    priority: int = 5,
    tags: list | None = None,
    status: str = "active",
    visibility: str = "private",
) -> MagicMock:
    """Create a mock Memory ORM object."""
    mem = MagicMock(spec=Memory)
    mem.id = uuid.uuid4()
    mem.user_id = user_id
    mem.title = title
    mem.content = content
    mem.type = mem_type
    mem.layer = layer
    mem.priority = priority
    mem.tags = tags or ["test"]
    mem.status = status
    mem.source = "manual"
    mem.token_count = 10
    mem.visibility = visibility
    mem.forked_from = None
    mem.scope_global = True
    mem.scope_projects = []
    mem.scope_exclude = []
    mem.embedding = None
    mem.created_at = datetime.now(timezone.utc)
    mem.updated_at = datetime.now(timezone.utc)
    return mem


class TestListMemories:
    """Tests for GET /api/v1/memories."""

    @pytest.mark.asyncio
    async def test_list_memories_empty(self, test_user_id: str):
        """Returns empty list when user has no memories."""
        from app.api.memories import list_memories

        mock_session = AsyncMock()
        # Total count query
        count_result = MagicMock()
        count_result.scalar_one.return_value = 0
        # Items query
        items_result = MagicMock()
        items_result.scalars.return_value = MagicMock(all=MagicMock(return_value=[]))

        mock_session.execute = AsyncMock(side_effect=[count_result, items_result])

        result = await list_memories(
            type=None,
            layer=None,
            status_filter=None,
            tags=None,
            project_id=None,
            offset=0,
            limit=50,
            session=mock_session,
            user_id=test_user_id,
        )

        assert result.total == 0
        assert result.items == []
        assert result.offset == 0
        assert result.limit == 50

    @pytest.mark.asyncio
    async def test_list_memories_with_results(self, test_user_id: str):
        """Returns memories when they exist."""
        from app.api.memories import list_memories

        mock_memories = [
            _make_memory(user_id=test_user_id, title="Memory 1"),
            _make_memory(user_id=test_user_id, title="Memory 2"),
        ]

        mock_session = AsyncMock()
        count_result = MagicMock()
        count_result.scalar_one.return_value = 2
        items_result = MagicMock()
        items_result.scalars.return_value = MagicMock(all=MagicMock(return_value=mock_memories))

        mock_session.execute = AsyncMock(side_effect=[count_result, items_result])

        result = await list_memories(
            type=None,
            layer=None,
            status_filter=None,
            tags=None,
            project_id=None,
            offset=0,
            limit=50,
            session=mock_session,
            user_id=test_user_id,
        )

        assert result.total == 2
        assert len(result.items) == 2

    @pytest.mark.asyncio
    async def test_list_memories_with_type_filter(self, test_user_id: str):
        """Filtering by type should pass the filter through."""
        from app.api.memories import list_memories

        mock_session = AsyncMock()
        count_result = MagicMock()
        count_result.scalar_one.return_value = 1
        items_result = MagicMock()
        mem = _make_memory(user_id=test_user_id, mem_type="method")
        items_result.scalars.return_value = MagicMock(all=MagicMock(return_value=[mem]))

        mock_session.execute = AsyncMock(side_effect=[count_result, items_result])

        result = await list_memories(
            type="method",
            layer=None,
            status_filter=None,
            tags=None,
            project_id=None,
            offset=0,
            limit=50,
            session=mock_session,
            user_id=test_user_id,
        )

        assert result.total == 1


class TestGetMemory:
    """Tests for GET /api/v1/memories/{memory_id}."""

    @pytest.mark.asyncio
    async def test_get_memory_found(self, test_user_id: str):
        """Returns memory when it exists and belongs to user."""
        from app.api.memories import get_memory

        mock_mem = _make_memory(user_id=test_user_id, title="Found Memory")
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_mem
        mock_session.execute = AsyncMock(return_value=mock_result)

        result = await get_memory(
            memory_id=mock_mem.id,
            session=mock_session,
            user_id=test_user_id,
        )

        assert result.title == "Found Memory"

    @pytest.mark.asyncio
    async def test_get_memory_not_found_raises_404(self, test_user_id: str):
        """Raises 404 when memory doesn't exist."""
        from app.api.memories import get_memory

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(HTTPException) as exc_info:
            await get_memory(
                memory_id=uuid.uuid4(),
                session=mock_session,
                user_id=test_user_id,
            )

        assert exc_info.value.status_code == 404
        assert "not found" in exc_info.value.detail.lower()


class TestCreateMemory:
    """Tests for POST /api/v1/memories."""

    @pytest.mark.asyncio
    async def test_create_memory_success(self, test_user_id: str, sample_memory_data: dict):
        """Successfully creates a memory and returns it."""
        from starlette.requests import Request

        from app.api.memories import create_memory
        from app.schemas.memory import MemoryCreate

        body = MemoryCreate(**sample_memory_data)
        mock_session = AsyncMock()
        mock_request = MagicMock(spec=Request)
        mock_background = MagicMock()

        # The function calls session.add() and session.flush()
        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock()
        mock_session.commit = AsyncMock()

        with patch("app.api.memories.count_tokens", return_value=15):
            await create_memory(
                request=mock_request,
                body=body,
                background_tasks=mock_background,
                session=mock_session,
                user_id=test_user_id,
            )

        # Verify the memory was added to session
        mock_session.add.assert_called_once()
        created_mem = mock_session.add.call_args[0][0]
        assert created_mem.title == "Test Memory"
        assert created_mem.user_id == test_user_id
        assert created_mem.type == "context"
        assert created_mem.layer == "L2"
        assert created_mem.token_count == 15

    @pytest.mark.asyncio
    async def test_create_memory_triggers_embedding(self, test_user_id: str, sample_memory_data: dict):
        """Creating a memory should schedule background embedding computation."""
        from starlette.requests import Request

        from app.api.memories import create_memory
        from app.schemas.memory import MemoryCreate

        body = MemoryCreate(**sample_memory_data)
        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_request = MagicMock(spec=Request)
        mock_background = MagicMock()

        with patch("app.api.memories.count_tokens", return_value=10):
            await create_memory(
                request=mock_request,
                body=body,
                background_tasks=mock_background,
                session=mock_session,
                user_id=test_user_id,
            )

        # Background task should be scheduled for embedding
        mock_background.add_task.assert_called_once()


class TestUpdateMemory:
    """Tests for PUT /api/v1/memories/{memory_id}."""

    @pytest.mark.asyncio
    async def test_update_memory_success(self, test_user_id: str, sample_memory_update_data: dict):
        """Successfully updates all fields of a memory."""
        from app.api.memories import update_memory
        from app.schemas.memory import MemoryUpdate

        body = MemoryUpdate(**sample_memory_update_data)

        existing_mem = _make_memory(user_id=test_user_id)
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_mem
        mock_session.execute = AsyncMock(return_value=mock_result)

        mock_background = MagicMock()

        with patch("app.api.memories.count_tokens", return_value=20):
            result = await update_memory(
                memory_id=existing_mem.id,
                body=body,
                background_tasks=mock_background,
                session=mock_session,
                user_id=test_user_id,
            )

        assert result.title == "Updated Memory"
        assert result.content == "This memory has been updated."
        assert result.type == "method"
        assert result.layer == "L1"
        assert result.priority == 8

    @pytest.mark.asyncio
    async def test_update_commits_before_scheduling_embedding(self, test_user_id: str, sample_memory_update_data: dict):
        """PUT should release the row lock before the embedding task can update it."""
        from app.api.memories import update_memory
        from app.schemas.memory import MemoryUpdate

        body = MemoryUpdate(**sample_memory_update_data)
        existing_mem = _make_memory(user_id=test_user_id)
        events = []

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_mem
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.flush = AsyncMock()

        async def mark_commit():
            events.append("commit")

        mock_session.commit = AsyncMock(side_effect=mark_commit)

        mock_background = MagicMock()
        mock_background.add_task = MagicMock(side_effect=lambda *args: events.append("add_task"))

        with patch("app.api.memories.count_tokens", return_value=20):
            await update_memory(
                memory_id=existing_mem.id,
                body=body,
                background_tasks=mock_background,
                session=mock_session,
                user_id=test_user_id,
            )

        assert events == ["commit", "add_task"]

    @pytest.mark.asyncio
    async def test_update_memory_not_found(self, test_user_id: str, sample_memory_update_data: dict):
        """Raises 404 when memory doesn't exist."""
        from app.api.memories import update_memory
        from app.schemas.memory import MemoryUpdate

        body = MemoryUpdate(**sample_memory_update_data)

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        mock_background = MagicMock()

        with pytest.raises(HTTPException) as exc_info:
            await update_memory(
                memory_id=uuid.uuid4(),
                body=body,
                background_tasks=mock_background,
                session=mock_session,
                user_id=test_user_id,
            )

        assert exc_info.value.status_code == 404


class TestPatchMemory:
    """Tests for PATCH /api/v1/memories/{memory_id}."""

    @pytest.mark.asyncio
    async def test_patch_memory_partial_update(self, test_user_id: str):
        """Partial update should only modify specified fields."""
        from app.api.memories import patch_memory
        from app.schemas.memory import MemoryPatch

        body = MemoryPatch(title="Patched Title", priority=9)

        existing_mem = _make_memory(user_id=test_user_id, title="Original")
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_mem
        mock_session.execute = AsyncMock(return_value=mock_result)

        mock_background = MagicMock()

        result = await patch_memory(
            memory_id=existing_mem.id,
            body=body,
            background_tasks=mock_background,
            session=mock_session,
            user_id=test_user_id,
        )

        assert result.title == "Patched Title"
        assert result.priority == 9
        # Other fields unchanged
        assert result.content == "Test content"

    @pytest.mark.asyncio
    async def test_patch_memory_not_found(self, test_user_id: str):
        """Raises 404 when memory doesn't exist."""
        from app.api.memories import patch_memory
        from app.schemas.memory import MemoryPatch

        body = MemoryPatch(title="New Title")

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        mock_background = MagicMock()

        with pytest.raises(HTTPException) as exc_info:
            await patch_memory(
                memory_id=uuid.uuid4(),
                body=body,
                background_tasks=mock_background,
                session=mock_session,
                user_id=test_user_id,
            )

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_patch_content_recomputes_tokens(self, test_user_id: str):
        """Patching content should recompute token count."""
        from app.api.memories import patch_memory
        from app.schemas.memory import MemoryPatch

        body = MemoryPatch(content="New long content for testing token count")

        existing_mem = _make_memory(user_id=test_user_id)
        existing_mem.token_count = 5
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_mem
        mock_session.execute = AsyncMock(return_value=mock_result)

        mock_background = MagicMock()

        with patch("app.api.memories.count_tokens", return_value=25):
            result = await patch_memory(
                memory_id=existing_mem.id,
                body=body,
                background_tasks=mock_background,
                session=mock_session,
                user_id=test_user_id,
            )

        assert result.token_count == 25


class TestDeleteMemory:
    """Tests for DELETE /api/v1/memories/{memory_id}."""

    @pytest.mark.asyncio
    async def test_soft_delete_archives_memory(self, test_user_id: str):
        """Soft delete should set status to 'archived'."""
        from app.api.memories import delete_memory

        existing_mem = _make_memory(user_id=test_user_id)
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_mem
        mock_session.execute = AsyncMock(return_value=mock_result)

        await delete_memory(
            memory_id=existing_mem.id,
            hard=False,
            session=mock_session,
            user_id=test_user_id,
        )

        assert existing_mem.status == "archived"

    @pytest.mark.asyncio
    async def test_hard_delete_removes_memory(self, test_user_id: str):
        """Hard delete should call session.delete()."""
        from app.api.memories import delete_memory

        existing_mem = _make_memory(user_id=test_user_id)
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_mem
        mock_session.execute = AsyncMock(return_value=mock_result)

        await delete_memory(
            memory_id=existing_mem.id,
            hard=True,
            session=mock_session,
            user_id=test_user_id,
        )

        mock_session.delete.assert_called_once_with(existing_mem)

    @pytest.mark.asyncio
    async def test_delete_memory_not_found(self, test_user_id: str):
        """Raises 404 when memory doesn't exist."""
        from app.api.memories import delete_memory

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(HTTPException) as exc_info:
            await delete_memory(
                memory_id=uuid.uuid4(),
                hard=False,
                session=mock_session,
                user_id=test_user_id,
            )

        assert exc_info.value.status_code == 404


class TestSearchMemories:
    """Tests for POST /api/v1/memories/search."""

    @pytest.mark.asyncio
    async def test_search_keyword_match(self, test_user_id: str):
        """Keyword search should return matching memories."""
        from starlette.requests import Request

        from app.api.memories import search_memories
        from app.schemas.memory import MemorySearchRequest

        body = MemorySearchRequest(query="python testing", top_k=5)

        # Create mocks for memory objects with proper attributes
        mem1 = _make_memory(
            user_id=test_user_id,
            title="Python Testing Guide",
            content="Use pytest for all tests",
            tags=["python", "testing"],
        )

        mock_session = AsyncMock()
        # Only keyword query is executed when get_embedding returns None
        keyword_result = MagicMock()
        keyword_result.scalars.return_value = MagicMock(all=MagicMock(return_value=[mem1]))

        mock_session.execute = AsyncMock(return_value=keyword_result)
        mock_request = MagicMock(spec=Request)

        with patch("app.api.memories.get_embedding", return_value=None):
            result = await search_memories(
                request=mock_request,
                body=body,
                session=mock_session,
                user_id=test_user_id,
            )

        assert result.total_searched == 1
        # Result should contain the matching memory (keyword "python" matches title)
        assert len(result.results) >= 1

    @pytest.mark.asyncio
    async def test_search_no_results(self, test_user_id: str):
        """Search with no matches should return empty results."""
        from starlette.requests import Request

        from app.api.memories import search_memories
        from app.schemas.memory import MemorySearchRequest

        body = MemorySearchRequest(query="zzzznonexistent", top_k=5)

        mock_session = AsyncMock()
        vector_result = MagicMock()
        vector_result.__iter__ = MagicMock(return_value=iter([]))
        keyword_result = MagicMock()
        keyword_result.scalars.return_value = MagicMock(all=MagicMock(return_value=[]))

        mock_session.execute = AsyncMock(side_effect=[vector_result, keyword_result])
        mock_request = MagicMock(spec=Request)

        with patch("app.api.memories.get_embedding", return_value=None):
            result = await search_memories(
                request=mock_request,
                body=body,
                session=mock_session,
                user_id=test_user_id,
            )

        assert result.total_searched == 0
        assert result.results == []


class TestMemorySchemaValidation:
    """Test that Pydantic schemas correctly validate input."""

    def test_valid_memory_create(self, sample_memory_data: dict):
        """Valid data should pass validation."""
        from app.schemas.memory import MemoryCreate

        mem = MemoryCreate(**sample_memory_data)
        assert mem.title == "Test Memory"
        assert mem.type.value == "context"
        assert mem.layer.value == "L2"

    def test_invalid_type_rejected(self, sample_memory_data: dict):
        """Invalid memory type should be rejected."""
        from pydantic import ValidationError

        from app.schemas.memory import MemoryCreate

        sample_memory_data["type"] = "invalid_type"
        with pytest.raises(ValidationError):
            MemoryCreate(**sample_memory_data)

    def test_invalid_layer_rejected(self, sample_memory_data: dict):
        """Invalid layer should be rejected."""
        from pydantic import ValidationError

        from app.schemas.memory import MemoryCreate

        sample_memory_data["layer"] = "L9"
        with pytest.raises(ValidationError):
            MemoryCreate(**sample_memory_data)

    def test_priority_out_of_range_rejected(self, sample_memory_data: dict):
        """Priority outside 1-10 should be rejected."""
        from pydantic import ValidationError

        from app.schemas.memory import MemoryCreate

        sample_memory_data["priority"] = 11
        with pytest.raises(ValidationError):
            MemoryCreate(**sample_memory_data)

        sample_memory_data["priority"] = 0
        with pytest.raises(ValidationError):
            MemoryCreate(**sample_memory_data)

    def test_title_max_length(self, sample_memory_data: dict):
        """Title exceeding 256 chars should be rejected."""
        from pydantic import ValidationError

        from app.schemas.memory import MemoryCreate

        sample_memory_data["title"] = "x" * 257
        with pytest.raises(ValidationError):
            MemoryCreate(**sample_memory_data)

    def test_patch_allows_partial(self):
        """MemoryPatch should accept any subset of fields."""
        from app.schemas.memory import MemoryPatch

        # Just title
        patch = MemoryPatch(title="New Title")
        assert patch.title == "New Title"
        assert patch.content is None
        assert patch.type is None

        # Just priority
        patch = MemoryPatch(priority=8)
        assert patch.priority == 8
        assert patch.title is None

    def test_search_request_defaults(self):
        """Search request should have sensible defaults."""
        from app.schemas.memory import MemorySearchRequest

        req = MemorySearchRequest(query="test")
        assert req.top_k == 5
        assert req.min_score == 0.3
        assert req.type is None
        assert req.tags == []



class TestComputeAndStoreEmbedding:
    """Tests for the _compute_and_store_embedding background task."""

    @pytest.mark.asyncio
    async def test_embedding_task_uses_targeted_update(self):
        """Background embedding task should only update the embedding column,
        not load and re-commit the full ORM object (which would overwrite
        concurrent changes like layer updates).
        """
        from app.api.memories import _compute_and_store_embedding

        memory_id = uuid.uuid4()
        fake_embedding = [0.1] * 1024  # bge-m3 outputs 1024 dimensions

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.rowcount = 1
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.commit = AsyncMock()

        # Mock the context manager
        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("app.api.memories.get_embedding", return_value=fake_embedding),
            patch("app.core.database.async_session_factory", return_value=mock_session_ctx),
        ):
            await _compute_and_store_embedding(memory_id, "test text")

        # Verify session.execute was called (the UPDATE statement)
        mock_session.execute.assert_called_once()
        # Verify commit was called
        mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_embedding_task_noop_when_embedding_unavailable(self):
        """If embedding service returns None, no DB operation should happen."""
        from app.api.memories import _compute_and_store_embedding

        memory_id = uuid.uuid4()

        with (
            patch("app.api.memories.get_embedding", return_value=None),
            patch("app.core.database.async_session_factory") as mock_factory,
        ):
            await _compute_and_store_embedding(memory_id, "test text")

        # async_session_factory should never be called if embedding is None
        mock_factory.assert_not_called()

    @pytest.mark.asyncio
    async def test_embedding_task_swallows_exceptions(self):
        """Background task must NEVER raise — exceptions would rollback
        the main request's session commit (the root cause of the layer
        update bug).
        """
        from app.api.memories import _compute_and_store_embedding

        memory_id = uuid.uuid4()
        fake_embedding = [0.1] * 1024  # bge-m3 outputs 1024 dimensions

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=Exception("dimension mismatch"))
        mock_session.commit = AsyncMock()

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("app.api.memories.get_embedding", return_value=fake_embedding),
            patch("app.core.database.async_session_factory", return_value=mock_session_ctx),
        ):
            # This MUST NOT raise
            await _compute_and_store_embedding(memory_id, "test text")

        # If we get here without exception, the test passes


class TestUpdateMemoryLayerPersistence:
    """Tests verifying that layer changes via PUT/PATCH actually persist
    and are not overwritten by the background embedding task.
    """

    @pytest.mark.asyncio
    async def test_put_update_layer_persists(self, test_user_id: str, sample_memory_update_data: dict):
        """PUT should persist layer change and background task should not revert it."""
        from app.api.memories import update_memory
        from app.schemas.memory import MemoryUpdate

        # Start with L0
        existing_mem = _make_memory(user_id=test_user_id, layer="L0")

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_mem
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.flush = AsyncMock()

        mock_background = MagicMock()

        # Update to L1
        sample_memory_update_data["layer"] = "L1"
        body = MemoryUpdate(**sample_memory_update_data)

        with patch("app.api.memories.count_tokens", return_value=20):
            result = await update_memory(
                memory_id=existing_mem.id,
                body=body,
                background_tasks=mock_background,
                session=mock_session,
                user_id=test_user_id,
            )

        # Layer should be updated on the ORM object
        assert result.layer == "L1"

        # flush must have been called to persist before response
        mock_session.flush.assert_called_once()

        # Background task should be scheduled but won't affect layer
        mock_background.add_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_patch_update_layer_persists(self, test_user_id: str):
        """PATCH with just layer change should persist it."""
        from app.api.memories import patch_memory
        from app.schemas.memory import MemoryPatch

        # Start with L0
        existing_mem = _make_memory(user_id=test_user_id, layer="L0")

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_mem
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.flush = AsyncMock()

        mock_background = MagicMock()

        # PATCH to L1
        body = MemoryPatch(layer="L1")

        result = await patch_memory(
            memory_id=existing_mem.id,
            body=body,
            background_tasks=mock_background,
            session=mock_session,
            user_id=test_user_id,
        )

        # Layer should be updated
        assert result.layer == "L1"

        # flush must have been called
        mock_session.flush.assert_called_once()

        # Background task should NOT be triggered (no title/content change)
        mock_background.add_task.assert_not_called()
