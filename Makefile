# EchoMe Development Makefile

.PHONY: help setup hub-up hub-down hub-logs cli-install mcp-install test lint

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# --- Setup ---

setup: ## First-time setup: create .env from example
	@if [ ! -f hub/.env ]; then \
		cp hub/.env.example hub/.env; \
		echo "Created hub/.env - please edit ECHOME_AUTH_TOKEN!"; \
	else \
		echo "hub/.env already exists"; \
	fi

# --- Hub (Server) ---

hub-up: setup ## Start Hub + Postgres + Redis via Docker Compose
	docker compose up -d --build
	@echo ""
	@echo "Hub is starting at http://localhost:8000"
	@echo "Health check: curl http://localhost:8000/health"

hub-down:  ## Stop all services
	docker compose down

hub-logs:  ## Follow Hub logs
	docker compose logs -f hub

hub-migrate:  ## Run database migrations inside container
	docker compose exec hub alembic upgrade head

hub-shell:  ## Open shell in Hub container
	docker compose exec hub bash

# --- CLI ---

cli-install:  ## Install CLI locally (editable)
	cd cli && pip install -e .

# --- MCP Server ---

mcp-install:  ## Install MCP server locally (editable)
	cd mcp_server && pip install -e .

# --- All local ---

install: cli-install mcp-install  ## Install both CLI and MCP server locally
	@echo "Done! Run 'echome init' to get started."

# --- Testing ---

test:  ## Run all tests
	cd hub && pytest
	cd cli && pytest
	cd mcp_server && pytest

lint:  ## Run linter
	cd hub && ruff check .
	cd cli && ruff check .
	cd mcp_server && ruff check .
