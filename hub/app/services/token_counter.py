"""Token counting utility using tiktoken with an offline-safe fallback."""

import hashlib
import os
import tempfile
from pathlib import Path

import tiktoken

_ENCODING_URL = "https://openaipublic.blob.core.windows.net/encodings/cl100k_base.tiktoken"
_CACHE_KEY = hashlib.sha1(_ENCODING_URL.encode()).hexdigest()


def _encoding_cache_path() -> Path | None:
    configured = os.getenv("TIKTOKEN_CACHE_DIR")
    if configured is None:
        configured = os.getenv("DATA_GYM_CACHE_DIR")
    if configured == "":
        return None
    cache_dir = Path(configured) if configured else Path(tempfile.gettempdir()) / "data-gym-cache"
    return cache_dir / _CACHE_KEY


def _load_encoding(*, allow_download: bool | None = None) -> tiktoken.Encoding | None:
    if allow_download is None:
        allow_download = os.getenv("ECHOME_TIKTOKEN_ALLOW_DOWNLOAD", "").lower() in {
            "1",
            "true",
            "yes",
        }
    cache_path = _encoding_cache_path()
    if not allow_download and (cache_path is None or not cache_path.is_file()):
        return None
    try:
        return tiktoken.get_encoding("cl100k_base")
    except Exception:
        return None


_encoding = _load_encoding()


def count_tokens(text: str) -> int:
    """Count the number of tokens in a text string."""
    if _encoding is None:
        # Rough fallback for offline startup/tests when tiktoken cannot load its BPE file.
        return max(1, len(text) // 4)
    return len(_encoding.encode(text))
