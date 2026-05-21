"""Embedding service client — calls the local BGE-M3 embedding container."""

import logging

import httpx

from app.core.config import settings

logger = logging.getLogger("embedding_client")


async def get_embeddings(texts: list[str]) -> list[list[float]] | None:
    """Get embeddings for a list of texts from the embedding service.

    Returns None if the service is unavailable (graceful degradation).
    """
    if not texts:
        return None

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
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
