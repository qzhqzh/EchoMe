"""Explicit scenario and continuing-item tools for AI clients."""

import json
from typing import Any
from urllib.parse import quote

import httpx

from echome_mcp.hub_client import MCPHubClient
from echome_mcp.tools.read_views import (
    check_view,
    page_options,
    pagination,
    scene_safety_refs,
    scene_view,
)


def _segment(value: str) -> str:
    if not value or "/" in value or ".." in value:
        raise ValueError("Invalid scenario identifier")
    return quote(value, safe="")


async def _request(
    method: str,
    path: str,
    data: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> str:
    try:
        result = await MCPHubClient().scenario_request(method, path, data, params)
        return json.dumps(result, ensure_ascii=False)
    except httpx.HTTPStatusError as exc:
        try:
            detail = exc.response.json().get("detail")
        except (ValueError, AttributeError):
            detail = None
        return json.dumps(
            {
                "schema_version": "echome.error.v1",
                "error": {
                    "code": "SCENARIO_REQUEST_FAILED",
                    "status": exc.response.status_code,
                    "message": detail or "Scenario request failed",
                },
            },
            ensure_ascii=False,
        )


async def echome_scenario_resolve(
    selector: str,
    parameters: dict[str, str] | None = None,
    environment: dict[str, str] | None = None,
) -> str:
    """Resolve only a user-specified scene ID or alias; no automatic execution."""
    return await _request(
        "POST",
        "/resolve",
        {
            "selector": selector,
            "parameters": parameters or {},
            "environment": environment or {},
        },
    )


async def echome_scenario_catalog(
    action: str,
    slug: str | None = None,
    version: int | None = None,
    data: dict[str, Any] | None = None,
) -> str:
    """Manage scenario definitions and publication with explicit evidence."""
    if action == "list":
        return await _request("GET", "")
    if action == "create":
        return await _request("POST", "", data or {})
    if slug is None:
        raise ValueError("slug is required")
    path = f"/catalog/{_segment(slug)}"
    if action == "get":
        return await _request("GET", path)
    if action == "new_version":
        return await _request("POST", f"{path}/versions", data or {})
    if action in {"publish", "activate"}:
        if version is None or version < 1:
            raise ValueError("version is required")
        return await _request("POST", f"{path}/versions/{version}/{action}", data)
    if action in {"disable", "enable"}:
        return await _request("PATCH", path, {"enabled": action == "enable"})
    raise ValueError("Unknown catalog action")


async def echome_scenario_item(
    action: str,
    item_id: str | None = None,
    data: dict[str, Any] | None = None,
) -> str:
    """Create or manage standalone and scenario-bound items, including explicit binding."""
    if action == "list":
        return await _request("GET", "/items", params=data)
    if action == "due":
        return await _request("GET", "/due", params=data)
    if action == "create":
        return await _request("POST", "/items", data or {})
    if item_id is None:
        raise ValueError("item_id is required")
    path = f"/items/{_segment(item_id)}"
    if action == "get":
        return await _request("GET", path)
    if action == "update":
        return await _request("PATCH", path, data or {})
    if action == "upgrade":
        return await _request("POST", f"{path}/upgrade", data or {})
    if action == "bind":
        return await _request("POST", f"{path}/bind", data or {})
    raise ValueError("Unknown item action")


async def echome_scenario_run(
    action: str,
    item_id: str,
    run_id: str | None = None,
    data: dict[str, Any] | None = None,
) -> str:
    """Claim one execution lease, finish it, or inspect recent runs."""
    path = f"/items/{_segment(item_id)}"
    if action == "list":
        return await _request("GET", f"{path}/runs")
    if action == "claim":
        return await _request("POST", f"{path}/claim", data or {})
    if action == "finish":
        if run_id is None:
            raise ValueError("run_id is required to finish")
        return await _request("POST", f"{path}/runs/{_segment(run_id)}/finish", data or {})
    raise ValueError("Unknown run action")


async def echome_scene_read(
    action: str,
    selector: str | None = None,
    entry_id: str | None = None,
    query: str | None = None,
    include_archived: bool = False,
    view: str = "compact",
    offset: int = 0,
    limit: int = 10,
) -> str:
    """Read a paged scene index, one complete entry, or an explicit full document."""
    check_view(view)
    page_options({"offset": offset, "limit": limit})
    if action == "list":
        payload = json.loads(
            await _request(
                "GET",
                "/knowledge",
                params={
                    "query": query,
                    "include_archived": include_archived,
                    "offset": offset,
                    "limit": limit,
                },
            )
        )
        if "error" not in payload and "items" in payload:
            payload.update(pagination(payload["total"], offset, len(payload["items"]), limit))
            if view == "compact":
                for item in payload["items"]:
                    summary = item.pop("summary", "")
                    item["summary_preview"] = summary[:180]
                    item["summary_chars"] = len(summary)
                    item["needs_expansion"] = True
                    item["read"] = {
                        "tool": "echome_scene_read",
                        "arguments": {
                            "action": "get",
                            "selector": item["slug"],
                            "include_archived": include_archived,
                        },
                    }
        return json.dumps(payload, ensure_ascii=False)
    if selector is None:
        raise ValueError("selector is required")
    path = f"/knowledge/{_segment(selector)}"
    if action == "get":
        raw = await _request("GET", path, params={"include_archived": include_archived})
        payload = json.loads(raw)
        if "error" in payload:
            return raw
        if entry_id is not None:
            _segment(entry_id)
            entry = next(
                (item for item in payload.get("entries", []) if item.get("id") == entry_id), None
            )
            if entry is None:
                return json.dumps(
                    {
                        "schema_version": "echome.error.v1",
                        "error": {
                            "code": "SCENARIO_REQUEST_FAILED",
                            "status": 404,
                            "message": "Scene entry not found in the selected archive scope",
                        },
                    }
                )
            return json.dumps(
                {
                    "scene": payload.get("scene"),
                    "entry": entry,
                    "safety_refs": scene_safety_refs(payload.get("entries", []), selector),
                    "view": "full_entry",
                    "needs_expansion": False,
                    "notice": "One complete entry only; other scene cautions may also apply.",
                },
                ensure_ascii=False,
            )
        if view == "full":
            return raw
        result = scene_view(payload, selector, offset, limit)
        if "read" in result:
            result["read"]["arguments"]["include_archived"] = include_archived
        return json.dumps(result, ensure_ascii=False)
    if action == "history":
        if entry_id is None:
            raise ValueError("entry_id is required")
        return await _request("GET", f"{path}/entries/{_segment(entry_id)}/history")
    raise ValueError("Unknown scene read action")


async def echome_scene_write(
    action: str,
    selector: str | None = None,
    entry_id: str | None = None,
    data: dict[str, Any] | None = None,
) -> str:
    """Add or correct one sourced item; formal SOP needs independent validation evidence."""
    if action == "create":
        return await _request("POST", "/knowledge", data or {})
    if selector is None:
        raise ValueError("selector is required")
    path = f"/knowledge/{_segment(selector)}"
    if action == "add":
        return await _request("POST", f"{path}/entries", data or {})
    if action == "add_batch":
        return await _request("POST", f"{path}/entries/batch", data or {})
    if action == "publish_sop":
        return await _request("POST", f"{path}/sops", data or {})
    if action == "correct":
        if entry_id is None:
            raise ValueError("entry_id is required")
        return await _request("PATCH", f"{path}/entries/{_segment(entry_id)}", data or {})
    raise ValueError("Unknown scene write action")
