"""Token counting utility using tiktoken with an offline-safe fallback."""

import tiktoken

try:
    _encoding = tiktoken.get_encoding("cl100k_base")
except Exception:
    _encoding = None


def count_tokens(text: str) -> int:
    """Count the number of tokens in a text string."""
    if _encoding is None:
        # Rough fallback for offline startup/tests when tiktoken cannot load its BPE file.
        return max(1, len(text) // 4)
    return len(_encoding.encode(text))
