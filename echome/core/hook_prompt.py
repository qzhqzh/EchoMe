"""Extract task text from the small set of known Codex message envelopes.

This is input adaptation, not a general XML or Markdown sanitizer. Unknown
markup, user URLs, attachments and code examples remain part of the task.
"""

from __future__ import annotations

import json
import re

_AMBIENT_TAGS = (
    "in-app-browser-context",
    "external_codex_apps_open_page",
    "environment_context",
)
_ENVELOPE = re.compile(
    r"(?m)^[ \t]*<(?P<tag>"
    + "|".join((*_AMBIENT_TAGS, "send_user_message_question_reply"))
    + r")(?:[ \t][^>\n]*)?>(?P<body>[\s\S]*?)</(?P=tag)>[ \t]*(?=\n|$)"
)
_FENCE = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})")
_REQUEST_LABEL = re.compile(r"\A\s*## My request:[ \t]*\n")


def _fenced_ranges(text: str) -> list[tuple[int, int]]:
    """Keep literal envelope examples in Markdown code fences unchanged."""
    ranges = []
    start: int | None = None
    fence = ""
    offset = 0
    for line in text.splitlines(keepends=True):
        match = _FENCE.match(line)
        if match:
            marker = match[1]
            if start is None:
                start, fence = offset, marker
            elif marker[0] == fence[0] and len(marker) >= len(fence):
                ranges.append((start, offset + len(line)))
                start = None
        offset += len(line)
    if start is not None:
        ranges.append((start, len(text)))
    return ranges


def _question_reply(body: str) -> str | None:
    try:
        replies = json.loads(body)
    except (ValueError, TypeError):
        return None
    if not isinstance(replies, list) or not replies:
        return None
    result = []
    for item in replies:
        if not isinstance(item, dict) or not isinstance(item.get("answer"), str):
            return None
        question = item.get("question", "")
        if not isinstance(question, str):
            return None
        # Keep the question for short answers such as a version or directory;
        # IDs and other client metadata do not describe the user's task.
        if question.strip():
            result.append("问题： " + question.strip())
        result.append("回答： " + item["answer"].strip())
    return "\n".join(result)


def normalize_hook_prompt(prompt: str) -> str:
    """Strip known complete ambient blocks, retaining the user's task semantics."""
    fenced = _fenced_ranges(prompt)
    removed_ambient = False

    def replace(match: re.Match[str]) -> str:
        nonlocal removed_ambient
        if any(start <= match.start() < end for start, end in fenced):
            return match[0]
        if match["tag"] in _AMBIENT_TAGS:
            removed_ambient = True
            return ""
        reply = _question_reply(match["body"])
        # Unknown/malformed replies stay intact rather than losing user input.
        return match[0] if reply is None else reply

    text = _ENVELOPE.sub(replace, prompt)
    if removed_ambient:
        text = _REQUEST_LABEL.sub("", text)
    return text.strip()
