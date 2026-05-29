.PHONY: up down logs shell test lint format migration-up migration-down migration-create install dev

up:
	docker compose up --build -d

down:
	docker compose down

logs:
	docker compose logs -f app

shell:
	docker compose exec app bash

test:
	docker compose exec app pytest -v

lint:
	docker compose exec app ruff check src tests

format:
	docker compose exec app ruff format src tests

migration-up:
	docker compose exec app alembic upgrade head

migration-down:
	docker compose exec app alembic downgrade -1

migration-create:
	@if [ -z "$(m)" ]; then echo "Usage: make migration-create m=\"message\""; exit 1; fi
	docker compose exec app alembic revision --autogenerate -m "$(m)"

install:
	pip install -e ".[dev]"

dev:
	uvicorn trip_planner.main:app --reload --host 0.0.0.0 --port 8000
