"""Embedding service client — calls the local BGE-M3 embedding container."""

import logging

import httpx

from app.core.config import settings
from app.services.content_safety import find_sensitive_content

logger = logging.getLogger("embedding_client")


async def get_embeddings(
    texts: list[str], *, timeout_seconds: float = 30.0
) -> list[list[float]] | None:
    """Get embeddings for a list of texts from the embedding service.

    Returns None if the service is unavailable (graceful degradation).
    """
    if not texts:
        return None
    blocked = sum(bool(find_sensitive_content(text)) for text in texts)
    if blocked:
        logger.warning(
            "Embedding request blocked by content safety for %d document(s)", blocked
        )
        return None

    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            resp = await client.post(
                f"{settings.embedding_url}/embed",
                json={"texts": texts},
            )
            resp.raise_for_status()
            data = resp.json()
            return data["embeddings"]
    except Exception as e:
        logger.warning(f"Embedding service unavailable: {e}")
        return None


async def get_embedding(text: str) -> list[float] | None:
    """Get embedding for a single text. Returns None on failure."""
    results = await get_embeddings([text])
    if results and len(results) > 0:
        return results[0]
    return None
