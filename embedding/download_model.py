"""Download BGE-M3 model from ModelScope (fast in China)."""

import os

from modelscope import snapshot_download

MODEL_DIR = os.environ.get("MODEL_DIR", "/app/models")

print(f"Downloading BAAI/bge-m3 to {MODEL_DIR}/BAAI/bge-m3 ...")
snapshot_download("BAAI/bge-m3", cache_dir=MODEL_DIR)
print("Done! Model saved to: {}/BAAI/bge-m3".format(MODEL_DIR))
