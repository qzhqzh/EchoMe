"""EchoMe MCP Server - Main server implementation."""

import asyncio
import contextlib
import json
import os
from collections.abc import AsyncIterator
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.types import (
    CallToolResult,
    GetPromptResult,
    Prompt,
    PromptArgument,
    PromptMessage,
    Resource,
    TextContent,
    Tool,
    ToolAnnotations,
)
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from echome_mcp import __version__
from echome_mcp.profiles import CORE_TOOL_NAMES, current_profile
from echome_mcp.runtime import (
    echome_context,
    echome_context_outcome,
    echome_runtime_health,
    error_contract,
)
from echome_mcp.tools.browse import echome_browse_memories, echome_search_summary
from echome_mcp.tools.capabilities import (
    capabilities_json,
    echome_capabilities,
    retrieval_workflow_prompt,
)
from echome_mcp.tools.feedback import echome_memory_feedback, echome_memory_feedback_batch
from echome_mcp.tools.get import echome_get
from echome_mcp.tools.get_many import echome_get_memories
from echome_mcp.tools.graph import (
    echome_memory_explain,
    echome_memory_neighbors,
    echome_temporal_candidates,
)
from echome_mcp.tools.list_by_type import echome_list_by_type
from echome_mcp.tools.project import (
    echome_create_project,
    echome_list_projects,
    echome_update_project_git_identity,
)
from echome_mcp.tools.project_context import echome_get_project_context
from echome_mcp.tools.project_knowledge import (
    echome_constraint_propose,
    echome_project_context,
    echome_project_event_append,
    echome_project_impact,
    echome_project_index,
    echome_project_preflight,
    echome_reflect_prepare,
    echome_reflect_submit,
)
from echome_mcp.tools.remember import echome_remember
from echome_mcp.tools.search import echome_search
from echome_mcp.tools.sleep import (
    echome_sleep_apply,
    echome_sleep_candidates,
    echome_sleep_submit_proposal,
)

# Create MCP server instance
server = Server("echome", version=__version__)

PROJECT_CONTEXT_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "project": {"type": "object"},
        "task": {"type": "string"},
        "mode": {"type": "string"},
        "must_include": {"type": "array"},
        "constraints": {"type": "array"},
        "memories": {"type": "array"},
        "artifacts": {"type": "array"},
        "evidence": {"type": "array"},
        "conflicts": {"type": "array"},
        "stale_warnings": {"type": "array"},
        "unknowns": {"type": "array"},
        "token_budget": {"type": "integer"},
        "token_used": {"type": "integer"},
        "retrieval_trace": {"type": "object"},
    },
    "required": ["project", "task", "constraints", "memories", "evidence"],
    "additionalProperties": True,
}

PREFLIGHT_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "project_id": {"type": "string"},
        "task": {"type": "string"},
        "read_only": {"type": "boolean"},
        "decision": {"type": "string"},
        "warnings": {"type": "array"},
        "requirements": {"type": "array"},
        "unknowns": {"type": "array"},
    },
    "required": ["project_id", "task", "read_only", "decision", "warnings", "unknowns"],
    "additionalProperties": True,
}

PROJECT_GIT_IDENTITY_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "schema_version": {"const": "echome.project-git-identity.v1"},
        "status": {
            "type": "string",
            "enum": ["confirmation_required", "updated", "unchanged"],
        },
        "requires_confirmation": {"type": "boolean"},
        "confirmation_token": {"type": ["string", "null"]},
        "project": {"type": "object"},
        "normalized_git_remote": {"type": ["string", "null"]},
        "changes": {"type": "object"},
    },
    "required": [
        "schema_version",
        "status",
        "requires_confirmation",
        "confirmation_token",
        "project",
        "changes",
    ],
    "additionalProperties": True,
}

ERROR_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "schema_version": {"const": "echome.error.v1"},
        "error": {"type": "object"},
    },
    "required": ["schema_version", "error"],
    "additionalProperties": True,
}


def _with_error_output(success_schema: dict[str, Any]) -> dict[str, Any]:
    """Allow structured MCP failures without violating a strict success schema."""
    return {
        "type": "object",
        "anyOf": [success_schema, ERROR_OUTPUT_SCHEMA],
    }


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List all available EchoMe tools."""
    tools = [
        Tool(
            name="echome_capabilities",
            description=(
                "Describe all EchoMe MCP capabilities, tool groups, and recommended workflows. "
                "Use this first when an agent or user is unsure how to use EchoMe MCP. "
                "This is read-only and helps decide when to call search, graph explanation, write, or sleep tools."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "format": {
                        "type": "string",
                        "enum": ["json", "prompt"],
                        "default": "json",
                        "description": "Return structured JSON or a concise retrieval workflow prompt.",
                    },
                },
                "required": [],
            },
        ),
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
                            "identity",
                            "guardrail",
                            "reasoning",
                            "method",
                            "stack",
                            "style",
                            "decision",
                            "context",
                            "template",
                            "project",
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
                            "identity",
                            "guardrail",
                            "reasoning",
                            "method",
                            "stack",
                            "style",
                            "decision",
                            "context",
                            "template",
                            "project",
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
                            "identity",
                            "guardrail",
                            "reasoning",
                            "method",
                            "stack",
                            "style",
                            "decision",
                            "context",
                            "template",
                            "project",
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
            name="echome_memory_explain",
            description=(
                "Explain one memory with graph provenance, supersession links, related memories, "
                "and temporal reliability assessment. Use after echome_search/echome_search_summary "
                "or echome_get when you need to know whether a memory is stable, time-sensitive, "
                "superseded, or connected to archived source memories. This complements normal search; "
                "it does not replace search."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "memory_id": {
                        "type": "string",
                        "description": "UUID of the memory to explain",
                    },
                    "include_inactive": {
                        "type": "boolean",
                        "default": True,
                        "description": "Include archived/deprecated neighbors for provenance.",
                    },
                },
                "required": ["memory_id"],
            },
        ),
        Tool(
            name="echome_memory_neighbors",
            description=(
                "Fetch an AI-readable local memory graph around one memory. "
                "Use this to expand context after a search result, follow derived_from/superseded_by "
                "relationships, inspect neighboring memories, or build a stable project context. "
                "For provenance, keep include_inactive=true so archived source memories are visible."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "memory_id": {
                        "type": "string",
                        "description": "Center memory UUID",
                    },
                    "depth": {
                        "type": "integer",
                        "default": 1,
                        "minimum": 1,
                        "maximum": 3,
                    },
                    "include_inactive": {
                        "type": "boolean",
                        "default": True,
                    },
                    "limit": {
                        "type": "integer",
                        "default": 200,
                        "minimum": 1,
                        "maximum": 500,
                    },
                },
                "required": ["memory_id"],
            },
        ),
        Tool(
            name="echome_temporal_candidates",
            description=(
                "List memories that may need temporal review without changing memory state. "
                "This is evidence-based: long inactivity alone is not treated as stale, and dormant "
                "projects are classified separately from truly time-sensitive memories. Use this before "
                "Memory Sleep or when auditing outdated project assumptions."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "Optional project ID filter",
                    },
                    "include_inactive": {
                        "type": "boolean",
                        "default": False,
                    },
                    "classifications": {
                        "type": "string",
                        "description": "Optional comma-separated classes, e.g. needs_verification,dormant_project",
                    },
                    "limit": {
                        "type": "integer",
                        "default": 100,
                        "minimum": 1,
                        "maximum": 500,
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="echome_memory_feedback",
            description=(
                "Record a lightweight feedback signal after a memory was used. "
                "Use when the user or agent can judge that a memory was helpful, important, "
                "irrelevant, outdated, conflicting, or wrong. This appends feedback only; "
                "it does not change the memory status."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "memory_id": {"type": "string", "description": "Memory UUID"},
                    "rating": {
                        "type": "string",
                        "enum": [
                            "helpful",
                            "irrelevant",
                            "outdated",
                            "conflicting",
                            "wrong",
                            "important",
                        ],
                    },
                    "note": {
                        "type": "string",
                        "description": "Optional short explanation or user correction.",
                    },
                    "task_context": {
                        "type": "string",
                        "description": "Optional brief description of the task where the memory was used.",
                    },
                    "used_by": {
                        "type": "string",
                        "enum": ["ai", "user", "system"],
                        "default": "ai",
                    },
                    "confidence": {
                        "type": "string",
                        "enum": ["low", "medium", "high"],
                        "default": "medium",
                    },
                },
                "required": ["memory_id", "rating"],
            },
        ),
        Tool(
            name="echome_memory_feedback_batch",
            description=(
                "Record feedback for several memories after a task. "
                "Use at task end when multiple retrieved memories were clearly helpful, irrelevant, "
                "outdated, conflicting, wrong, or important. This appends feedback only."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 50,
                        "items": {
                            "type": "object",
                            "properties": {
                                "memory_id": {"type": "string"},
                                "rating": {
                                    "type": "string",
                                    "enum": [
                                        "helpful",
                                        "irrelevant",
                                        "outdated",
                                        "conflicting",
                                        "wrong",
                                        "important",
                                    ],
                                },
                                "note": {"type": "string"},
                                "task_context": {"type": "string"},
                                "used_by": {
                                    "type": "string",
                                    "enum": ["ai", "user", "system"],
                                    "default": "ai",
                                },
                                "confidence": {
                                    "type": "string",
                                    "enum": ["low", "medium", "high"],
                                    "default": "medium",
                                },
                            },
                            "required": ["memory_id", "rating"],
                        },
                    },
                },
                "required": ["items"],
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
                            "identity",
                            "guardrail",
                            "reasoning",
                            "method",
                            "stack",
                            "style",
                            "decision",
                            "context",
                            "template",
                            "project",
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
                            "identity",
                            "guardrail",
                            "reasoning",
                            "method",
                            "stack",
                            "style",
                            "decision",
                            "context",
                            "template",
                            "project",
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
                            "identity",
                            "guardrail",
                            "reasoning",
                            "method",
                            "stack",
                            "style",
                            "decision",
                            "context",
                            "template",
                            "project",
                        ],
                    },
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "suggested_layer": {
                        "type": "string",
                        "enum": ["L0", "L1", "L2"],
                        "default": "L2",
                    },
                    "project": {"type": "string"},
                },
                "required": ["title", "content", "type", "tags"],
            },
        ),
        Tool(
            name="echome_context",
            description=(
                "Default EchoMe entry for any task. Automatically routes to personal memory or canonical "
                "project context, combines project preflight when applicable, and returns evidence, conflicts, "
                "unknowns, answerability, runtime metadata, and an explicit read-only cache fallback."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "task": {"type": "string"},
                    "project_hint": {
                        "type": "string",
                        "description": "Optional project ID, alias, Git remote, or path. The current Git remote is inferred when omitted.",
                    },
                    "project_hints": {
                        "type": "array",
                        "items": {"type": "string", "minLength": 1, "maxLength": 2048},
                        "maxItems": 10,
                        "description": "Optional additional identity signals. When omitted, MCP sends every available local Git remote and repository-root hint.",
                    },
                    "changed_paths": {"type": "array", "items": {"type": "string"}},
                    "mode": {
                        "type": "string",
                        "enum": ["auto", "personal", "project", "impact", "temporal"],
                        "default": "auto",
                    },
                    "token_budget": {
                        "type": "integer",
                        "minimum": 256,
                        "maximum": 50000,
                        "default": 6000,
                    },
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
                    "as_of": {"type": "string", "format": "date-time"},
                    "valid_at": {"type": "string", "format": "date-time"},
                    "policy_mode": {
                        "type": "string",
                        "enum": ["off", "shadow", "enforce"],
                        "default": "shadow",
                        "description": "Attach reliability decisions in shadow mode by default; enforce only works when the Hub feature flag is enabled.",
                    },
                    "client": {"type": "string"},
                    "client_version": {"type": "string"},
                },
                "required": ["task"],
            },
            outputSchema={"type": "object", "additionalProperties": True},
            annotations=ToolAnnotations(
                readOnlyHint=False,
                destructiveHint=False,
                idempotentHint=False,
                openWorldHint=False,
            ),
        ),
        Tool(
            name="echome_runtime_health",
            description=(
                "Diagnose the MCP package, authenticated Hub, database, migration revision, embedding service, "
                "feature flags, profile, and read-only context cache. Optionally include the derived context "
                "policy readiness gate before considering an enforce canary."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "include_policy_readiness": {
                        "type": "boolean",
                        "default": False,
                    },
                    "project_id": {"type": "string"},
                    "window_days": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 365,
                        "default": 30,
                    },
                },
            },
            outputSchema={"type": "object", "additionalProperties": True},
            annotations=ToolAnnotations(
                readOnlyHint=True,
                destructiveHint=False,
                idempotentHint=True,
                openWorldHint=False,
            ),
        ),
        Tool(
            name="echome_context_outcome",
            description=(
                "Append an explicit, idempotent outcome for a completed non-shadow echome_context run. "
                "Use success/partial/failed only when task evidence exists; use corrected with a note. "
                "Do not infer failure merely because no outcome was reported."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "context_run_id": {"type": "string", "format": "uuid"},
                    "outcome": {
                        "type": "string",
                        "enum": ["success", "partial", "failed", "corrected", "no_signal"],
                    },
                    "policy_effect": {
                        "type": "string",
                        "enum": ["helpful", "neutral", "harmful", "uncertain"],
                        "description": "Optional explicit evidence about the observed policy intervention. Harmful requires a note.",
                    },
                    "idempotency_key": {"type": "string", "minLength": 1, "maxLength": 128},
                    "reported_by": {
                        "type": "string",
                        "enum": ["user", "ai", "system"],
                        "default": "ai",
                    },
                    "source": {
                        "type": "string",
                        "enum": ["mcp", "web", "api", "ci"],
                        "default": "mcp",
                    },
                    "project_event_id": {"type": "string", "format": "uuid"},
                    "note": {"type": "string", "maxLength": 2000},
                },
                "required": ["context_run_id", "outcome", "idempotency_key"],
            },
            outputSchema={"type": "object", "additionalProperties": True},
            annotations=ToolAnnotations(
                readOnlyHint=False,
                destructiveHint=False,
                idempotentHint=True,
                openWorldHint=False,
            ),
        ),
        Tool(
            name="echome_project_context",
            description=(
                "Default entry point for project implementation work. Returns a task-aware context pack "
                "combining confirmed/proposed constraints, artifact evidence, and existing scoped memories. "
                "Use this instead of guessing whether memory search or graph search is needed."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string", "description": "EchoMe project ID"},
                    "task": {"type": "string", "description": "Current task or question"},
                    "changed_paths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional local paths involved in the task",
                    },
                    "limit": {"type": "integer", "default": 20, "minimum": 1, "maximum": 100},
                    "mode": {
                        "type": "string",
                        "enum": ["local", "overview", "impact"],
                        "default": "local",
                    },
                    "token_budget": {
                        "type": "integer",
                        "default": 6000,
                        "minimum": 256,
                        "maximum": 50000,
                    },
                    "as_of": {"type": "string", "format": "date-time"},
                    "valid_at": {"type": "string", "format": "date-time"},
                    "record_run": {"type": "boolean", "default": True},
                    "shadow": {"type": "boolean", "default": False},
                    "policy_mode": {
                        "type": "string",
                        "enum": ["off", "shadow", "enforce"],
                        "default": "shadow",
                        "description": "Attach reliability and intervention decisions without mutating source memories or constraints.",
                    },
                },
                "required": ["project_id", "task"],
            },
            outputSchema=_with_error_output(PROJECT_CONTEXT_OUTPUT_SCHEMA),
            annotations=ToolAnnotations(
                readOnlyHint=False,
                destructiveHint=False,
                idempotentHint=False,
                openWorldHint=False,
            ),
        ),
        Tool(
            name="echome_reflect_prepare",
            description=(
                "Prepare a read-only evidence pack for a project summary or mental model. Use when "
                "durable cross-source synthesis would improve future work; the response includes every "
                "allowed source ID and a server-owned freshness fingerprint for submit."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "query": {"type": "string", "minLength": 1},
                    "changed_paths": {"type": "array", "items": {"type": "string"}},
                    "limit": {"type": "integer", "default": 30, "minimum": 1, "maximum": 100},
                    "token_budget": {
                        "type": "integer",
                        "default": 12000,
                        "minimum": 512,
                        "maximum": 50000,
                    },
                    "supersedes_id": {"type": "string", "format": "uuid"},
                },
                "required": ["project_id", "query"],
            },
            outputSchema={"type": "object", "additionalProperties": True},
            annotations=ToolAnnotations(
                readOnlyHint=True,
                destructiveHint=False,
                idempotentHint=True,
                openWorldHint=False,
            ),
        ),
        Tool(
            name="echome_reflect_submit",
            description=(
                "Submit a client-generated project reflection after echome_reflect_prepare. Every claim "
                "must cite prepared memory, constraint, artifact, or event IDs; the Hub rejects stale "
                "fingerprints and creates only a derived view without rewriting source facts."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "kind": {
                        "type": "string",
                        "enum": ["summary", "mental_model", "community"],
                        "default": "mental_model",
                    },
                    "query": {"type": "string", "minLength": 1},
                    "claims": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 50,
                        "items": {
                            "type": "object",
                            "properties": {
                                "statement": {"type": "string", "minLength": 1},
                                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                                "evidence_refs": {
                                    "type": "array",
                                    "minItems": 1,
                                    "maxItems": 20,
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "target_type": {
                                                "type": "string",
                                                "enum": [
                                                    "memory",
                                                    "constraint",
                                                    "artifact",
                                                    "event",
                                                ],
                                            },
                                            "target_id": {"type": "string", "format": "uuid"},
                                            "relation": {
                                                "type": "string",
                                                "enum": ["supports", "contradicts", "context"],
                                                "default": "supports",
                                            },
                                        },
                                        "required": ["target_type", "target_id"],
                                    },
                                },
                            },
                            "required": ["statement", "confidence", "evidence_refs"],
                        },
                    },
                    "source_watermark": {"type": "object"},
                    "idempotency_key": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 128,
                    },
                    "supersedes_id": {"type": "string", "format": "uuid"},
                },
                "required": [
                    "project_id",
                    "query",
                    "claims",
                    "source_watermark",
                    "idempotency_key",
                ],
            },
            outputSchema={"type": "object", "additionalProperties": True},
            annotations=ToolAnnotations(
                readOnlyHint=False,
                destructiveHint=False,
                idempotentHint=True,
                openWorldHint=False,
            ),
        ),
        Tool(
            name="echome_project_impact",
            description=(
                "Analyze how a requirement, architecture, API, code, or test change propagates through "
                "the project constraint graph. Returns affected constraints and source evidence with reasons."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "change": {"type": "string", "description": "Proposed change description"},
                    "changed_paths": {"type": "array", "items": {"type": "string"}},
                    "constraint_ids": {"type": "array", "items": {"type": "string"}},
                    "depth": {"type": "integer", "default": 2, "minimum": 0, "maximum": 4},
                    "limit": {"type": "integer", "default": 20, "minimum": 1, "maximum": 100},
                },
                "required": ["project_id", "change"],
            },
            outputSchema={"type": "object", "additionalProperties": True},
            annotations=ToolAnnotations(
                readOnlyHint=True,
                destructiveHint=False,
                idempotentHint=True,
                openWorldHint=False,
            ),
        ),
        Tool(
            name="echome_project_index",
            description=(
                "Synchronize local project artifacts with EchoMe. First sends only a SHA-256 manifest, "
                "then uploads changed content when dry_run=false. Excludes data, .git, virtualenv, build, "
                "cache, and dependency directories."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "root_path": {"type": "string", "description": "Absolute local project root"},
                    "dry_run": {"type": "boolean", "default": True},
                    "max_files": {"type": "integer", "default": 500, "minimum": 1, "maximum": 5000},
                },
                "required": ["project_id", "root_path"],
            },
        ),
        Tool(
            name="echome_project_preflight",
            description=(
                "Run a read-only check before editing, testing, committing, or deploying. Returns only "
                "evidence-backed historical warnings, relevant constraints, and explicit unknowns."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "task": {"type": "string"},
                    "changed_paths": {"type": "array", "items": {"type": "string"}},
                    "planned_actions": {"type": "array", "items": {"type": "string"}},
                    "limit": {"type": "integer", "default": 20, "minimum": 1, "maximum": 100},
                },
                "required": ["project_id", "task"],
            },
            outputSchema=_with_error_output(PREFLIGHT_OUTPUT_SCHEMA),
            annotations=ToolAnnotations(
                readOnlyHint=True,
                destructiveHint=False,
                idempotentHint=True,
                openWorldHint=False,
            ),
        ),
        Tool(
            name="echome_project_event_append",
            description=(
                "Append an issue, attempt, failure, fix, decision, test result, deploy, or note as a "
                "project event. Events are append-only and never become active constraints automatically."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "event_type": {
                        "type": "string",
                        "enum": [
                            "issue",
                            "attempt",
                            "failure",
                            "fix",
                            "decision",
                            "test_result",
                            "deploy",
                            "note",
                        ],
                    },
                    "title": {"type": "string"},
                    "content": {"type": "string"},
                    "occurred_at": {"type": "string", "format": "date-time"},
                    "source": {"type": "string", "default": "ai_client"},
                    "source_ref": {"type": "string"},
                    "metadata": {"type": "object"},
                    "idempotency_key": {"type": "string"},
                    "links": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "target_type": {
                                    "type": "string",
                                    "enum": ["memory", "constraint", "artifact", "event"],
                                },
                                "target_id": {"type": "string"},
                                "relation": {"type": "string"},
                                "metadata": {"type": "object"},
                            },
                            "required": ["target_type", "target_id", "relation"],
                        },
                    },
                },
                "required": ["project_id", "event_type", "title", "content"],
            },
            outputSchema={"type": "object", "additionalProperties": True},
            annotations=ToolAnnotations(
                readOnlyHint=False,
                destructiveHint=False,
                idempotentHint=False,
                openWorldHint=False,
            ),
        ),
        Tool(
            name="echome_constraint_propose",
            description=(
                "Record a project-stability constraint inferred from requirements, code, tests, or decisions. "
                "The constraint is stored as proposed and does not modify personal memories or AI behavior rules."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "title": {"type": "string"},
                    "statement": {"type": "string"},
                    "rationale": {"type": "string"},
                    "kind": {
                        "type": "string",
                        "enum": [
                            "functional",
                            "nonfunctional",
                            "architecture",
                            "process",
                            "security",
                            "data",
                            "compatibility",
                        ],
                        "default": "architecture",
                    },
                    "stability": {
                        "type": "string",
                        "enum": ["invariant", "evolving", "temporary"],
                        "default": "evolving",
                    },
                    "confidence": {"type": "number", "default": 0.7, "minimum": 0, "maximum": 1},
                    "tags": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["project_id", "title", "statement"],
            },
        ),
        Tool(
            name="echome_get_project_context",
            description=(
                "Get the full context for a specific project, including all memories scoped to it."
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
            description=("列出当前用户的所有项目。用于查看已有项目，帮助确定 project_id。"),
            inputSchema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
        Tool(
            name="echome_create_project",
            description=(
                "确认项目确实不存在后创建 canonical project。"
                "只可在用户明确确认新建后调用；工具会先做候选发现，避免重复项目。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "项目显示名称",
                    },
                    "project_id": {
                        "type": "string",
                        "description": "Canonical project ID；未提供时沿用 name",
                    },
                    "description": {
                        "type": "string",
                        "description": "项目描述（可选）",
                    },
                    "git_remote": {
                        "type": "string",
                        "description": "Git 远程仓库地址（可选）",
                    },
                    "kind": {
                        "type": "string",
                        "enum": ["repository", "workspace"],
                        "default": "repository",
                    },
                    "path_patterns": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "用于后续确定性识别的路径模式",
                    },
                    "confirmed_new_project": {
                        "type": "boolean",
                        "default": False,
                        "description": "仅当用户明确确认这是新项目时设为 true；否则不会创建",
                    },
                    "confirmed_distinct_project": {
                        "type": "boolean",
                        "default": False,
                        "description": "仅当用户已确认所有候选都是其他项目时设为 true",
                    },
                },
                "required": ["name"],
            },
        ),
        Tool(
            name="echome_update_project_git_identity",
            description=(
                "为既有 canonical project 预览或更新 Git remote/alias。"
                "首次调用保持 confirmed=false；只有用户确认候选确为同一仓库后才设为 true。"
                "SSH、SCP 风格 SSH 与 HTTPS 使用同一规范化身份，跨项目冲突会被拒绝。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "已解析并由用户确认的 canonical project ID",
                    },
                    "git_remote": {
                        "type": "string",
                        "description": "要设置为项目主 remote 的地址（可选）",
                    },
                    "git_remote_aliases": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                        "maxItems": 10,
                        "description": "要补充并激活的额外 Git remote；替换主 remote 后仍需兼容旧地址时应显式包含旧值",
                    },
                    "confirmed": {
                        "type": "boolean",
                        "default": False,
                        "description": "仅在用户确认预览内容且候选是同一仓库后设为 true",
                    },
                    "confirmation_token": {
                        "type": "string",
                        "description": "confirmed=true 时必须回传最近一次预览返回的 token",
                    },
                },
                "required": ["project_id"],
                "anyOf": [
                    {"required": ["git_remote"]},
                    {"required": ["git_remote_aliases"]},
                ],
            },
            outputSchema=_with_error_output(PROJECT_GIT_IDENTITY_OUTPUT_SCHEMA),
            annotations=ToolAnnotations(
                readOnlyHint=False,
                destructiveHint=True,
                idempotentHint=True,
                openWorldHint=False,
            ),
        ),
        Tool(
            name="echome_sleep_candidates",
            description=(
                "Fetch all eligible Memory Sleep candidates page by page. "
                "Statuses are active, ai_review, and pending; deprecated and archived are never Sleep candidates. "
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
                            "enum": ["active", "ai_review", "pending"],
                        },
                        "description": "Optional explicit statuses; omit for active, ai_review, pending.",
                    },
                    "page_size": {"type": "integer", "default": 100},
                    "cursor": {"type": "integer"},
                    "include_protected": {"type": "boolean", "default": True},
                    "plan_schema_version": {
                        "type": "string",
                        "enum": ["memory_sleep_plan.v1", "memory_sleep_plan.v2"],
                        "default": "memory_sleep_plan.v2",
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="echome_sleep_submit_proposal",
            description=(
                "Submit a client-generated Memory Sleep proposal. "
                "memory_sleep_plan.v2 adds source preconditions and before/after replay gates; v1 remains supported. "
                "The Hub replaces client-supplied simulation output and validates again before apply."
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
    if current_profile() == "core":
        return [tool for tool in tools if tool.name in CORE_TOOL_NAMES]
    return tools


@server.list_prompts()
async def list_prompts() -> list[Prompt]:
    """List reusable EchoMe prompts for clients that support MCP prompts."""
    return [
        Prompt(
            name="echome_retrieval_workflow",
            description=(
                "Standard workflow for using EchoMe memory retrieval, graph explanation, "
                "and durable memory writing."
            ),
            arguments=[
                PromptArgument(
                    name="project_id",
                    description="Optional project identifier to bias retrieval instructions.",
                    required=False,
                )
            ],
        ),
    ]


@server.get_prompt()
async def get_prompt(name: str, arguments: dict[str, str] | None) -> GetPromptResult:
    """Return reusable EchoMe prompt content."""
    if name != "echome_retrieval_workflow":
        raise ValueError(f"Unknown prompt: {name}")
    project_id = (arguments or {}).get("project_id")
    return GetPromptResult(
        description="EchoMe summary-first retrieval workflow with graph reliability checks.",
        messages=[
            PromptMessage(
                role="user",
                content=TextContent(
                    type="text",
                    text=retrieval_workflow_prompt(project_id=project_id),
                ),
            )
        ],
    )


@server.list_resources()
async def list_resources() -> list[Resource]:
    """List EchoMe MCP resources for clients that support MCP resources."""
    return [
        Resource(
            uri="echome://capabilities",
            name="EchoMe MCP capabilities",
            description="Tool groups, recommended workflows, and safety rules for EchoMe MCP.",
            mimeType="application/json",
        )
    ]


@server.read_resource()
async def read_resource(uri: Any) -> str:
    """Read EchoMe MCP resource content."""
    if str(uri) != "echome://capabilities":
        raise ValueError(f"Unknown resource: {uri}")
    return capabilities_json()


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> CallToolResult:
    """Route tool calls to the appropriate handler."""
    try:
        if name == "echome_capabilities":
            result = await echome_capabilities(format=arguments.get("format", "json"))
        elif name == "echome_context":
            result = await echome_context(
                task=arguments["task"],
                project_hint=arguments.get("project_hint"),
                project_hints=arguments.get("project_hints"),
                changed_paths=arguments.get("changed_paths"),
                mode=arguments.get("mode", "auto"),
                token_budget=arguments.get("token_budget", 6000),
                limit=arguments.get("limit", 20),
                as_of=arguments.get("as_of"),
                valid_at=arguments.get("valid_at"),
                policy_mode=arguments.get("policy_mode", "shadow"),
                client=arguments.get("client"),
                client_version=arguments.get("client_version"),
            )
        elif name == "echome_runtime_health":
            result = await echome_runtime_health(
                include_policy_readiness=arguments.get("include_policy_readiness", False),
                project_id=arguments.get("project_id"),
                window_days=arguments.get("window_days", 30),
            )
        elif name == "echome_context_outcome":
            result = await echome_context_outcome(
                context_run_id=arguments["context_run_id"],
                outcome=arguments["outcome"],
                idempotency_key=arguments["idempotency_key"],
                policy_effect=arguments.get("policy_effect"),
                reported_by=arguments.get("reported_by", "ai"),
                source=arguments.get("source", "mcp"),
                project_event_id=arguments.get("project_event_id"),
                note=arguments.get("note"),
            )
        elif name in {"echome_search", "memory_search"}:
            result = await echome_search(
                query=arguments["query"],
                type=arguments.get("type"),
                project_id=arguments.get("project_id"),
                top_k=arguments.get("top_k", 5),
            )
        elif name in {"echome_search_summary", "echome_browse_memories"}:
            summary_func = (
                echome_browse_memories
                if name == "echome_browse_memories"
                else echome_search_summary
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
        elif name == "echome_memory_explain":
            result = await echome_memory_explain(
                memory_id=arguments["memory_id"],
                include_inactive=arguments.get("include_inactive", True),
            )
        elif name == "echome_memory_neighbors":
            result = await echome_memory_neighbors(
                memory_id=arguments["memory_id"],
                depth=arguments.get("depth", 1),
                include_inactive=arguments.get("include_inactive", True),
                limit=arguments.get("limit", 200),
            )
        elif name == "echome_temporal_candidates":
            result = await echome_temporal_candidates(
                project_id=arguments.get("project_id"),
                include_inactive=arguments.get("include_inactive", False),
                classifications=arguments.get("classifications"),
                limit=arguments.get("limit", 100),
            )
        elif name == "echome_memory_feedback":
            result = await echome_memory_feedback(
                memory_id=arguments["memory_id"],
                rating=arguments["rating"],
                note=arguments.get("note"),
                task_context=arguments.get("task_context"),
                used_by=arguments.get("used_by", "ai"),
                confidence=arguments.get("confidence", "medium"),
            )
        elif name == "echome_memory_feedback_batch":
            result = await echome_memory_feedback_batch(items=arguments.get("items", []))
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
        elif name == "echome_project_context":
            result = await echome_project_context(
                project_id=arguments["project_id"],
                task=arguments["task"],
                changed_paths=arguments.get("changed_paths"),
                limit=arguments.get("limit", 20),
                mode=arguments.get("mode", "local"),
                token_budget=arguments.get("token_budget", 6000),
                as_of=arguments.get("as_of"),
                valid_at=arguments.get("valid_at"),
                record_run=arguments.get("record_run", True),
                shadow=arguments.get("shadow", False),
                policy_mode=arguments.get("policy_mode", "shadow"),
            )
        elif name == "echome_reflect_prepare":
            result = await echome_reflect_prepare(
                project_id=arguments["project_id"],
                query=arguments["query"],
                changed_paths=arguments.get("changed_paths"),
                limit=arguments.get("limit", 30),
                token_budget=arguments.get("token_budget", 12000),
                supersedes_id=arguments.get("supersedes_id"),
            )
        elif name == "echome_reflect_submit":
            result = await echome_reflect_submit(
                project_id=arguments["project_id"],
                query=arguments["query"],
                claims=arguments["claims"],
                source_watermark=arguments["source_watermark"],
                idempotency_key=arguments["idempotency_key"],
                kind=arguments.get("kind", "mental_model"),
                supersedes_id=arguments.get("supersedes_id"),
            )
        elif name == "echome_project_impact":
            result = await echome_project_impact(
                project_id=arguments["project_id"],
                change=arguments["change"],
                changed_paths=arguments.get("changed_paths"),
                constraint_ids=arguments.get("constraint_ids"),
                depth=arguments.get("depth", 2),
                limit=arguments.get("limit", 20),
            )
        elif name == "echome_project_index":
            result = await echome_project_index(
                project_id=arguments["project_id"],
                root_path=arguments["root_path"],
                dry_run=arguments.get("dry_run", True),
                max_files=arguments.get("max_files", 500),
            )
        elif name == "echome_project_preflight":
            result = await echome_project_preflight(
                project_id=arguments["project_id"],
                task=arguments["task"],
                changed_paths=arguments.get("changed_paths"),
                planned_actions=arguments.get("planned_actions"),
                limit=arguments.get("limit", 20),
            )
        elif name == "echome_project_event_append":
            result = await echome_project_event_append(
                project_id=arguments["project_id"],
                event_type=arguments["event_type"],
                title=arguments["title"],
                content=arguments["content"],
                occurred_at=arguments.get("occurred_at"),
                source=arguments.get("source", "ai_client"),
                source_ref=arguments.get("source_ref"),
                metadata=arguments.get("metadata"),
                idempotency_key=arguments.get("idempotency_key"),
                links=arguments.get("links"),
            )
        elif name == "echome_constraint_propose":
            result = await echome_constraint_propose(
                project_id=arguments["project_id"],
                title=arguments["title"],
                statement=arguments["statement"],
                rationale=arguments.get("rationale"),
                kind=arguments.get("kind", "architecture"),
                stability=arguments.get("stability", "evolving"),
                confidence=arguments.get("confidence", 0.7),
                tags=arguments.get("tags"),
            )
        elif name == "echome_list_projects":
            result = await echome_list_projects()
        elif name == "echome_create_project":
            result = await echome_create_project(
                name=arguments["name"],
                project_id=arguments.get("project_id"),
                description=arguments.get("description"),
                git_remote=arguments.get("git_remote"),
                kind=arguments.get("kind", "repository"),
                path_patterns=arguments.get("path_patterns"),
                confirmed_new_project=arguments.get("confirmed_new_project", False),
                confirmed_distinct_project=arguments.get("confirmed_distinct_project", False),
            )
        elif name == "echome_update_project_git_identity":
            result = await echome_update_project_git_identity(
                project_id=arguments["project_id"],
                git_remote=arguments.get("git_remote"),
                git_remote_aliases=arguments.get("git_remote_aliases"),
                confirmed=arguments.get("confirmed", False),
                confirmation_token=arguments.get("confirmation_token"),
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
                plan_schema_version=arguments.get("plan_schema_version", "memory_sleep_plan.v2"),
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
            raise ValueError(f"Unknown tool: {name}")

        structured = None
        try:
            parsed = json.loads(result)
            if isinstance(parsed, dict):
                structured = parsed
        except (json.JSONDecodeError, TypeError):
            pass
        error_prefixes = (
            "Error",
            "EchoMe error",
            "Project root",
            "Project not found",
            "Project path_patterns",
            "Root path",
        )
        is_error = result.startswith(error_prefixes) or bool(
            isinstance(structured, dict) and structured.get("error")
        )
        if is_error and structured is None:
            structured = error_contract(RuntimeError(result))
        return CallToolResult(
            content=[TextContent(type="text", text=result)],
            structuredContent=structured,
            isError=is_error,
        )

    except Exception as e:
        error = error_contract(e)
        error_msg = json.dumps(error, ensure_ascii=False, indent=2)
        return CallToolResult(
            content=[TextContent(type="text", text=error_msg)],
            structuredContent=error,
            isError=True,
        )


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
        raise NotImplementedError(
            "SSE mode not yet implemented. Use streamable-http or stdio mode."
        )
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
        return JSONResponse(
            {
                "status": "ok",
                "transport": "streamable-http",
                "service": "echome",
                "service_version": __version__,
                "context_schema_version": "echome.context.v1",
                "error_schema_version": "echome.error.v1",
                "profile": current_profile(),
            }
        )

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
