"""Token counting utility using tiktoken."""

import tiktoken

_encoding = tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    """Count the number of tokens in a text string."""
    return len(_encoding.encode(text))
