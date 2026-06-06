# Coding Style Guide

## Core Principle
**Code must speak for itself.** Prioritize clarity and readability over cleverness. A reader should understand intent without needing to decipher syntax 34 months later.

---

## Agent Change Rules

- Do not modify files outside the current task unless explicitly approved.
- Do not refactor unrelated code.
- Do not introduce new dependencies without asking.
- Do not change public API contracts unless the plan says so.
- After implementation, summarize changed files and why each change was needed.
- If strict typing requires Any or ignores, stop and ask.

## Variable & Function Naming

### Good
```python
has_usage_metadata = hasattr(response, "usage_metadata") and response.usage_metadata

if has_usage_metadata:
    extract_tokens(response)
```

### Bad (unclear intent)
```python
if hasattr(response, "usage_metadata") and response.usage_metadata:
    extract_tokens(response)
```

**Rule:** Extract complex conditions into named variables that describe what you're checking.

---

## Conditionals & Logic

### Good
```python
prompt_tokens = 0
completion_tokens = 0

has_usage_metadata = hasattr(response, "usage_metadata") and response.usage_metadata

if has_usage_metadata:
    prompt_tokens = response.usage_metadata.get("input_tokens", 0)
    completion_tokens = response.usage_metadata.get("output_tokens", 0)
```

### Bad (nested fallbacks, hard to follow)
```python
prompt_tokens = usage_metadata.get("input_tokens", token_usage.get("prompt_tokens", 0))
```

**Rule:** Initialize defaults first. Use single-level checks. Avoid nested fallbacks.

---

## List Building

### Good
```python
query_parts = [
    "Use this conversation context to resolve references:",
]
query_parts.extend(history_lines)
query_parts.append(f"current_question: {question}")

return "\n".join(query_parts)
```

### Bad (unpacking syntax, unclear)
```python
return "\n".join([
    "Use this conversation context to resolve references:",
    *history_lines,
    f"current_question: {question}",
])
```

**Rule:** Build lists step-by-step. Use `.extend()` and `.append()`. Avoid unpacking `*` in list literals.

---

## Use Cool Syntax Only If...

1. **Performance matters** (e.g., list comprehension for large data)
2. **Widely understood** (e.g., `for x in list`)
3. **Makes code shorter AND clearer** (rare)

### Example: When to use list comprehension
```python
# Good: clear intent, standard pattern
formatted_chunks = [f"[{i}] {chunk}" for i, chunk in enumerate(chunks, start=1)]

# NOT good: unpacking, walrus, nested comprehension
messages = [msg for msg in history if (content := msg.get("content")) and len(content) > 0]
```

---

## Functions

### Good
```python
def generate_answer(context: str, question: str, history: list[dict] | None = None) -> dict:
    """Generate LLM answer from context and question using conversation history."""
    response = qa_chain.invoke({
        "context": context,
        "question": question,
        "history": _build_chat_history_messages(history),
    })

    # Clear, named extraction
    has_usage_data = hasattr(response, "usage_metadata") and response.usage_metadata
    if has_usage_data:
        tokens = extract_tokens(response)
    else:
        tokens = {"prompt": 0, "completion": 0, "total": 0}

    return {
        "answer": response.content,
        "usage": tokens,
    }
```

### Bad (unclear logic, magic numbers)
```python
def gen_ans(ctx, q, h=None):
    r = chain.invoke({"ctx": ctx, "q": q, "h": cvt_hist(h)})
    t = (getattr(r, "usage_metadata", {}) or {}).get("input_tokens", 0)
    return {"answer": r.content, "tokens": t}
```

**Rule:** Full names, clear docstrings, explicit logic flow.

---

## Comments

Add comments only when **why**, not **what**.

### Good
```python
# Limit history to recent turns to keep prompt token count manageable
recent_history = history[-max_messages:]
```

### Bad (obvious from code)
```python
# Get the last max_messages items
recent_history = history[-max_messages:]
```

---

## Error Handling

### Good
```python
if not session:
    raise HTTPException(status_code=404, detail="Session not found")

if not retrieved_chunks:
    return {"answer": "No documents found", "sources": []}
```

### Bad (unclear what went wrong)
```python
try:
    session = get_session(db, session_id)
except:
    pass
```

**Rule:** Explicit error checks. Clear error messages.

---

## String Building

### Good (Clear intent, named parts)
```python
instruction = "Use this conversation context to resolve references in the current question:"
retrieval_query = f"{instruction}\n\n{formatted_history}\ncurrent_question: {question}"

return retrieval_query
```

### Bad (Multi-line f-string, unclear what we're building)
```python
return f"""Use this conversation context to resolve references in the current question:

{formatted_history}
current_question: {question}"""
```

**Rule:** Name each part of the string. Use f-string on the final assembled result. Reader instantly knows what each piece is.

---

## Type Annotations

**Strict typing is enforced.** Pylance/Pyright runs in `strict` mode. Types are part of the contract — they document intent, catch bugs at author time, and make refactors safe. A reader 34 months from now should see the shape of every value flowing through the system without running the code.

### Rules

1. **Every function signature is fully typed** — parameters and return type. No exceptions.
2. **No bare `dict`, `list`, `tuple`** — always parameterize: `dict[str, int]`, `list[Chunk]`, etc.
3. **`Any` is forbidden.** Do not introduce `Any` on your own. If you believe `Any` is the only correct choice (e.g. genuinely untyped third-party return value, dynamic dispatch), **stop and ask** with a written justification of why no other type fits. Approval is required before `Any` enters the codebase.
4. **Use `TypedDict` for structured dicts that flow between modules** — chunks, LLM results, token usage, history messages, API response shapes. If a dict has a known set of keys, it gets a `TypedDict`.
5. **Local variables don't need annotations** when the type is obvious from the right-hand side. Annotate only when the inferred type is wrong or the empty-collection case is ambiguous (`history: list[HistoryMessage] = []`).
6. **Prefer `X | None` over `Optional[X]`** (PEP 604 syntax).

### Good

```python
from typing import TypedDict

class ChunkMetadata(TypedDict, total=False):
    source: str
    page: int
    chunk_index: int

class Chunk(TypedDict):
    text: str
    score: float
    metadata: ChunkMetadata

class TokenUsage(TypedDict):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int

class LLMResult(TypedDict):
    answer: str
    usage: TokenUsage

def rerank_chunks(query: str, chunks: list[Chunk], top_k: int) -> list[Chunk]:
    ...

def generate_answer(
    context: str,
    question: str,
    history: list[HistoryMessage] | None = None,
) -> LLMResult:
    ...
```

### Bad (bare generics, no contract)

```python
def rerank_chunks(query, chunks, top_k):  # no types at all
    ...

def generate_answer(context: str, question: str, history: list[dict] | None = None) -> dict:
    # list[dict] = list[dict[Unknown, Unknown]] in strict mode
    # Caller has no idea what keys the result has
    ...
```

### Where TypedDict belongs in this project

Define shared shapes in `app/services/types.py`:

- `Chunk` / `ChunkMetadata` — output of retrievers and reranker
- `HistoryMessage` — `{"role": Literal["user", "assistant"], "content": str}`
- `TokenUsage` — LLM token counts
- `LLMResult` — `generate_answer` return value
- `Source` — citation entry returned by `/ask`

Service modules import and use these. Routers reuse the same types — no parallel definitions.

### Escape hatch (for when strict is too much overhead)

If a specific module deals with genuinely dynamic data (e.g. raw JSON from an unknown external API before validation), narrow the relaxation to that module with a file-level pragma:

```python
# pyright: reportUnknownMemberType=false, reportUnknownArgumentType=false
```

This is preferred over loosening the project-wide config. Strict stays the default; relaxation is local and visible.

---

## Imports

### Good
```python
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_openai import ChatOpenAI
from app.core.config import settings
```

### Bad (mixed line breaks, unclear organization)
```python
from langchain_core.messages import AIMessage, HumanMessage; from langchain_openai import ChatOpenAI
```

**Rule:** One import per line (or logical group). Order: stdlib, third-party, local.

---

## Whitespace & Formatting

**Code must have space to breathe.** Blank lines group related logic and make flow obvious. **Maximum 1 blank line anywhere—no stacking.**

### Spacing Rules

1. **Between function definitions:** 1 blank line
2. **Between logical sections inside a function:** 1 blank line
3. **Before return statements:** 1 blank line
4. **Around loops/conditions:** 1 blank line before and after
5. **Never stack blank lines** (no `\n\n\n`)
6. **Group related variables with blank lines between groups**

### Good (Proper breathing room, max 1 blank)
```python
def generate_answer(context: str, question: str, history: list[dict] | None = None) -> dict:
    """Generate LLM answer from context and question."""
    response = qa_chain.invoke({
        "context": context,
        "question": question,
        "history": _build_chat_history_messages(history),
    })

    prompt_tokens = 0
    completion_tokens = 0
    total_tokens = 0

    has_usage_data = hasattr(response, "usage_metadata") and response.usage_metadata

    if has_usage_data:
        prompt_tokens = response.usage_metadata.get("input_tokens", 0)
        completion_tokens = response.usage_metadata.get("output_tokens", 0)
        total_tokens = response.usage_metadata.get("total_tokens", 0)

    return {
        "answer": response.content,
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
        },
    }

def load_session(db: AsyncSession, session_id: UUID) -> Session:
    """Load session from database."""
    session = await db.get(Session, session_id)

    return session
```

### Bad (Stacked blank lines, dense sections)
```python
def generate_answer(context: str, question: str, history: list[dict] | None = None) -> dict:


    response = qa_chain.invoke({...})


    prompt_tokens = 0
    completion_tokens = 0
    total_tokens = 0


    has_usage_data = hasattr(response, "usage_metadata") and response.usage_metadata
    if has_usage_data:
        prompt_tokens = response.usage_metadata.get("input_tokens", 0)


        completion_tokens = response.usage_metadata.get("output_tokens", 0)
    return {...}



def load_session(db: AsyncSession, session_id: UUID) -> Session:
    session = await db.get(Session, session_id)
    return session
```

### More Examples: Loops & Conditionals

Good (clear sections, max 1 blank):
```python
def build_history_aware_query(question: str, history: list[dict], max_messages: int = 6) -> str:
    if not history:
        return question

    recent_history = history[-max_messages:]
    history_lines = []

    for message in recent_history:
        role = message.get("role")
        content = message.get("content")

        if role in {"user", "assistant"} and content:
            history_lines.append(f"{role}: {content}")

    if not history_lines:
        return question

    query_parts = [
        "Use this conversation context to resolve references:",
    ]
    query_parts.extend(history_lines)
    query_parts.append(f"current_question: {question}")

    return "\n".join(query_parts)
```

Bad (dense, no breathing):
```python
def build_history_aware_query(question: str, history: list[dict], max_messages: int = 6) -> str:
    if not history:
        return question
    recent_history = history[-max_messages:]
    history_lines = []
    for message in recent_history:
        role = message.get("role")
        content = message.get("content")
        if role in {"user", "assistant"} and content:
            history_lines.append(f"{role}: {content}")
    if not history_lines:
        return question
    query_parts = ["Use this conversation context to resolve references:"]
    query_parts.extend(history_lines)
    query_parts.append(f"current_question: {question}")
    return "\n".join(query_parts)
```

### Line Length

- **Soft limit:** 100 characters (readability over horizontal scroll)
- **Hard limit:** 120 characters (very rare exceptions)

---

## Summary

1. **Use explicit > implicit**
2. **Readable > clever**
3. **Named variables > inline expressions**
4. **Simple logic > nested conditions**
5. **Code that reads like prose is code that works.**
