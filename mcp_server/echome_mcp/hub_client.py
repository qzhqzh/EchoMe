"""HTTP client for MCP Server to communicate with EchoMe Hub."""

from pathlib import Path
from typing import Any

import httpx
import yaml

CONFIG_FILE = Path.home() / ".echome" / "config.yaml"


def _load_config() -> dict[str, str]:
    """Load Hub URL and token from ~/.echome/config.yaml."""
    if not CONFIG_FILE.exists():
        return {"hub_url": "http://localhost:8000", "token": ""}
    with open(CONFIG_FILE) as f:
        data = yaml.safe_load(f) or {}
    return {
        "hub_url": data.get("hub_url", "http://localhost:8000"),
        "token": data.get("token", ""),
    }


class MCPHubClient:
    """Async HTTP client used by MCP server to query Hub."""

    def __init__(self) -> None:
        config = _load_config()
        self.base_url = config["hub_url"].rstrip("/")
        self._headers = {
            "Authorization": f"Bearer {config['token']}",
            "Content-Type": "application/json",
        }

    async def search(
        self,
        query: str,
        type: str | None = None,
        project_id: str | None = None,
        top_k: int = 5,
    ) -> dict[str, Any]:
        """Search memories."""
        payload: dict[str, Any] = {"query": query, "top_k": top_k}
        if type:
            payload["type"] = type
        if project_id:
            payload["project_id"] = project_id

        async with httpx.AsyncClient(base_url=self.base_url, headers=self._headers) as client:
            resp = await client.post("/api/v1/memories/search", json=payload)
            resp.raise_for_status()
            return resp.json()

    async def get_memory(self, memory_id: str) -> dict[str, Any]:
        """Get a single memory by ID."""
        async with httpx.AsyncClient(base_url=self.base_url, headers=self._headers) as client:
            resp = await client.get(f"/api/v1/memories/{memory_id}")
            resp.raise_for_status()
            return resp.json()

    async def list_by_type(self, type: str, status: str = "active") -> dict[str, Any]:
        """List memories by type."""
        async with httpx.AsyncClient(base_url=self.base_url, headers=self._headers) as client:
            resp = await client.get("/api/v1/memories", params={"type": type, "status": status})
            resp.raise_for_status()
            return resp.json()

    async def create_memory(self, data: dict[str, Any]) -> dict[str, Any]:
        """Create a new memory (for AI-suggested memories)."""
        async with httpx.AsyncClient(base_url=self.base_url, headers=self._headers) as client:
            resp = await client.post("/api/v1/memories", json=data)
            resp.raise_for_status()
            return resp.json()

    async def get_project_memories(self, project_id: str) -> dict[str, Any]:
        """Get all memories scoped to a project."""
        async with httpx.AsyncClient(base_url=self.base_url, headers=self._headers) as client:
            resp = await client.get(
                "/api/v1/memories", params={"project_id": project_id, "limit": 50}
            )
            resp.raise_for_status()
            return resp.json()

    async def health(self) -> dict[str, Any]:
        """Check Hub health."""
        async with httpx.AsyncClient(base_url=self.base_url, headers=self._headers) as client:
            resp = await client.get("/health")
            resp.raise_for_status()
            return resp.json()
