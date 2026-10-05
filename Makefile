SHELL := /bin/bash
PY ?= python3.14
VENV := .venv
BIN := $(VENV)/bin

.DEFAULT_GOAL := help
.PHONY: help venv install test test-gateway test-services test-frontend load lint format typecheck e2e up down logs clean

help: ## Show targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-16s %s\n", $$1, $$2}'

venv: ## Create the Python 3.14 virtualenv
	$(PY) -m venv $(VENV)

install: venv ## Install all Python + frontend dependencies
	$(BIN)/pip install -q -r gateway/requirements-dev.txt -r services/service_a/requirements-dev.txt locust
	cd frontend && npm ci

test: test-gateway test-services test-frontend ## Run every automated test suite

test-gateway: ## Gateway unit + integration tests with coverage
	cd gateway && ../$(BIN)/python -m pytest --cov=app --cov-report=term-missing

test-services: ## Service A and B tests
	cd services/service_a && ../../$(BIN)/python -m pytest -q
	cd services/service_b && ../../$(BIN)/python -m pytest -q

test-frontend: ## Frontend typecheck, unit tests and build
	cd frontend && npm run build && npm test

load: ## In-process rate limiter load test
	cd gateway && ../$(BIN)/python -m pytest -m load tests/load -s

lint: ## Ruff lint (all Python)
	$(BIN)/ruff check gateway services scripts load_test

format: ## Ruff format
	$(BIN)/ruff format gateway services scripts load_test

typecheck: ## mypy on the gateway
	cd gateway && ../$(BIN)/mypy app

e2e: ## Smoke test against a running stack (make up first)
	$(BIN)/python scripts/e2e_smoke.py --admin-password "$$(grep ^ADMIN_PASSWORD .env | cut -d= -f2)"

up: ## Build and start the stack (needs .env)
	@test -f .env || (echo "Create .env first: cp .env.example .env" && exit 1)
	docker compose up --build -d

down: ## Stop the stack
	docker compose down

logs: ## Tail all logs
	docker compose logs -f --tail=100

clean: ## Remove caches and build output
	rm -rf frontend/dist .pytest_cache .ruff_cache .mypy_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
