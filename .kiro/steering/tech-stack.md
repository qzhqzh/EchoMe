# Tech Stack Context

## Current State

- **Frontend**: Vue 3 + TypeScript + Tailwind CSS + Vite
- **Backend API**: FastAPI (Python 3.11+) + SQLAlchemy async + PostgreSQL + pgvector
- **CLI**: Python (typer + rich + httpx)
- **MCP Server**: Python (mcp SDK)

## Direction (non-binding preferences)

The following are current inclinations, not hard rules. They may evolve.

- **Frontend**: Leaning toward keeping Vue for now (lightweight, sufficient for this scale). If the project grows significantly in UI complexity or needs a larger ecosystem (e.g., mobile via React Native), React is a reasonable migration target.
- **Backend**: Considering Django (DRF) as a future alternative if the project needs:
  - Built-in admin panel
  - More batteries-included ORM features
  - Larger team familiarity
  
  FastAPI is fine for current needs (async, lightweight, fast iteration). No urgency to migrate.

## Guidance for AI

- When writing new code, follow the **current** stack conventions (Vue, FastAPI, SQLAlchemy).
- When discussing architecture or planning, feel free to suggest alternatives — these preferences are soft.
- Do NOT refuse to discuss or prototype in React/Django if asked.
