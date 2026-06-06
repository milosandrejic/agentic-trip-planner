---
applyTo: "**/*.py"
description: "Python coding style and strict typing rules for the trip-planner backend"
---

# Python Coding Style

Follow the full guide in [CODING_STYLE.md](../../docs/CODING_STYLE.md). Key rules:

> **When to load the full guide:** The rules below cover the common cases and are
> sufficient for most edits — do not open the full doc on every change. If a
> situation is ambiguous or you need a concrete example, read the linked doc in
> full before writing code. If the doc itself is unclear or seems to conflict
> with these rules, ask the user.

- Extract complex conditions into named variables that describe what you're checking.
- Initialize defaults first; use single-level checks; no nested fallbacks.
- Build lists with `.extend()` / `.append()` — never `*` unpacking in literals.
- Name each string part separately, then assemble with a single f-string.
- Full descriptive names, a docstring on every function, explicit logic flow.
- Comments explain **why**, never **what**.
- Explicit error checks with clear messages; never bare `except: pass`.
- Max 1 blank line anywhere (no stacking); use blank lines to group logic.
- One import per line; order: stdlib, third-party, local.
- Soft line limit 100 chars, hard 120.

## Strict typing (pyright strict mode is enforced)

- Every function signature is fully typed — parameters AND return type, no exceptions.
- No bare `dict`, `list`, `tuple` — always parameterize (`dict[str, int]`, `list[Chunk]`).
- `Any` is forbidden — stop and ask with written justification before introducing it.
- Use `TypedDict` for structured dicts that flow between modules; shared shapes live in `src/trip_planner/services/types.py` — no parallel definitions.
- Local vars need annotations only when the type is not obvious from the right-hand side, or for ambiguous empty collections (`items: list[Item] = []`).
- Prefer `X | None` over `Optional[X]` (PEP 604).
- FastAPI dependencies use `Annotated[T, Depends(...)]`, not `T = Depends(...)`.
- Async generators are typed `AsyncGenerator[T, None]`; async context managers `AsyncIterator[T]`.
- Module-level pragmas (`# pyright: reportUnknownMemberType=false`) only for genuinely dynamic modules; never loosen the project-wide config.
