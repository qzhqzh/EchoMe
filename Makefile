# EchoMe Development Makefile

.PHONY: help setup install hub-up hub-down hub-logs test lint

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

# --- Install (CLI + MCP) ---

install:  ## Install EchoMe CLI + MCP locally (editable)
	pip install -e ".[mcp]"
	@echo ""
	@echo "Done! Run 'echome init' to get started."

install-cli:  ## Install CLI only (without MCP)
	pip install -e .

# --- Hub (Server) ---

hub-up: setup ## Start Hub + Postgres + Redis via Docker Compose
	docker compose up -d --build
	@echo ""
	@echo "Hub starting at http://localhost:8000"
	@echo "Health: curl http://localhost:8000/health"

hub-down:  ## Stop all services
	docker compose down

hub-logs:  ## Follow Hub logs
	docker compose logs -f hub

hub-migrate:  ## Run database migrations inside container
	docker compose exec hub alembic upgrade head

hub-shell:  ## Open shell in Hub container
	docker compose exec hub bash

# --- Testing ---

test:  ## Run all tests
	pytest

lint:  ## Run linter
	ruff check echome/ echome_mcp/ hub/app/
