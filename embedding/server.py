"""EchoMe Embedding Service - BGE-M3 via Sentence Transformers and PyTorch."""

import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

import torch
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, StringConstraints
from sentence_transformers import SentenceTransformer

logger = logging.getLogger("embedding")
logging.basicConfig(level=logging.INFO)

MODEL_DIR = os.environ.get("MODEL_DIR", "/app/models")
DEVICE = os.environ.get("ECHOME_EMBEDDING_DEVICE", "cpu").strip().lower()
USE_FP16 = os.environ.get("ECHOME_EMBEDDING_FP16", "false").strip().lower() in {
    "1",
    "true",
    "yes",
}
MAX_SEQ_LENGTH = int(os.environ.get("ECHOME_EMBEDDING_MAX_SEQ_LENGTH", "1024"))
MAX_TEXT_CHARS = int(os.environ.get("ECHOME_EMBEDDING_MAX_CHARS", "8000"))
BATCH_SIZE = int(os.environ.get("ECHOME_EMBEDDING_BATCH_SIZE", "8"))
model: SentenceTransformer | None = None


def _find_model_path() -> str:
    """Find the actual model path inside MODEL_DIR.

    ModelScope downloads to: MODEL_DIR/BAAI/bge-m3/
    Direct download might be: MODEL_DIR/ (with config.json at root)
    """
    base = Path(MODEL_DIR)

    # Check if config.json exists directly in MODEL_DIR
    if (base / "config.json").exists():
        return str(base)

    # Check ModelScope layout: MODEL_DIR/BAAI/bge-m3/
    ms_path = base / "BAAI" / "bge-m3"
    if (ms_path / "config.json").exists():
        return str(ms_path)

    # Check HuggingFace cache layout: MODEL_DIR/models--BAAI--bge-m3/snapshots/xxx/
    hf_path = base / "models--BAAI--bge-m3"
    if hf_path.exists():
        snapshots = hf_path / "snapshots"
        if snapshots.exists():
            # Get the latest snapshot
            snapshot_dirs = sorted(snapshots.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
            if snapshot_dirs and (snapshot_dirs[0] / "config.json").exists():
                return str(snapshot_dirs[0])

    # Fallback: return MODEL_DIR and let sentence-transformers handle the error
    logger.warning(f"Could not find config.json in {MODEL_DIR}, trying as-is...")
    return str(base)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Load model on startup."""
    global model
    if DEVICE.startswith("cuda") and not torch.cuda.is_available():
        raise RuntimeError(
            f"CUDA device {DEVICE!r} was requested but is unavailable "
            f"with torch {torch.__version__}"
        )
    if USE_FP16 and not DEVICE.startswith("cuda"):
        raise RuntimeError("FP16 inference is only supported by this service on CUDA")

    model_path = _find_model_path()
    logger.info("Loading model from %s on %s ...", model_path, DEVICE)
    model = SentenceTransformer(
        model_path,
        device=DEVICE,
        local_files_only=True,
        model_kwargs={"torch_dtype": torch.float16} if USE_FP16 else None,
    )
    model.max_seq_length = MAX_SEQ_LENGTH
    logger.info(
        "Model loaded. Dimension: %s; dtype: %s; max sequence length: %s",
        model.get_sentence_embedding_dimension(),
        next(model.parameters()).dtype,
        model.max_seq_length,
    )
    try:
        yield
    finally:
        model = None
        if DEVICE.startswith("cuda"):
            torch.cuda.empty_cache()


app = FastAPI(
    title="EchoMe Embedding Service",
    version="0.2.0",
    description="BGE-M3 embedding API for EchoMe vector search",
    lifespan=lifespan,
)


class EmbedRequest(BaseModel):
    """Request to generate embeddings."""

    texts: list[Annotated[str, StringConstraints(max_length=MAX_TEXT_CHARS)]] = Field(
        ..., min_length=1, max_length=100
    )


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
        "backend": "pytorch",
        "device": str(model.device),
        "dtype": str(next(model.parameters()).dtype).removeprefix("torch."),
        "dimension": model.get_sentence_embedding_dimension(),
        "max_seq_length": model.max_seq_length,
        "max_text_chars": MAX_TEXT_CHARS,
        "batch_size": BATCH_SIZE,
    }


@app.post("/embed", response_model=EmbedResponse)
async def embed(request: EmbedRequest):
    """Generate embeddings for a list of texts."""
    if model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")

    try:
        embeddings = model.encode(
            request.texts,
            batch_size=BATCH_SIZE,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        embeddings_list = embeddings.tolist()

        return EmbedResponse(
            embeddings=embeddings_list,
            dimension=len(embeddings_list[0]),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Embedding failed: {e}") from e


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=20002)
