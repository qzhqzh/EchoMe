"""HTTP client for communicating with EchoMe Hub."""

from typing import Any

import httpx

from echome.core.config import Config


class HubClient:
    """Async HTTP client for EchoMe Hub API."""

    def __init__(self, config: Config | None = None) -> None:
        self.config = config or Config.load()
        self.base_url = self.config.hub_url.rstrip("/")
        self._headers = {
            "Authorization": f"Bearer {self.config.token}",
            "Content-Type": "application/json",
        }

    def _client(self) -> httpx.Client:
        """Create a synchronous httpx client."""
        return httpx.Client(
            base_url=self.base_url,
            headers=self._headers,
            timeout=30.0,
        )

    def health(self) -> dict[str, Any]:
        """Check hub health."""
        with self._client() as client:
            resp = client.get("/health")
            resp.raise_for_status()
            return resp.json()

    def list_memories(self, **params: Any) -> dict[str, Any]:
        """List memories with optional filters."""
        with self._client() as client:
            resp = client.get("/api/v1/memories", params=params)
            resp.raise_for_status()
            return resp.json()

    def get_memory(self, memory_id: str) -> dict[str, Any]:
        """Get a single memory."""
        with self._client() as client:
            resp = client.get(f"/api/v1/memories/{memory_id}")
            resp.raise_for_status()
            return resp.json()

    def create_memory(self, data: dict[str, Any]) -> dict[str, Any]:
        """Create a new memory."""
        with self._client() as client:
            resp = client.post("/api/v1/memories", json=data)
            resp.raise_for_status()
            return resp.json()

    def update_memory(self, memory_id: str, data: dict[str, Any]) -> dict[str, Any]:
        """Update a memory."""
        with self._client() as client:
            resp = client.put(f"/api/v1/memories/{memory_id}", json=data)
            resp.raise_for_status()
            return resp.json()

    def delete_memory(self, memory_id: str, hard: bool = False) -> None:
        """Delete a memory."""
        with self._client() as client:
            resp = client.delete(f"/api/v1/memories/{memory_id}", params={"hard": hard})
            resp.raise_for_status()

    def search(self, query: str, **kwargs: Any) -> dict[str, Any]:
        """Search memories."""
        payload = {"query": query, **kwargs}
        with self._client() as client:
            resp = client.post("/api/v1/memories/search", json=payload)
            resp.raise_for_status()
            return resp.json()

    def push(self, memories: list[dict[str, Any]], client_info: str = "") -> dict[str, Any]:
        """Push memories to Hub."""
        payload = {"memories": memories, "client_info": client_info}
        with self._client() as client:
            resp = client.post("/api/v1/sync/push", json=payload)
            resp.raise_for_status()
            return resp.json()

    def pull(self, since: str | None = None, include_pending: bool = True) -> dict[str, Any]:
        """Pull memories from Hub."""
        payload: dict[str, Any] = {"include_pending": include_pending}
        if since:
            payload["since"] = since
        with self._client() as client:
            resp = client.post("/api/v1/sync/pull", json=payload)
            resp.raise_for_status()
            return resp.json()

    def render(self, target: str, project_id: str | None = None) -> dict[str, Any]:
        """Render memories for a target CLI."""
        payload: dict[str, Any] = {"target": target}
        if project_id:
            payload["project_id"] = project_id
        with self._client() as client:
            resp = client.post("/api/v1/sync/render", json=payload)
            resp.raise_for_status()
            return resp.json()
