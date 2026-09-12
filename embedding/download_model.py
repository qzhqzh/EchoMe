"""Download BGE-M3 model from ModelScope (fast in China)."""

import os

from modelscope import snapshot_download

MODEL_DIR = os.environ.get("MODEL_DIR", "/app/models")
MODEL_REVISION = os.environ.get("MODEL_REVISION") or None

print(f"Downloading BAAI/bge-m3 to {MODEL_DIR}/BAAI/bge-m3 ...")
snapshot_download(
    "BAAI/bge-m3",
    cache_dir=MODEL_DIR,
    revision=MODEL_REVISION,
    ignore_file_pattern=[r"onnx/.*", r"openvino/.*"],
)
print(f"Done! Model saved to: {MODEL_DIR}/BAAI/bge-m3")
