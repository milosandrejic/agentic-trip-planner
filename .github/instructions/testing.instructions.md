---
applyTo: "tests/**"
description: "Testing conventions and coverage rules for the trip-planner backend"
---

# Testing

Follow the full guide in [TESTING.md](../../docs/TESTING.md). Key rules:

> **When to load the full guide:** The rules below cover the common cases and are
> sufficient for most tests — do not open the full doc on every change. If a
> situation is ambiguous or you need a concrete example, read the linked doc in
> full before writing tests. If the doc itself is unclear or seems to conflict
> with these rules, ask the user.

- Minimum 90% coverage; no module below 90% line coverage.
- Tests mirror `src/trip_planner/` exactly: a module at `src/trip_planner/services/auth.py` is tested at `tests/services/test_auth.py`.
- All shared fixtures live in `tests/conftest.py` — no fixture duplication.
- Test names describe exactly what is verified (e.g. `test_register_returns_201_with_user_data`).
- Assert both status code AND response body shape; assert sensitive fields (passwords, hashes) are absent.
- One logical scenario per test function.

## AI / agent tests

- Test structured-output schema validity, tool-call selection, tool-failure fallback, clarification flow, and token/cost tracking.
- Test shape, decisions, and invariants — not exact LLM wording. Don't snapshot full LLM text unless the model is mocked.

## Mocking rule

- Mock all external APIs and LLM calls — no real network in CI.
- Always mocked: OpenAI, Tavily, Duffel, Google, Ticketmaster, weather APIs.
- Use `unittest.mock.AsyncMock` or `pytest-mock` for async clients.
