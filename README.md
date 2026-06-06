# Agentic Trip Planner

Production-style agentic trip planner backend built with **FastAPI** and **LangGraph**.
Personal project — building gradually to learn agentic AI concepts.

See [PLAN.md](docs/PLAN.md) for the phased roadmap.

## Stack

FastAPI · Pydantic v2 · SQLAlchemy 2 (async) · Alembic · Postgres 16 · LangGraph · OpenAI · structlog

## Quick start

```bash
cp .env.example .env
# fill in OPENAI_API_KEY, TAVILY_API_KEY, JWT_SECRET when needed

make up                 # build + start app + postgres
curl http://localhost:8000/health
```

API docs: <http://localhost:8000/docs>

## Common commands

```bash
make up                       # build + start
make down                     # stop
make logs                     # tail app logs
make shell                    # bash into app container
make test                     # pytest
make lint                     # ruff check
make format                   # ruff format
make migration-up             # apply migrations
make migration-create m="add foo"   # autogenerate migration
```

## Project structure

```
src/trip_planner/
  core/         # database engine, base classes
  config.py     # pydantic-settings
  main.py       # FastAPI app
  api/routes/   # HTTP endpoints
  schemas/      # Pydantic request/response models
  services/     # business logic
  agents/       # LangGraph graphs + state
  tools/        # agent tools (web_search, weather, ...)
  models/       # SQLAlchemy ORM models
alembic/        # database migrations
tests/
```
