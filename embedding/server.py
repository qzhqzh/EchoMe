"""EchoMe Embedding Service - BGE-M3 via modelscope + sentence-transformers."""

import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from sentence_transformers import SentenceTransformer

logger = logging.getLogger("embedding")
logging.basicConfig(level=logging.INFO)

MODEL_DIR = os.environ.get("MODEL_DIR", "/app/models/BAAI/bge-m3")
model: SentenceTransformer | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Load model on startup."""
    global model
    logger.info(f"Loading model from {MODEL_DIR} ...")
    model = SentenceTransformer(MODEL_DIR)
    logger.info(f"Model loaded. Dimension: {model.get_sentence_embedding_dimension()}")
    yield
    del model


app = FastAPI(
    title="EchoMe Embedding Service",
    version="0.2.0",
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
        embeddings = model.encode(
            request.texts,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
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
