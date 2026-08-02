# Plan

> **Approach:** Build a production-style agentic trip planner backend using LangGraph from day 1.
> Start with a one-node graph, then introduce one agentic concept per phase — tool calling,
> structured output, memory, real travel APIs, multi-agent orchestration — so each is understood
> in isolation. Every phase is independently runnable.

---

# Part A — Foundations

## Phase 0 — Project Setup

- [x] Initialize Python project (`pyproject.toml`, `src/trip_planner/`)
- [x] Set up project structure (`api/routes`, `schemas`, `services`, `agents`, `tools`, `models`, `core`)
- [x] Configure environment variables with `pydantic-settings`
- [x] Set up FastAPI app with health check endpoint
- [x] Add `.env.example` with required keys (OpenAI, Tavily, JWT secret, LangSmith)
- [x] Add `.gitignore`
- [x] Dockerize from the start (`Dockerfile` + `docker-compose.yml` with `postgres:16`)
- [x] Add `Makefile` with common commands (up, down, logs, shell, test, lint, migration-up, migration-create)
- [x] Add `sqlalchemy[asyncio]`, `asyncpg`, `alembic` to requirements
- [x] Create `app/core/database.py` (async engine, session factory, `get_db` dependency)
- [x] Init Alembic, configure for async, generate empty first migration
- [x] Configure `structlog` for structured logging

## Phase 1 — Auth (JWT, manual)

- [x] Create `User` SQLAlchemy model (`id`, `email`, `hashed_password`, `first_name`, `last_name`, `country`, `created_at`, `updated_at`)
- [x] Alembic migration for `users` table
- [x] Build `services/auth_service.py`: bcrypt hashing + JWT encode/decode (HS256, 24h expiry)
- [x] Create endpoints: `POST /auth/register`, `POST /auth/login` (returns JWT)
- [x] Build `get_current_user` FastAPI dependency (Bearer token → `User`)
- [x] Protect a sample `GET /me` endpoint
- [x] Tests for register / login / invalid-token

---

# Part B — The Agent

## Phase 2 — Minimal LangGraph Agent (no tools)

- [x] Add `langgraph`, `langchain-openai`, `langsmith` to requirements
- [x] Build `agents/state.py` — `TripPlannerState` TypedDict (`messages`, `trip_request`, `draft_itinerary`)
- [x] Build `agents/graph.py` — one-node graph: `chat_node` calls `gpt-4o-mini`, returns free text
- [x] Write system prompt: "You are a trip planner. Ask clarifying questions if needed."
- [x] Create `POST /trips/plan` endpoint (auth-required): body `{query: str}` → invokes graph
- [x] Wire LangSmith env vars, confirm trace appears in dashboard
- [x] Test end-to-end: "Paris 7 days for 2" returns coherent text

## Phase 3 — Tools + ReAct Loop

- [x] Build `tools/web_search.py` — Tavily wrapper (`langchain-tavily`), top-5 results
- [x] Build `tools/weather.py` — Open-Meteo wrapper (geocoding + forecast for date range)
- [x] Convert graph to ReAct pattern: `agent_node` (LLM with `bind_tools`) ↔ `ToolNode`
- [x] Add conditional edge with `tools_condition` to loop until LLM emits final answer
- [x] Update system prompt: use `web_search` for current info, `weather` for forecasts, cite sources
- [x] Define Pydantic output schemas: `Itinerary`, `DayPlan`, `Activity`, `Source`
- [x] Final node forces structured output via `with_structured_output(Itinerary)`
- [x] Update `POST /trips/plan` to return `Itinerary` JSON
- [x] Tests with mocked tool responses (golden snapshot for Paris-7-day request)

## Phase 4 — Memory & Multi-turn

- [x] Add `langgraph-checkpoint-postgres`, run its setup migration
- [x] Wire `AsyncPostgresSaver` as the graph's checkpointer
- [x] Create `Thread` model (`id` UUID PK, `user_id` FK, `slug` UNIQUE, `title`, `deleted_at`, timestamps)
- [x] Create `Message` model (`id`, `thread_id` UUID FK → `threads.id`, `role`, `content`, `itinerary` JSONB nullable, `deleted_at`, `created_at`)
- [x] Add `is_active` to `User` model
- [x] Alembic migrations: `threads`, `messages`, `users.is_active`
- [x] `thread_repository` — `create`, `get_by_thread_id`, `list_by_user`, `delete`
- [x] `message_repository` — `create`, `list_by_thread_id` (cursor paginated by `created_at`)
- [x] Create endpoints:
  - `POST /threads` — create thread, invoke graph, persist messages, return `{thread_id, itinerary}`
  - `POST /threads/{thread_id}/messages` — append message, reinvoke graph, return `{itinerary}`
  - `GET /threads` — list current user's threads
  - `GET /threads/{thread_id}` — paginated message history + latest itinerary
  - `DELETE /threads/{thread_id}`
- [x] Ownership check on `thread_id` — 403 if `thread.user_id != current_user.id`
- [x] Tests: thread CRUD, 403 cross-user, multi-turn refinement, pagination

## Phase 4.5 — Clarifying Questions

- [x] Define `ClarificationRequest` schema (`message: str`, `missing_fields: list[str]`)
- [x] Add `triage_node` before tools: decides `plan | clarify` based on completeness of `trip_request`
- [x] Conditional edge: if `clarify` → return `ClarificationRequest`, skip tool calls
- [x] `POST /trips/{thread_id}/messages` response is a discriminated union: `Itinerary | ClarificationRequest`
- [x] Multi-turn test: vague query → clarifying questions → answers → full itinerary

---

# Part C — Real Travel Data

## Phase 5 — Travel API Tools

### 5a — Flights (Duffel)
- [x] Build `services/duffel_client.py` — OAuth token refresh, retry, rate limiting
- [x] Build `tools/flight_search.py` — Duffel flight search (origin, dest, dates, pax)
- [x] Register tool with agent, update prompt to extract origin city
- [x] Define `FlightOption`: `airline`, `stops`, `duration_min`, `price`, `currency`, `outbound_date`, `return_date`, `booking_url`
- [x] Extend `Itinerary` with `flights: list[FlightOption]` (optional, default empty)

### 5b — Hotels (LiteAPI)
- [x] Build `services/liteapi_client.py` — API key auth, retry, rate limiting
- [x] Build `tools/hotel_search.py` — city + dates + pax → top offers
- [x] Register tool with agent, update prompt
- [x] Define `HotelOption`: `name`, `area`, `rating`, `nightly_price`, `total_price`, `coordinates`, `booking_url`
- [x] Extend `Itinerary` with `hotels: list[HotelOption]` (optional, default empty)

### 5c — Places / POI (Geoapify + Google Places)
- [x] Build `tools/discover_places.py` — Geoapify Places API (categories, radius)
- [x] Build `tools/place_details.py` — Google Places Details for top N picks only
- [x] Build `tools/find_place_by_name.py` — Google Places Text Search for named lookups
- [x] Register the three places tools with the agent, update prompt (discover → find-by-name → details flow)
- [x] Extend `Activity` with `place_id`, `coordinates`, `address`, `rating`, `opening_hours`, `price_level`, `price_eur`, `ticket_url`, `photo_url` (all optional)

### 5d — Events (Ticketmaster Discovery)
- [ ] Build `services/ticketmaster_client.py` — auth, rate limiting
- [ ] Build `tools/event_search.py` — city + date range + classification (music / sports / arts)
- [ ] Update prompt: call `event_search` when user mentions interests
- [ ] Define `EventOption`: `name`, `category`, `venue`, `start_time`, `ticket_url`, `price_range`, `coordinates`
- [ ] Extend `Itinerary` with `events: list[EventOption]` (optional, default empty)

### 5e — Maps & Routing (Google Maps)
- [ ] Build `tools/distance_matrix.py` — travel time between activities (walking + transit)
- [ ] Build `tools/directions.py` — turn-by-turn between two stops
- [ ] Post-process: cluster same-day activities by proximity
- [ ] Define `TravelLeg`: `mode` (walk / transit / drive), `duration_min`, `distance_m`
- [ ] Extend `Activity` with `travel_from_previous: TravelLeg | None`

---

# Phase X — Architecture Hardening

> **Goal:** Take the backend from learning-project to production/market-ready (web + mobile).
> Sequenced into ordered waves; execute one wave at a time, keeping the project working after
> each. **Phase 5c (Places/POI) stays the immediate priority** — hardening only interrupts
> feature work if a task *directly* blocks 5c. Two lifecycle concepts coexist deliberately:
> **Thread** status (Wave 4, conversation/execution) vs **Trip** status (Wave 7, travel planning).

## Wave 1 — Security & Startup Hardening

- [x] Validate JWT subject — guard malformed `sub` (UUID parse) → 401
- [x] Reject inactive users — add `is_active` check in `get_current_user` (currently missing)
- [x] `Settings.assert_production_ready()` — abort startup in production when `jwt_secret` is default/empty or required provider keys are missing; call in `main.py` lifespan
- [x] Tests: inactive → 401, unknown/malformed sub → 401, prod+default secret aborts, dev tolerates

## Wave 2 — Transaction Lifetime

> **Decision:** the stateless graph was removed. Every trip becomes a persistent, resumable
> conversation (see Wave 7 trip-centric model), so the graph is **always stateful** — a single
> checkpointed graph. `run_planner` generates a `thread_id` when one isn't supplied.

- [x] Reduce transaction lifetime in `threads.py`: Validate → Persist request → **commit** → Run AI (outside txn) → Persist response → **commit** (no txn held across `run_planner`)
- [x] Tests: thread flow commits request before AI; ownership preserved

## Wave 3 — Structured Tool Outputs + LLM Separation + Graph State + Safety Limits

- [x] Canonical `ToolResult` contract shared by every tool (Flights, Hotels, Places, Weather, future Events/Maps): `status`, `provider`, `provider_request_id`, `latency_ms`, `cached`, `data`, `error`
- [x] Typed payloads: `FlightSearchResult`, `HotelSearchResult`, `WeatherResult`, `PlacesResult` (preserve provider IDs, prices, coordinates, metadata)
- [x] Tools return `ToolResult` via LangChain `content_and_artifact` (readable text for LLM + typed object in state)
- [x] `format_node` consumes structured `tool_results` from state — no reparsing tool text through the LLM
- [x] Separate LLM configs for triage / reasoning / structured formatting; deterministic temperature (0) for triage + structured output
- [x] Improve graph state: remove unused fields (e.g. `draft_itinerary`); separate `current_itinerary` / `pending_clarification` / `tool_results`; prevent stale state across runs
- [x] Graph safety limits: recursion limit, max-tool-calls guard, overall timeout (`asyncio.wait_for`); scaffold cost-tracking counter in state
- [x] Tests: `ToolResult` envelope per tool (success/empty/error, retryable, latency, provider); format from structured results; per-node model wiring; recursion/timeout

## Wave 4 — Follow-up Triage + Memory Ownership + Thread Lifecycle

- [x] Follow-up aware triage — use conversation history, classify intent: New Trip | Itinerary Modification | Clarification Answer | Trip Question; do **not** re-clarify when an itinerary already exists
- [x] Define memory ownership: LangGraph checkpoint = execution state; application DB (threads/messages) = user-visible conversation
- [x] Thread lifecycle `status` column (Pending / Running / Ready / Failed / Deleted) + Alembic migration + transitions
- [x] Tests: follow-up modification (no re-clarify), clarification answer flow, intent classification, status transitions

## Wave 5 — Stable Pagination + Bulk Soft Delete

- [x] Composite `(created_at, id)` cursor for message listing; add pagination to thread listing (currently unpaginated)
- [x] Replace row-by-row loop in `soft_delete_by_thread` with a single bulk `UPDATE`
- [x] Tests: pagination stable under same-timestamp rows; bulk delete in one statement

## Wave 6 — Shared HTTP Clients + Retry Resilience

- [x] Lifespan-managed pooled `httpx.AsyncClient`(s) injected into service clients (replace per-request `AsyncClient`)
- [x] Configure request timeouts (connect/read/write) centrally for every provider
- [x] Retry on network failures (`ConnectError`, `TimeoutException`, connection resets) in addition to 429/5xx; handle non-JSON error bodies gracefully
- [x] Tests: retries on `ConnectError`/timeout; non-JSON error handled; shared client reused

## Wave 7 — Domain Model Evolution: Trip, ItineraryVersion, Place, Selections

> Deferred: start **after** the Places domain is complete and **before** the Frontend phase. Largest wave — plan as its own sub-plan first.

> **Architectural decision — Trip-centric conversation model (drives this wave):**
> The product is an AI Travel Assistant, not a generic chat app. The core business entity is a
> **Trip**; the conversation is merely the interface for planning it. Domain hierarchy:
> `Trip → Thread → (Messages + LangGraph Checkpoints)`. Responsibilities are separated —
> **Trip** owns destination/budget/itinerary/selected flights+hotels/metadata; **Thread** owns
> conversation history + LangGraph execution state/checkpoints.
>
> - `POST /trips` — the only entry point for creating a new trip. Creates Trip, creates Thread automatically, invokes the stateful graph, writes the first checkpoint and returns the first assistant response.
> - `POST /threads/{thread_id}/messages` — continue only. Load checkpoint, resume graph, persist checkpoint and return response. Never creates Trips.
> - Remove `POST /threads` once `POST /trips` is introduced. Threads become an internal implementation detail of a Trip rather than a top-level resource for creating conversations.
> - Remove `POST /trips/plan` or keep it only as a temporary thin alias until clients migrate, then delete it.
> - Every MVP trip is a persistent, resumable conversation (survives refresh / return-next-day), so the stateful graph is the default.

> **Sub-plan (execute top-to-bottom, one task per review gate). Cardinality: Trip 1—1 Thread for MVP.**
> Current state: no `Trip` model — itinerary JSON is stored only on `messages.itinerary`; routers
> orchestrate the graph + persistence directly; `POST /threads` creates, `POST /trips/plan` is stateless.

### 7.1 — `Trip` model + schema foundation
- [x] `Trip` model (`id`, `user_id` FK, `title`, `slug`, `destination` nullable, `status`, `deleted_at`, timestamps) + `trip_id` FK on `threads` (1—1, UNIQUE); Alembic migration
- [x] `trip_repository` (`create_trip`, `get_by_id`, `list_by_user` keyset, `soft_delete`) + tests

### 7.2 — Trip lifecycle
- [x] `TripStatus` enum (Draft / Generating / Ready / Completed / Archived) with a guarded transition helper (reject illegal transitions) + tests

### 7.3 — Versioned itineraries
- [x] `ItineraryVersion` model (`id`, `trip_id` FK, `version_number`, `itinerary` JSONB, `created_at`) + `Trip.current_version_id` pointer; Alembic migration
- [x] `itinerary_version_repository` (`add_version` auto-incrementing per trip, `get_current`, `list_versions`, `set_current` for rollback) + tests

### 7.4 — Provider-independent `Place`
- [x] `Place` model (`id`, `provider`, `external_id`, `name`, `latitude`, `longitude`, `address`, `metadata` JSONB) with unique `(provider, external_id)`; Alembic migration
- [x] Normalization upsert (map provider activity result → `Place`, dedupe by `(provider, external_id)`) + tests

### 7.5 — Persisted selections
- [x] `SelectedFlight` and `SelectedHotel` models persisting the chosen option snapshots separately from search results; Alembic migrations, repositories, and tests

### 7.6 — Application service
- [x] `TripPlanningService` becomes the sole application entry point for planner orchestration (graph execution, persistence, and lifecycle transitions); routers stop orchestrating. Assistant response, itinerary version, and lifecycle transition commit atomically in one transaction (test rollback-on-failure) + service tests

### 7.7 — Trip-centric API surface
- [ ] `POST /trips` — sole creation entry point (Trip + Thread + first checkpoint + first assistant response) via `TripPlanningService` + route tests
- [ ] `POST /threads/{thread_id}/messages` — continuation routes through the service (loads trip, resumes graph, persists new version + message atomically) + route tests
- [ ] Remove `POST /threads` creation; remove `POST /trips/plan` (or keep as thin alias until clients migrate) + adjust affected tests

### 7.8 — Integration tests
- [ ] End-to-end: trip versioning/rollback, status transitions, place normalization, selection persistence, creation flow through `POST /trips`, continuation through `POST /threads/{thread_id}/messages`


## Wave 8 — Trip Validation Engine (future product)

- [ ] Post-generation pipeline: Generate → Route optimization → Constraint validation → Repair invalid days
- [ ] Validate opening hours, travel time, weather conflicts, arrival/departure constraints, activity overlap
- [ ] Explain validation repairs (attach validation notes to itinerary)
- [ ] Tests: constraint violations detected + repaired; validated itinerary output

> **Deferred to post-MVP:** checkpoint cleanup / retention policy (tied to account deletion
> + GDPR), cost tracking, deeper observability.

---

# Part D — Clients

## Phase 6 — Web Frontend

- [ ] Choose stack (Next.js + TypeScript + Tailwind) and scaffold the app
- [ ] Auth flow: register / login, JWT storage, protected routes, logout
- [ ] Typed API client with loading + error states
- [ ] Trip planning chat UI: thread list, message thread, send message, clarification prompts
- [ ] Render structured itinerary: days, activities, flights, hotels, places (map view)
- [ ] Thread history with pagination; create / delete thread
- [ ] Responsive layout (desktop + mobile web)
- [ ] Deploy (Vercel or container) with environment config

## Phase 7 — Mobile App

- [ ] Choose stack (React Native + Expo) and scaffold the app
- [ ] Reuse auth + typed API client (login, token storage via secure storage)
- [ ] Chat + itinerary screens (native navigation)
- [ ] Native itinerary rendering with maps and share sheet
- [ ] Offline cache of the latest itinerary per thread
- [ ] Build + internal distribution (TestFlight / Play internal testing)

---

> **MVP ends here.** Once the web and mobile apps are usable, evaluate the product on real
> usage before planning further. Post-MVP candidates (Evaluation, Multi-agent orchestration,
> Personalization, Recommendations, Production scaling, Redis, Background jobs, Cost
> optimization, Analytics) will be planned then based on real usage.
