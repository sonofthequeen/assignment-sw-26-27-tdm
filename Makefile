# Convenience wrappers (POSIX shell + GNU make). Every target is a thin alias for a
# raw command documented in README.md, so nothing here is required: on Windows
# without make, run the README commands directly.
#
# The backend targets expect an activated virtual environment (see `install-backend`).

PYTHON ?= python
NPM ?= npm

.PHONY: install-backend install-frontend migrate seed import-sample backend frontend \
        test-backend test-frontend lint build compose-up compose-demo compose-down acceptance

install-backend:  ## dependencies pinned by backend/constraints.txt
	cd backend && $(PYTHON) -m pip install -c constraints.txt -e ".[dev]"

install-frontend:
	cd frontend && $(NPM) ci

migrate:
	cd backend && alembic upgrade head

seed:
	cd backend && $(PYTHON) -m scripts.seed

import-sample:  ## dry run; append ARGS=--commit to write
	cd backend && $(PYTHON) -m scripts.import_csv sample-data/historical_runs.csv $(ARGS)

backend:
	cd backend && uvicorn app.main:create_app --factory --reload --port 8000

frontend:
	cd frontend && $(NPM) run dev

test-backend:
	cd backend && $(PYTHON) -m pytest -q

test-frontend:
	cd frontend && $(NPM) test

lint:
	cd backend && ruff check . && ruff format --check .
	cd frontend && $(NPM) run typecheck

build:
	cd frontend && $(NPM) run build

compose-up:
	docker compose up --build -d --wait

compose-demo:  ## with the synthetic demo dataset
	SEED_DEMO_DATA=true docker compose up --build -d --wait

compose-down:  ## keeps the database volume; add -v manually to delete it
	docker compose down

acceptance: lint test-backend test-frontend build
	cd backend && alembic check
