# Testing Guide

## Core Principle

Every feature ships with tests. Tests are not optional — they are part of the definition of done.

---

## Coverage Requirement

**Minimum 90% coverage across the codebase.**

Coverage is measured per-module. No module may fall below 90% line coverage. New code that drops coverage below 90% will not be merged.

---

## What to Test

### Always test
- All API endpoints (happy path + error cases)
- All service functions with business logic
- All auth flows (valid token, expired token, missing token, wrong role)
- All database interactions (via async session fixtures)
- Edge cases that are not obvious from the happy path

### Do not test
- Third-party library internals
- SQLAlchemy model field definitions (no logic, no test needed)
- Pydantic schema field declarations (validated by Pydantic itself)

---

## Test Structure

Tests mirror the `src/trip_planner/` structure exactly. Every module has a corresponding test file at the same relative path under `tests/`.

```
tests/
    conftest.py              # shared fixtures: client, db session, test user, auth headers
    api/
        __init__.py
        routes/
            __init__.py
            test_health.py
    core/
        __init__.py
        test_database.py
    models/
        __init__.py
        test_user.py
    schemas/
        __init__.py
    services/
        __init__.py
    agents/
        __init__.py
    tools/
        __init__.py
```

If a module lives at `src/trip_planner/services/auth.py`, its tests live at `tests/services/test_auth.py`. No exceptions.

---

## Fixtures

All shared fixtures live in `tests/conftest.py`. No fixture duplication across test files.

Standard fixtures to provide:

- `client` — `AsyncClient` with `ASGITransport`
- `db` — test `AsyncSession` with rollback after each test
- `test_user` — a pre-created `User` row in the test DB
- `auth_headers` — `{"Authorization": "Bearer <token>"}` for an authenticated request

---

## Writing Tests

### Good
```python
async def test_register_returns_201_with_user_data(client: AsyncClient) -> None:
    payload = {"email": "user@example.com", "password": "secret123", "first_name": "Ada", "last_name": "Lovelace"}

    response = await client.post("/auth/register", json=payload)

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "user@example.com"
    assert "id" in body
    assert "password" not in body
    assert "hashed_password" not in body
```

### Bad (vague, no assertions on shape)
```python
async def test_register(client):
    r = await client.post("/auth/register", json={...})
    assert r.status_code == 201
```

**Rules:**
- Test name describes exactly what is being verified
- Assert both status code and response body shape
- Never leak sensitive fields (passwords, hashed values) in response assertions — assert they are absent
- One logical scenario per test function

---

## AI / Agent Testing

### Always test
- Structured output schema validity — assert required keys and value types are present
- Tool call selection for known prompts — verify the agent picks the right tool given deterministic input
- Fallback behavior when a tool fails — assert graceful degradation, not an unhandled exception
- Clarification flow for vague input — assert the agent asks for more information rather than guessing
- Token/cost tracking when available — assert usage fields are populated and within expected shape
- No hallucinated places or events when a verification tool exists — assert results are grounded

Do not snapshot full LLM text output unless the model is fully mocked. Test shape, decisions, and invariants — not exact wording.

---

## Mocking Rule

External APIs and LLM calls must be mocked in all unit and integration tests. No real network calls in CI.

Services that must always be mocked:
- OpenAI (LLM completions, embeddings)
- Tavily (web search)
- Duffel (flights)
- Google (places, maps)
- Ticketmaster (events)
- Weather APIs

Use `unittest.mock.AsyncMock` or `pytest-mock` for async clients. Never rely on live credentials or network in test runs.

---

## Running Tests

```bash
make test          # run full suite
make test-cov      # run with coverage report
```

Coverage report is generated with `pytest-cov`. The `make test-cov` target must pass before any PR is considered ready.


