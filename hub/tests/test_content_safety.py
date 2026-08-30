"""Tests for high-confidence secret rejection at the Hub trust boundary."""

import json
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.services.content_safety import (
    find_sensitive_content,
    require_safe_artifact,
    require_safe_content,
)
from app.services.embedding import get_embeddings


@pytest.mark.parametrize(
    "content",
    [
        "API_KEY=${ECHOME_API_KEY}",
        "password=<set-me>",
        "token = test-token-for-ci-only",
        "api_key = your_api_key_here",
        "Use ECHOME_API_KEY from the environment.",
    ],
)
def test_documentation_placeholders_are_allowed(content: str) -> None:
    require_safe_content(content)


@pytest.mark.parametrize(
    ("content", "kind"),
    [
        ("-----BEGIN " + "PRIVATE KEY-----\nmaterial", "private_key"),
        ("token=" + "ghp_" + "abcdefghijklmnopqrstuvwxyz123456", "github_token"),
        ("AWS_ACCESS_KEY_ID=" + "AKIA" + "1234567890ABCDEF", "aws_access_key"),
        ("password=" + "V3ry-Private-Password-9081", "credential_assignment"),
        ("postgresql://user:" + "V3ryPrivate9081@db/prod", "url_credential"),
        ("Authorization: Bearer " + "prodTokenABC1234567890", "bearer_token"),
        ("eyJ" + "a" * 20 + "." + "b" * 20 + "." + "c" * 20, "jwt"),
    ],
)
def test_realistic_secret_shapes_are_rejected_without_echo(content: str, kind: str) -> None:
    with pytest.raises(HTTPException) as exc_info:
        require_safe_content(content)

    detail = exc_info.value.detail
    assert detail["code"] == "sensitive_content_rejected"
    assert kind in {item["kind"] for item in detail["findings"]}
    assert "V3ry" not in str(detail)
    assert "ghp_" not in str(detail)


def test_sensitive_artifact_path_is_rejected_but_template_is_allowed() -> None:
    with pytest.raises(HTTPException):
        require_safe_artifact("deploy/.env.production", "DEBUG=false")

    require_safe_artifact("deploy/.env.example", "API_KEY=${API_KEY}")


def test_artifact_metadata_is_scanned_recursively() -> None:
    metadata = json.dumps({"deployment": {"password": "V3ry-" + "Private-Password-9081"}})

    with pytest.raises(HTTPException):
        require_safe_artifact("docs/deploy.json", "safe body", metadata)


@pytest.mark.asyncio
async def test_embedding_client_blocks_sensitive_text_before_network() -> None:
    with patch("app.services.embedding.httpx.AsyncClient") as client:
        result = await get_embeddings(
            ["Authorization: Bearer " + "prodTokenABC1234567890"]
        )

    assert result is None
    client.assert_not_called()


def test_findings_report_location_not_secret_value() -> None:
    findings = find_sensitive_content("safe\npassword=" + "V3ry-Private-Password-9081")

    assert findings == [{"kind": "credential_assignment", "line": 2}]
