"""HTTP client for MCP Server to communicate with EchoMe Hub."""

from pathlib import Path
from typing import Any

import httpx
import yaml

CONFIG_FILE = Path.home() / ".echome" / "config.yaml"


def _load_config() -> dict[str, str]:
    """Load Hub URL and token from ~/.echome/config.yaml."""
    if not CONFIG_FILE.exists():
        return {"hub_url": "http://localhost:20000", "token": ""}
    with open(CONFIG_FILE) as f:
        data = yaml.safe_load(f) or {}
    return {
        "hub_url": data.get("hub_url", "http://localhost:20000"),
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
        memory_type: str | None = None,
        project_id: str | None = None,
        top_k: int = 5,
    ) -> dict[str, Any]:
        """Search memories."""
        payload: dict[str, Any] = {"query": query, "top_k": top_k}
        if memory_type:
            payload["type"] = memory_type
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

    async def list_by_type(self, memory_type: str, status: str = "active") -> dict[str, Any]:
        """List memories by type."""
        async with httpx.AsyncClient(base_url=self.base_url, headers=self._headers) as client:
            resp = await client.get(
                "/api/v1/memories",
                params={"type": memory_type, "status": status},
            )
            resp.raise_for_status()
            return resp.json()

    async def browse_memories(
        self,
        memory_type: str | None = None,
        status: str = "active",
        project_id: str | None = None,
        query: str | None = None,
        limit: int = 30,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Browse compact memory index entries."""
        params: dict[str, Any] = {
            "status": status,
            "limit": limit,
            "offset": offset,
        }
        if memory_type:
            params["type"] = memory_type
        if project_id:
            params["project_id"] = project_id
        if query:
            params["query"] = query

        async with httpx.AsyncClient(base_url=self.base_url, headers=self._headers) as client:
            resp = await client.get("/api/v1/memories", params=params)
            resp.raise_for_status()
            return resp.json()

    async def create_memory(self, data: dict[str, Any]) -> dict[str, Any]:
        """Create a new memory (for AI-suggested memories)."""
        async with httpx.AsyncClient(base_url=self.base_url, headers=self._headers) as client:
            resp = await client.post("/api/v1/memories", json=data)
            resp.raise_for_status()
            return resp.json()

    async def sleep_candidates(self, data: dict[str, Any]) -> dict[str, Any]:
        """Request memory sleep candidates."""
        async with httpx.AsyncClient(base_url=self.base_url, headers=self._headers) as client:
            resp = await client.post("/api/v1/memory-sleep/candidates", json=data)
            resp.raise_for_status()
            return resp.json()

    async def sleep_submit_proposal(
        self,
        session_id: str,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        """Submit a memory sleep proposal."""
        async with httpx.AsyncClient(base_url=self.base_url, headers=self._headers) as client:
            resp = await client.post(
                f"/api/v1/memory-sleep/sessions/{session_id}/proposal",
                json=data,
            )
            resp.raise_for_status()
            return resp.json()

    async def sleep_apply(self, session_id: str, approved: bool = True) -> dict[str, Any]:
        """Apply an approved memory sleep proposal."""
        async with httpx.AsyncClient(base_url=self.base_url, headers=self._headers) as client:
            resp = await client.post(
                f"/api/v1/memory-sleep/sessions/{session_id}/apply",
                json={"approved": approved},
            )
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

    async def list_projects(self) -> list[dict[str, Any]]:
        """List all projects for the current user."""
        async with httpx.AsyncClient(base_url=self.base_url, headers=self._headers) as client:
            resp = await client.get("/api/v1/projects")
            resp.raise_for_status()
            return resp.json()

    async def get_project(self, project_id: str) -> dict[str, Any] | None:
        """Get a project by ID. Returns None if not found."""
        async with httpx.AsyncClient(base_url=self.base_url, headers=self._headers) as client:
            resp = await client.get(f"/api/v1/projects/{project_id}")
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()

    async def create_project(
        self,
        id: str,
        name: str,
        description: str | None = None,
        git_remote: str | None = None,
    ) -> dict[str, Any]:
        """Create a new project."""
        data = {
            "id": id,
            "name": name,
            "description": description,
            "git_remote": git_remote,
            "path_patterns": [],
        }
        async with httpx.AsyncClient(base_url=self.base_url, headers=self._headers) as client:
            resp = await client.post("/api/v1/projects", json=data)
            resp.raise_for_status()
            return resp.json()
