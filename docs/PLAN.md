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
- [ ] Protect a sample `GET /me` endpoint
- [ ] Tests for register / login / invalid-token

---

# Part B — The Agent

## Phase 2 — Minimal LangGraph Agent (no tools)

- [ ] Add `langgraph`, `langchain-openai`, `langsmith` to requirements
- [ ] Build `agents/state.py` — `TripPlannerState` TypedDict (`messages`, `trip_request`, `draft_itinerary`)
- [ ] Build `agents/graph.py` — one-node graph: `chat_node` calls `gpt-4o-mini`, returns free text
- [ ] Write system prompt: "You are a trip planner. Ask clarifying questions if needed."
- [ ] Create `POST /trips/plan` endpoint (auth-required): body `{query: str}` → invokes graph
- [ ] Wire LangSmith env vars, confirm trace appears in dashboard
- [ ] Test end-to-end: "Paris 7 days for 2" returns coherent text

## Phase 3 — Tools + ReAct Loop

- [ ] Build `tools/web_search.py` — Tavily wrapper (`langchain-tavily`), top-5 results
- [ ] Build `tools/weather.py` — Open-Meteo wrapper (geocoding + forecast for date range)
- [ ] Convert graph to ReAct pattern: `agent_node` (LLM with `bind_tools`) ↔ `ToolNode`
- [ ] Add conditional edge with `tools_condition` to loop until LLM emits final answer
- [ ] Update system prompt: use `web_search` for current info, `weather` for forecasts, cite sources
- [ ] Define Pydantic output schemas: `Itinerary`, `DayPlan`, `Activity`, `Source`
- [ ] Final node forces structured output via `with_structured_output(Itinerary)`
- [ ] Update `POST /trips/plan` to return `Itinerary` JSON
- [ ] Tests with mocked tool responses (golden snapshot for Paris-7-day request)

## Phase 4 — Memory & Multi-turn

- [ ] Add `langgraph-checkpoint-postgres`, run its setup migration
- [ ] Wire `AsyncPostgresSaver` as the graph's checkpointer
- [ ] Create `TripSession` model (`id`, `user_id` FK, `thread_id`, `title`, `created_at`, `updated_at`)
- [ ] Alembic migration for `trip_sessions`
- [ ] Create endpoints:
  - `POST /trips` — create new session, returns `thread_id`
  - `POST /trips/{thread_id}/messages` — send follow-up; reuses checkpointed state
  - `GET /trips` — list current user's trips
  - `GET /trips/{thread_id}` — full message history + latest itinerary snapshot
  - `DELETE /trips/{thread_id}`
- [ ] Ownership check on `thread_id` (403 on cross-user access)
- [ ] Test conversational refinement: "make day 3 about museums" updates only day 3

## Phase 4.5 — Clarifying Questions

- [ ] Define `ClarificationRequest` schema (`questions: list[str]`, `missing_fields: list[str]`)
- [ ] Add `triage_node` before tools: decides `plan | clarify` based on completeness of `trip_request`
- [ ] Conditional edge: if `clarify` → return `ClarificationRequest`, skip tool calls
- [ ] `POST /trips/{thread_id}/messages` response is a discriminated union: `Itinerary | ClarificationRequest`
- [ ] Multi-turn test: vague query → clarifying questions → answers → full itinerary

---

# Part C — Real Travel Data

## Phase 5 — Travel API Tools

### 5a — Flights (Duffel)
- [ ] Build `services/duffel_client.py` — OAuth token refresh, retry, rate limiting
- [ ] Build `tools/flight_search.py` — Duffel flight search (origin, dest, dates, pax)
- [ ] Add `api_cache` table for response caching (24h TTL)
- [ ] Register tool with agent, update prompt to extract origin city

### 5b — Hotels (LiteAPI)
- [ ] Build `services/liteapi_client.py` — API key auth, retry, rate limiting
- [ ] Build `tools/hotel_search.py` — city + dates + pax → top offers

### 5c — Places / POI (Geoapify + Google Places)
- [ ] Build `tools/places_search.py` — Geoapify Places API (categories, radius)
- [ ] Build `tools/place_details.py` — Google Places Details for top N picks only
- [ ] Build `tools/places_text_search.py` — Google Places Text Search for named lookups

### 5d — Events (Ticketmaster Discovery)
- [ ] Build `services/ticketmaster_client.py` — auth, rate limiting
- [ ] Build `tools/event_search.py` — city + date range + classification (music / sports / arts)
- [ ] Cache responses (12h TTL)
- [ ] Update prompt: call `event_search` when user mentions interests

### 5e — Maps & Routing (Google Maps)
- [ ] Build `tools/distance_matrix.py` — travel time between activities (walking + transit)
- [ ] Build `tools/directions.py` — turn-by-turn between two stops
- [ ] Post-process: cluster same-day activities by proximity, annotate each `Activity` with `travel_from_previous`

### 5f — Schema extensions
- [ ] Extend `Itinerary`: `flights: list[FlightOption]`, `hotels: list[HotelOption]`, `events: list[EventOption]`
- [ ] Extend `Activity`: `time`, `duration_min`, `place_id`, `coordinates`, `address`, `rating`, `opening_hours`, `price_level`, `price_eur`, `ticket_url`, `photo_url`, `travel_from_previous`
- [ ] Define `EventOption`: `name`, `category`, `venue`, `start_time`, `ticket_url`, `price_range`, `coordinates`
- [ ] Define `FlightOption`: `outbound`, `return_`, `airline`, `stops`, `duration_min`, `price`, `booking_url`
- [ ] Define `HotelOption`: `name`, `area`, `rating`, `nightly_price`, `total_price`, `coordinates`, `booking_url`
- [ ] Define `TravelLeg` (for `travel_from_previous`): `mode` (walk / transit / drive), `duration_min`, `distance_m`
- [ ] All new fields optional so earlier-phase outputs stay valid
- [ ] Per-tool unit tests with VCR.py cassettes

## Phase 6 — Multi-Agent Orchestration

- [ ] Refactor single ReAct graph into supervisor + subgraphs:
  - `supervisor` — routes to specialists, composes final itinerary
  - `flight_agent` — owns `flight_search`
  - `hotel_agent` — owns `hotel_search`
  - `itinerary_agent` — owns `weather` + `places` + `web_search`
- [ ] Use LangGraph `Send` API for parallel fan-out (flights + hotels in parallel)
- [ ] Shared state with reducers for merging partial results
- [ ] Add SSE streaming: `POST /trips/{id}/messages/stream`
- [ ] Benchmark single-agent vs multi-agent latency on 5 sample queries

---

# Part D — Evaluation & Production Hardening

## Phase 7 — Evaluation & Observability

- [ ] Build golden set: 15 trip queries in `eval/golden_set.json`
- [ ] Build `scripts/eval_agent.py` — schema validity, tool-call correctness, hallucinated-place detection (verify via Geoapify)
- [ ] Track per-run: tokens, $ cost, latency, tool-call count → `eval/results/<timestamp>.json`
- [ ] Add LangSmith datasets + LLM-as-judge evaluators
- [ ] Create `POST /feedback` endpoint (thumbs up/down per message)

## Phase 8 — Production Hardening

- [ ] Per-user rate limiting (`slowapi`)
- [ ] Per-user monthly budget cap (`user_budgets` table; reject when exceeded)
- [ ] Background processing for long plans (FastAPI `BackgroundTasks` or `arq`)
- [ ] Structured error taxonomy (`parse_error`, `tool_error`, `quota_error`, `auth_error`)
- [ ] OpenAPI docs polish, example payloads
- [ ] CI: GitHub Actions (ruff + pytest + docker build)

---

# Part E — Personalization & Recommendations

## Phase 9 — User Preferences

- [ ] Create `UserProfile` model: `interests`, `favorite_teams`, `favorite_artists`, `dietary`, `pace`, `budget_tier`, `accessibility`
- [ ] Endpoints: `GET /me/preferences`, `PUT /me/preferences`
- [ ] Onboarding flow: first-time `/trips/plan` triggers preferences prompt if profile empty
- [ ] Inject preferences into agent system prompt (`PreferenceContext` section)
- [ ] Bias `event_search` to auto-include favorite artists / teams when planning matching dates
- [ ] Eval: compare itinerary quality with/without preferences on same query (LangSmith A/B)

## Phase 10 — Implicit Signals & Trip History

- [ ] Create `ActivityFeedback` model: per-activity thumbs (from Phase 7) + swapped-out events
- [ ] Nightly job: aggregate signals → update `UserProfile.derived_interests`
- [ ] Past-trip retrieval: embed completed itineraries, retrieve top-k similar past trips, inject as few-shot examples
- [ ] Add `Itinerary.recommendation_notes` with "because you liked X in Y" reasoning trace
- [ ] Privacy: `DELETE /me/preferences`, `DELETE /me/history`
