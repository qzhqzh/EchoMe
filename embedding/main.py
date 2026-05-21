"""EchoMe Embedding Service - BGE-M3 vector embedding via HTTP API."""

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import numpy as np
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from sentence_transformers import SentenceTransformer

logger = logging.getLogger("embedding")

# Global model reference
model: SentenceTransformer | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Load model on startup."""
    global model
    logger.info("Loading BGE-M3 model... (this may take 30-60s on first run)")
    model = SentenceTransformer("BAAI/bge-m3")
    logger.info(f"Model loaded. Embedding dimension: {model.get_sentence_embedding_dimension()}")
    yield
    del model


app = FastAPI(
    title="EchoMe Embedding Service",
    version="0.1.0",
    description="BGE-M3 embedding API for EchoMe vector search",
    lifespan=lifespan,
)


class EmbedRequest(BaseModel):
    """Request to generate embeddings."""
    texts: list[str] = Field(..., min_length=1, max_length=100)


class EmbedResponse(BaseModel):
    """Embedding response."""
    embeddings: list[list[float]]
    dimension: int
    model: str = "BAAI/bge-m3"


@app.get("/health")
async def health():
    """Health check."""
    if model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    return {
        "status": "ok",
        "model": "BAAI/bge-m3",
        "dimension": model.get_sentence_embedding_dimension(),
    }


@app.post("/embed", response_model=EmbedResponse)
async def embed(request: EmbedRequest):
    """Generate embeddings for a list of texts."""
    if model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")

    try:
        # BGE-M3 recommends prepending "Represent this sentence: " for better quality
        # But for mixed Chinese/English short texts, raw input works well too
        embeddings = model.encode(
            request.texts,
            normalize_embeddings=True,  # L2 normalize for cosine similarity
            show_progress_bar=False,
        )

        # Convert numpy to list
        embeddings_list = embeddings.tolist()

        return EmbedResponse(
            embeddings=embeddings_list,
            dimension=len(embeddings_list[0]),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Embedding failed: {e}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=20002)
