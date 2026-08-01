# Architecture

## Memory ownership

The system keeps two distinct memories. Each has a single owner, and they are linked only by
the `thread_id`. Neither layer reaches into the other's storage.

### LangGraph checkpoint — execution state

- **Owner:** the agent (`src/trip_planner/agents`).
- **Storage:** `AsyncPostgresSaver` (`checkpoint_db_url`), keyed by `thread_id`.
- **Holds:** the accumulated LangChain message history the agent reasons over, tool results,
  the tool-call budget (`tool_call_count`), and the in-flight `current_itinerary` /
  `pending_clarification`. This is the agent's working memory and the authoritative execution
  state when a thread is resumed.
- **Lifecycle:** written by LangGraph on every superstep. Transient fields are reset by
  `triage_node` at the start of each turn; `messages` accumulates via the `add_messages`
  reducer so prior context survives across turns.

### Application database — user-visible conversation

- **Owner:** the API layer (`src/trip_planner/api`, `models`, `repositories`).
- **Storage:** the `threads` and `messages` tables.
- **Holds:** the product-facing transcript — human queries and assistant replies (summary text
  plus an itinerary snapshot) used for listing, pagination, and display. This is the only
  persistence layer exposed through the REST API and consumed by the frontend and mobile
  clients.
- **Lifecycle:** written explicitly by the route handlers, one row per user-visible message.

### The boundary

`plan_turn(query, thread_id)` in `agents/graph.py` is the **only** entry point the application
uses to run the agent. It accepts the user's message and thread id and returns a
`PlannerOutcome` containing just `clarification` and `itinerary`.

Execution state never crosses this boundary:

- The application never constructs or reads a `TripPlannerState`; it cannot see the message
  history, tool results, or tool-call budget.
- The agent runtime never reads the application database directly; on resume it restores context
  solely from its checkpoint keyed by `thread_id`, plus the single new human message it is
  handed.

This keeps execution details (which are an implementation concern of the agent) from leaking
into the persisted, user-visible conversation.

```
      write / read transcript

  Client
  (web/mobile)
        │
        ▼
     FastAPI  ───────────────────────────────► Application DB
        │                                      (threads, messages)
        │
        │ plan_turn(query, thread_id)
        ▼
     LangGraph  ─────────────────────────────► Checkpoint
      (agent)                                 (execution state)
```

## Invariants

- The application database is the only user-visible persistence layer.
- LangGraph checkpoints are an implementation detail of the agent.
- The application communicates with the agent only through `plan_turn()`.
- The two memories are correlated exclusively by `thread_id`.

