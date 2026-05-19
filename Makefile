SHELL := /bin/bash
.DEFAULT_GOAL := help

COMPOSE        ?= docker compose
PROJECT        ?= cpa
PY             ?= uv run
WEB            ?= pnpm -C web

.PHONY: help
help: ## Show this help
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# ──────────────── Docker compose ────────────────

.PHONY: up
up: ## Bring up the full stack (api + web + deps)
	$(COMPOSE) up -d --build

.PHONY: up-deps
up-deps: ## Bring up only deps (postgres + qdrant + minio + mailhog)
	$(COMPOSE) up -d postgres qdrant minio mailhog

.PHONY: down
down: ## Stop the stack
	$(COMPOSE) down

.PHONY: nuke
nuke: ## Stop the stack and drop all volumes
	$(COMPOSE) down -v

.PHONY: logs
logs: ## Tail logs from all services
	$(COMPOSE) logs -f --tail=200

# ──────────────── Backend ────────────────

.PHONY: install
install: ## Install Python deps via uv
	uv sync

.PHONY: api-dev
api-dev: ## Run FastAPI with hot reload (host)
	$(PY) uvicorn app.main:app --reload --port 8000 --host 0.0.0.0

.PHONY: migrate
migrate: ## Run alembic upgrade head
	$(PY) alembic upgrade head

.PHONY: seed
seed: migrate ## Migrate + ingest fixture standards + seed dev firm/user
	$(PY) python -m scripts.seed

.PHONY: ingest
ingest: ## Ingest a standards source: make ingest SOURCE=fasb_asc_public
	$(PY) python -m app.ingest_standards.jobs.run_ingest --source $(SOURCE)

.PHONY: rotator-status
rotator-status: ## Print the live KeyRotator state
	$(PY) python -m scripts.check_keys

.PHONY: openapi
openapi: ## Dump OpenAPI to spec/openapi.json
	$(PY) python -m scripts.gen_openapi

# ──────────────── Frontend ────────────────

.PHONY: web-install
web-install: ## Install web deps
	$(WEB) install

.PHONY: web-dev
web-dev: ## Run Next.js dev server
	$(WEB) dev

.PHONY: gen-api
gen-api: ## Generate typed API client from running api
	$(WEB) gen:api

# ──────────────── Tests ────────────────

.PHONY: test-unit
test-unit: ## Backend unit tests
	$(PY) pytest tests/unit -m "not integration and not e2e"

.PHONY: test-int
test-int: ## Backend integration tests (testcontainers)
	$(PY) pytest tests/integration -m integration

.PHONY: test-web
test-web: ## Frontend unit tests (vitest)
	$(WEB) test

.PHONY: e2e
e2e: up ## Full-stack Playwright e2e
	$(WEB) e2e

# ──────────────── Quality ────────────────

.PHONY: lint
lint: ## Lint everything
	$(PY) ruff check .
	$(PY) mypy app
	$(WEB) lint

.PHONY: fmt
fmt: ## Format everything
	$(PY) ruff format .
	$(WEB) format
