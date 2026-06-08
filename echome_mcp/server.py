"""EchoMe MCP Server - Main server implementation."""

import asyncio
import contextlib
from collections.abc import AsyncIterator
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.types import TextContent, Tool
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from echome_mcp.tools.browse import echome_browse_memories, echome_search_summary
from echome_mcp.tools.get import echome_get
from echome_mcp.tools.get_many import echome_get_memories
from echome_mcp.tools.list_by_type import echome_list_by_type
from echome_mcp.tools.project import echome_create_project, echome_list_projects
from echome_mcp.tools.project_context import echome_get_project_context
from echome_mcp.tools.remember import echome_remember
from echome_mcp.tools.search import echome_search
from echome_mcp.tools.sleep import (
    echome_sleep_apply,
    echome_sleep_candidates,
    echome_sleep_submit_proposal,
)

# Create MCP server instance
server = Server("echome")


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List all available EchoMe tools."""
    return [
        Tool(
            name="echome_search",
            description=(
                "Search user's personal memories and knowledge. "
                "Use when you need to know the user's workflow rules, technical preferences, "
                "project background, past decisions, or any stored context. "
                "Call this before making assumptions about the user's conventions. "
                "For broad or uncertain questions, prefer echome_search_summary first, then echome_get_memories with selected UUIDs for full content."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query - keywords or natural language question",
                    },
                    "type": {
                        "type": "string",
                        "enum": [
                            "identity", "guardrail", "reasoning", "method", "stack",
                            "style", "decision", "context", "template", "project",
                        ],
                        "description": "Optional: filter by memory type",
                    },
                    "project_id": {
                        "type": "string",
                        "description": "Optional: filter by project ID (e.g. 'user/repo')",
                    },
                    "top_k": {
                        "type": "integer",
                        "default": 5,
                        "description": "Number of results to return (default: 5)",
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="memory_search",
            description=(
                "Alias for echome_search. Search user memories and knowledge. "
                "Use this when an agent expects a generic memory_search tool name."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "type": {
                        "type": "string",
                        "enum": [
                            "identity", "guardrail", "reasoning", "method", "stack",
                            "style", "decision", "context", "template", "project",
                        ],
                    },
                    "project_id": {"type": "string"},
                    "top_k": {"type": "integer", "default": 5},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="echome_search_summary",
            description=(
                "Return a compact numbered summary index of memories instead of full content. "
                "Use this first for broad or uncertain questions, projects with many memories, "
                "or when you need to choose which memories to read. Then call echome_get_memories with selected UUIDs."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": [
                            "identity", "guardrail", "reasoning", "method", "stack",
                            "style", "decision", "context", "template", "project",
                        ],
                        "description": "Optional memory type filter",
                    },
                    "status": {
                        "type": "string",
                        "enum": ["active", "ai_review", "pending", "deprecated", "archived"],
                        "default": "active",
                        "description": "Memory status filter",
                    },
                    "project_id": {
                        "type": "string",
                        "description": "Optional project ID filter",
                    },
                    "query": {
                        "type": "string",
                        "description": "Optional lightweight title/content/tag filter",
                    },
                    "limit": {
                        "type": "integer",
                        "default": 30,
                        "description": "Number of index entries to return",
                    },
                    "offset": {
                        "type": "integer",
                        "default": 0,
                        "description": "Pagination offset",
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="echome_get_memories",
            description=(
                "Get full content for multiple memories by UUID. "
                "Use after echome_search_summary when only selected entries are relevant."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "memory_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Memory UUIDs selected from echome_search_summary",
                    },
                },
                "required": ["memory_ids"],
            },
        ),
        Tool(
            name="echome_get",
            description="Get a single memory's full content by its UUID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "memory_id": {
                        "type": "string",
                        "description": "UUID of the memory to retrieve",
                    },
                },
                "required": ["memory_id"],
            },
        ),
        Tool(
            name="echome_list_by_type",
            description=(
                "List all memories of a specific type. "
                "Use to browse what the user has stored in a category."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": [
                            "identity", "guardrail", "reasoning", "method", "stack",
                            "style", "decision", "context", "template", "project",
                        ],
                        "description": "Memory type to list",
                    },
                    "status": {
                        "type": "string",
                        "enum": ["active", "ai_review", "pending", "deprecated"],
                        "default": "active",
                        "description": "Filter by status (default: active)",
                    },
                },
                "required": ["type"],
            },
        ),
        Tool(
            name="echome_remember",
            description=(
                "Save a proposed memory to the user's vault in ai_review state. "
                "You may call this proactively when you observe durable user preferences, "
                "project decisions, workflow conventions, repeated corrections, or reusable context. "
                "Do not save secrets, one-off temporary facts, or uncertain guesses. "
                "ai_review memories are immediately searchable by AI, and can later be promoted or archived with `echome review`."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Short, descriptive title",
                    },
                    "content": {
                        "type": "string",
                        "description": "Detailed content of the rule/knowledge/preference",
                    },
                    "type": {
                        "type": "string",
                        "enum": [
                            "identity", "guardrail", "reasoning", "method", "stack",
                            "style", "decision", "context", "template", "project",
                        ],
                        "description": "Memory type",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Relevant tags",
                    },
                    "suggested_layer": {
                        "type": "string",
                        "enum": ["L0", "L1", "L2"],
                        "default": "L2",
                        "description": "Suggested loading layer",
                    },
                    "project": {
                        "type": "string",
                        "description": "项目名称（仅 project 类型需要）",
                    },
                },
                "required": ["title", "content", "type", "tags"],
            },
        ),
        Tool(
            name="memory_remember",
            description=(
                "Alias for echome_remember. Save a proposed memory in ai_review state. "
                "Agents may use this proactively for durable preferences, decisions, conventions, "
                "and reusable context; ai_review memories are searchable immediately and can be curated later."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "content": {"type": "string"},
                    "type": {
                        "type": "string",
                        "enum": [
                            "identity", "guardrail", "reasoning", "method", "stack",
                            "style", "decision", "context", "template", "project",
                        ],
                    },
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "suggested_layer": {"type": "string", "enum": ["L0", "L1", "L2"], "default": "L2"},
                    "project": {"type": "string"},
                },
                "required": ["title", "content", "type", "tags"],
            },
        ),
        Tool(
            name="echome_get_project_context",
            description=(
                "Get the full context for a specific project, "
                "including all memories scoped to it."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "Project ID (e.g. 'qzhqzh/EchoMe')",
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="echome_list_projects",
            description=(
                "列出当前用户的所有项目。"
                "用于查看已有项目，帮助确定 project_id。"
            ),
            inputSchema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
        Tool(
            name="echome_create_project",
            description=(
                "创建新项目。项目名称(name)同时作为唯一标识。"
                "创建 project 类型记忆前，如果项目不存在，需先创建项目。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "项目名称（唯一标识）",
                    },
                    "description": {
                        "type": "string",
                        "description": "项目描述（可选）",
                    },
                    "git_remote": {
                        "type": "string",
                        "description": "Git 远程仓库地址（可选）",
                    },
                },
                "required": ["name"],
            },
        ),
        Tool(
            name="echome_sleep_candidates",
            description=(
                "Fetch all eligible Memory Sleep candidates page by page. "
                "Default statuses are active, ai_review, and pending; deprecated and archived are excluded unless explicitly requested. "
                "Use this before generating a client-side text proposal and JSON sleep plan."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "session_id": {"type": "string"},
                    "scope": {
                        "type": "string",
                        "enum": ["project", "global", "all"],
                        "default": "project",
                    },
                    "status": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": ["active", "ai_review", "pending", "deprecated", "archived"],
                        },
                        "description": "Optional explicit statuses; omit for active, ai_review, pending.",
                    },
                    "page_size": {"type": "integer", "default": 100},
                    "cursor": {"type": "integer"},
                    "include_protected": {"type": "boolean", "default": True},
                },
                "required": [],
            },
        ),
        Tool(
            name="echome_sleep_submit_proposal",
            description=(
                "Submit a client-generated Memory Sleep proposal. "
                "The JSON proposal must follow memory_sleep_plan.v1 and will be validated by Hub before apply."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string"},
                    "json_proposal": {"type": "object"},
                    "text_proposal": {"type": "string"},
                },
                "required": ["session_id", "json_proposal"],
            },
        ),
        Tool(
            name="echome_sleep_apply",
            description=(
                "Apply an approved Memory Sleep proposal. "
                "Only call after the user approves the submitted JSON plan."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string"},
                },
                "required": ["session_id"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Route tool calls to the appropriate handler."""
    try:
        if name in {"echome_search", "memory_search"}:
            result = await echome_search(
                query=arguments["query"],
                type=arguments.get("type"),
                project_id=arguments.get("project_id"),
                top_k=arguments.get("top_k", 5),
            )
        elif name in {"echome_search_summary", "echome_browse_memories"}:
            summary_func = (
                echome_browse_memories if name == "echome_browse_memories" else echome_search_summary
            )
            result = await summary_func(
                type=arguments.get("type"),
                status=arguments.get("status", "active"),
                project_id=arguments.get("project_id"),
                query=arguments.get("query"),
                limit=arguments.get("limit", 30),
                offset=arguments.get("offset", 0),
            )
        elif name == "echome_get_memories":
            result = await echome_get_memories(
                memory_ids=arguments.get("memory_ids", []),
            )
        elif name == "echome_get":
            result = await echome_get(memory_id=arguments["memory_id"])
        elif name == "echome_list_by_type":
            result = await echome_list_by_type(
                type=arguments["type"],
                status=arguments.get("status", "active"),
            )
        elif name in {"echome_remember", "memory_remember"}:
            result = await echome_remember(
                title=arguments["title"],
                content=arguments["content"],
                type=arguments["type"],
                tags=arguments.get("tags", []),
                suggested_layer=arguments.get("suggested_layer", "L2"),
                project=arguments.get("project"),
            )
        elif name == "echome_get_project_context":
            result = await echome_get_project_context(
                project_id=arguments.get("project_id"),
            )
        elif name == "echome_list_projects":
            result = await echome_list_projects()
        elif name == "echome_create_project":
            result = await echome_create_project(
                name=arguments["name"],
                description=arguments.get("description"),
                git_remote=arguments.get("git_remote"),
            )
        elif name == "echome_sleep_candidates":
            result = await echome_sleep_candidates(
                project_id=arguments.get("project_id"),
                session_id=arguments.get("session_id"),
                scope=arguments.get("scope", "project"),
                status=arguments.get("status"),
                page_size=arguments.get("page_size", 100),
                cursor=arguments.get("cursor"),
                include_protected=arguments.get("include_protected", True),
            )
        elif name == "echome_sleep_submit_proposal":
            result = await echome_sleep_submit_proposal(
                session_id=arguments["session_id"],
                json_proposal=arguments["json_proposal"],
                text_proposal=arguments.get("text_proposal"),
            )
        elif name == "echome_sleep_apply":
            result = await echome_sleep_apply(session_id=arguments["session_id"])
        else:
            result = f"Unknown tool: {name}"

        return [TextContent(type="text", text=result)]

    except Exception as e:
        error_msg = f"EchoMe error: {e}"
        return [TextContent(type="text", text=error_msg)]


def run_server(
    use_sse: bool = False,
    transport: str = "stdio",
    host: str = "127.0.0.1",
    port: int = 20003,
) -> None:
    """Run the MCP server."""
    if use_sse or transport == "sse":
        # SSE mode - for remote/multi-client access
        # TODO: Implement SSE transport when needed
        raise NotImplementedError("SSE mode not yet implemented. Use streamable-http or stdio mode.")
    if transport == "streamable-http":
        _run_streamable_http(host=host, port=port)
        return
    if transport != "stdio":
        raise ValueError(f"Unsupported MCP transport: {transport}")

    # stdio mode - default for Claude Code / Codex CLI
    asyncio.run(_run_stdio())


async def _run_stdio() -> None:
    """Run server in stdio mode."""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def _create_streamable_http_app() -> Starlette:
    """Create ASGI app for MCP streamable HTTP transport."""
    session_manager = StreamableHTTPSessionManager(
        app=server,
        json_response=True,
        stateless=False,
    )

    class MCPHTTPApp:
        async def __call__(self, scope, receive, send) -> None:
            await session_manager.handle_request(scope, receive, send)

    handle_mcp = MCPHTTPApp()

    async def health(_request) -> JSONResponse:
        return JSONResponse({"status": "ok", "transport": "streamable-http"})

    @contextlib.asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncIterator[None]:
        async with session_manager.run():
            yield

    return Starlette(
        routes=[
            Route("/health", endpoint=health, methods=["GET"]),
            Route("/mcp", endpoint=handle_mcp, methods=["DELETE", "GET", "POST"]),
            Route("/mcp/", endpoint=handle_mcp, methods=["DELETE", "GET", "POST"]),
        ],
        lifespan=lifespan,
    )


def _run_streamable_http(host: str, port: int) -> None:
    """Run server with MCP streamable HTTP transport."""
    import uvicorn

    uvicorn.run(_create_streamable_http_app(), host=host, port=port)


if __name__ == "__main__":
    run_server()
