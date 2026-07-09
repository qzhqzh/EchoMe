"""Tests for memory feedback helpers."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException


class TestMemoryFeedback:
    """Tests for memory feedback API helpers."""

    @pytest.mark.asyncio
    async def test_feedback_summary_counts_ratings(self, test_user_id: str):
        """Feedback summary aggregates counts and last feedback time."""
        from app.api.feedback import _feedback_summary

        memory_id = uuid.uuid4()
        mock_session = AsyncMock()
        result = MagicMock()
        result.all.return_value = [
            ("helpful", 2, None),
            ("outdated", 1, None),
        ]
        mock_session.execute = AsyncMock(return_value=result)

        summary = await _feedback_summary(mock_session, memory_id, test_user_id)

        assert summary.memory_id == memory_id
        assert summary.total == 3
        assert summary.ratings == {"helpful": 2, "outdated": 1}

    @pytest.mark.asyncio
    async def test_ensure_memory_raises_404(self, test_user_id: str):
        """Feedback cannot be recorded for a missing memory."""
        from app.api.feedback import _ensure_memory

        mock_session = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=result)

        with pytest.raises(HTTPException) as exc_info:
            await _ensure_memory(mock_session, uuid.uuid4(), test_user_id)

        assert exc_info.value.status_code == 404
