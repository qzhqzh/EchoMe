"""HTTP client for MCP Server to communicate with EchoMe Hub."""

import hashlib
from pathlib import Path
from typing import Any

import httpx
import yaml

CONFIG_FILE = Path.home() / ".echome" / "config.yaml"
PROJECT_CONTEXT_TIMEOUT = httpx.Timeout(120.0)


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
        self.cache_namespace = hashlib.sha256(
            f"{self.base_url}\0{config['token']}".encode()
        ).hexdigest()
        self.cache_enabled = bool(config["token"])
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

    async def memory_neighbors(
        self,
        memory_id: str,
        depth: int = 1,
        include_inactive: bool = True,
        limit: int = 200,
    ) -> dict[str, Any]:
        """Get a local memory graph around one memory."""
        async with httpx.AsyncClient(base_url=self.base_url, headers=self._headers) as client:
            resp = await client.get(
                f"/api/v1/observability/memory-graph/neighbors/{memory_id}",
                params={
                    "depth": depth,
                    "include_inactive": include_inactive,
                    "limit": limit,
                },
            )
            resp.raise_for_status()
            return resp.json()

    async def memory_explain(
        self,
        memory_id: str,
        include_inactive: bool = True,
    ) -> dict[str, Any]:
        """Explain one memory with graph provenance and temporal status."""
        async with httpx.AsyncClient(base_url=self.base_url, headers=self._headers) as client:
            resp = await client.get(
                f"/api/v1/observability/memory-graph/explain/{memory_id}",
                params={"include_inactive": include_inactive},
            )
            resp.raise_for_status()
            return resp.json()

    async def temporal_candidates(
        self,
        project_id: str | None = None,
        include_inactive: bool = False,
        classifications: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """List memories that may need temporal review."""
        params: dict[str, Any] = {
            "include_inactive": include_inactive,
            "limit": limit,
        }
        if project_id:
            params["project_id"] = project_id
        if classifications:
            params["classifications"] = classifications
        async with httpx.AsyncClient(base_url=self.base_url, headers=self._headers) as client:
            resp = await client.get(
                "/api/v1/observability/memory-graph/temporal-candidates",
                params=params,
            )
            resp.raise_for_status()
            return resp.json()

    async def create_memory_feedback(self, data: dict[str, Any]) -> dict[str, Any]:
        """Record one memory feedback signal."""
        async with httpx.AsyncClient(base_url=self.base_url, headers=self._headers) as client:
            resp = await client.post("/api/v1/memory-feedback", json=data)
            resp.raise_for_status()
            return resp.json()

    async def create_memory_feedback_batch(self, items: list[dict[str, Any]]) -> dict[str, Any]:
        """Record several memory feedback signals."""
        async with httpx.AsyncClient(base_url=self.base_url, headers=self._headers) as client:
            resp = await client.post("/api/v1/memory-feedback/batch", json={"items": items})
            resp.raise_for_status()
            return resp.json()

    async def create_retrieval_log(self, data: dict[str, Any]) -> dict[str, Any]:
        """Record a retrieval debug log."""
        async with httpx.AsyncClient(base_url=self.base_url, headers=self._headers) as client:
            resp = await client.post("/api/v1/retrieval-debug/logs", json=data)
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

    async def project_context(
        self,
        project_id: str,
        task: str,
        changed_paths: list[str] | None = None,
        limit: int = 20,
        mode: str = "local",
        token_budget: int = 6000,
        as_of: str | None = None,
        valid_at: str | None = None,
        record_run: bool = True,
        shadow: bool = False,
        policy_mode: str = "shadow",
    ) -> dict[str, Any]:
        """Get task-aware memory, constraint, and artifact context."""
        payload = {
            "project_id": project_id,
            "task": task,
            "changed_paths": changed_paths or [],
            "limit": limit,
            "mode": mode,
            "token_budget": token_budget,
            "as_of": as_of,
            "valid_at": valid_at,
            "record_run": record_run,
            "shadow": shadow,
            "policy_mode": policy_mode,
        }
        async with httpx.AsyncClient(
            base_url=self.base_url,
            headers=self._headers,
            timeout=PROJECT_CONTEXT_TIMEOUT,
        ) as client:
            resp = await client.post("/api/v1/project-knowledge/context", json=payload)
            resp.raise_for_status()
            return resp.json()

    async def prepare_reflection(self, data: dict[str, Any]) -> dict[str, Any]:
        """Prepare an evidence-complete, read-only project reflection contract."""
        async with httpx.AsyncClient(
            base_url=self.base_url,
            headers=self._headers,
            timeout=PROJECT_CONTEXT_TIMEOUT,
        ) as client:
            resp = await client.post(
                "/api/v1/project-knowledge/views/reflect/prepare",
                json=data,
            )
            resp.raise_for_status()
            payload = resp.json()
            if not isinstance(payload, dict):
                raise TypeError("Reflection prepare response must be an object")
            return payload

    async def submit_reflection(self, data: dict[str, Any]) -> dict[str, Any]:
        """Submit an evidence-linked reflection against its prepared source fingerprint."""
        async with httpx.AsyncClient(
            base_url=self.base_url,
            headers=self._headers,
            timeout=PROJECT_CONTEXT_TIMEOUT,
        ) as client:
            resp = await client.post(
                "/api/v1/project-knowledge/views/reflect/submit",
                json=data,
            )
            resp.raise_for_status()
            payload = resp.json()
            if not isinstance(payload, dict):
                raise TypeError("Reflection submit response must be an object")
            return payload

    async def unified_context(self, data: dict[str, Any]) -> dict[str, Any]:
        """Get one routed personal or project context envelope."""
        async with httpx.AsyncClient(
            base_url=self.base_url,
            headers=self._headers,
            timeout=PROJECT_CONTEXT_TIMEOUT,
        ) as client:
            resp = await client.post("/api/v1/context", json=data)
            resp.raise_for_status()
            return resp.json()

    async def runtime_health(self) -> dict[str, Any]:
        """Check authenticated Hub runtime dependencies."""
        async with httpx.AsyncClient(base_url=self.base_url, headers=self._headers) as client:
            resp = await client.get("/api/v1/context/runtime/health")
            resp.raise_for_status()
            return resp.json()

    async def context_policy_readiness(
        self,
        *,
        project_id: str | None = None,
        window_days: int = 30,
    ) -> dict[str, Any]:
        """Read the derived, non-activating context policy rollout gate."""
        params: dict[str, str | int] = {"window_days": window_days}
        if project_id:
            params["project_id"] = project_id
        async with httpx.AsyncClient(base_url=self.base_url, headers=self._headers) as client:
            resp = await client.get(
                "/api/v1/observability/context-policy/readiness",
                params=params,
            )
            resp.raise_for_status()
            payload = resp.json()
            if not isinstance(payload, dict):
                raise TypeError("Context policy readiness response must be an object")
            return payload

    async def create_context_outcome(self, data: dict[str, Any]) -> dict[str, Any]:
        """Append an explicit result signal for one completed context run."""
        async with httpx.AsyncClient(base_url=self.base_url, headers=self._headers) as client:
            resp = await client.post("/api/v1/context-outcomes", json=data)
            resp.raise_for_status()
            return resp.json()

    async def append_project_event(self, data: dict[str, Any]) -> dict[str, Any]:
        """Append an evidence-linked project event."""
        async with httpx.AsyncClient(base_url=self.base_url, headers=self._headers) as client:
            resp = await client.post("/api/v1/project-knowledge/events", json=data)
            resp.raise_for_status()
            return resp.json()

    async def project_preflight(
        self,
        project_id: str,
        task: str,
        changed_paths: list[str] | None = None,
        planned_actions: list[str] | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Get read-only, evidence-backed warnings before a project action."""
        payload = {
            "project_id": project_id,
            "task": task,
            "changed_paths": changed_paths or [],
            "planned_actions": planned_actions or [],
            "limit": limit,
        }
        async with httpx.AsyncClient(base_url=self.base_url, headers=self._headers) as client:
            resp = await client.post("/api/v1/project-knowledge/preflight", json=payload)
            resp.raise_for_status()
            return resp.json()

    async def project_impact(
        self,
        project_id: str,
        task: str,
        changed_paths: list[str] | None = None,
        constraint_ids: list[str] | None = None,
        depth: int = 2,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Analyze local impact around a proposed project change."""
        payload = {
            "project_id": project_id,
            "task": task,
            "changed_paths": changed_paths or [],
            "constraint_ids": constraint_ids or [],
            "depth": depth,
            "limit": limit,
        }
        async with httpx.AsyncClient(base_url=self.base_url, headers=self._headers) as client:
            resp = await client.post("/api/v1/project-knowledge/impact", json=payload)
            resp.raise_for_status()
            return resp.json()

    async def check_artifact_sync(
        self, project_id: str, artifacts: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Compare a local artifact manifest without uploading content."""
        async with httpx.AsyncClient(base_url=self.base_url, headers=self._headers) as client:
            resp = await client.post(
                "/api/v1/project-knowledge/artifacts/sync/check",
                json={"project_id": project_id, "artifacts": artifacts},
            )
            resp.raise_for_status()
            return resp.json()

    async def apply_artifact_sync(
        self, project_id: str, artifacts: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Upload only changed artifact content."""
        async with httpx.AsyncClient(base_url=self.base_url, headers=self._headers) as client:
            resp = await client.post(
                "/api/v1/project-knowledge/artifacts/sync/apply",
                json={"project_id": project_id, "artifacts": artifacts},
            )
            resp.raise_for_status()
            return resp.json()

    async def create_constraint(self, data: dict[str, Any]) -> dict[str, Any]:
        """Create a proposed or user-confirmed project constraint."""
        async with httpx.AsyncClient(base_url=self.base_url, headers=self._headers) as client:
            resp = await client.post("/api/v1/project-knowledge/constraints", json=data)
            resp.raise_for_status()
            return resp.json()

    async def list_constraints(self, project_id: str) -> dict[str, Any]:
        """List project constraints for idempotent client workflows."""
        async with httpx.AsyncClient(base_url=self.base_url, headers=self._headers) as client:
            resp = await client.get(
                "/api/v1/project-knowledge/constraints",
                params={"project_id": project_id, "limit": 2000},
            )
            resp.raise_for_status()
            return resp.json()

    async def list_artifacts(self, project_id: str) -> dict[str, Any]:
        """List current project artifacts."""
        async with httpx.AsyncClient(base_url=self.base_url, headers=self._headers) as client:
            resp = await client.get(
                "/api/v1/project-knowledge/artifacts",
                params={"project_id": project_id, "limit": 1000},
            )
            resp.raise_for_status()
            return resp.json()

    async def create_constraint_edge(self, data: dict[str, Any]) -> dict[str, Any]:
        """Create one typed constraint relation."""
        async with httpx.AsyncClient(base_url=self.base_url, headers=self._headers) as client:
            resp = await client.post("/api/v1/project-knowledge/edges", json=data)
            resp.raise_for_status()
            return resp.json()

    async def create_constraint_evidence(self, data: dict[str, Any]) -> dict[str, Any]:
        """Link a constraint to an artifact revision."""
        async with httpx.AsyncClient(base_url=self.base_url, headers=self._headers) as client:
            resp = await client.post("/api/v1/project-knowledge/evidence", json=data)
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

    async def discover_projects(
        self,
        hints: list[str],
        limit: int = 5,
    ) -> dict[str, Any]:
        """Resolve or suggest projects without modifying project identity."""
        async with httpx.AsyncClient(base_url=self.base_url, headers=self._headers) as client:
            resp = await client.post(
                "/api/v1/projects/discover",
                json={"hints": hints, "limit": limit},
            )
            resp.raise_for_status()
            payload = resp.json()
            if not isinstance(payload, dict):
                raise TypeError("Project discovery response must be an object")
            return payload

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
        kind: str = "repository",
        path_patterns: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a new project."""
        data = {
            "id": id,
            "name": name,
            "kind": kind,
            "description": description,
            "git_remote": git_remote,
            "path_patterns": path_patterns or [],
        }
        async with httpx.AsyncClient(base_url=self.base_url, headers=self._headers) as client:
            resp = await client.post("/api/v1/projects", json=data)
            resp.raise_for_status()
            return resp.json()
