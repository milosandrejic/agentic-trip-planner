# API Improvements — Happy Path (temp tracking)

Investigate and fix one at a time. Check off when done + verified (pyright + tests green).

## Data on the Trip entity
- [x] **1. Populate `trip.destination`** — copy the itinerary's `destination` (e.g. `"Rome, Italy"`) onto the Trip entity so cards/lists don't parse the itinerary.
- [x] **2. Human-readable trip title** — stop truncating the raw prompt. Generate a clean title (e.g. `Rome, Italy`, `7 Days in Rome`, `Rome Trip`). Title must never contain the raw prompt.
- [x] **3. Structured slug** — derive slug from structured data (e.g. `rome-2026-09-14`) or `trip-{uuid}`, not the serialized prompt.

## Flights / hotels / currency
- [x] **4. Deduplicate flights** — drop duplicate offers before returning; key on (airline, outbound date, return date, duration, price).
- [x] **5. Consistent currency** — whole itinerary uses a single currency (user's requested/default); no mixed EUR/USD.
- [x] **6. `null` instead of empty strings** — unknown `currency`/`total_price`/`url`/etc. must be `null`, never `""`.
- [x] **7. Numeric prices as numbers** — `price: 164.12` not `"164.12"` (flights and hotels).
- [x] **8. No `~` in estimated prices** — return `nightly_price: 143.00` + `is_estimated: true` instead of `"~143.00"`.
- [x] **9. Source URLs valid or omitted** — drop sources with empty `url`; only return sources with a valid URL.

## Generation quality
- [ ] **10. Full itinerary length** — 7-day request returned only Day 1. Investigate token limits / prompt / structured-output limits / bug. Must return all requested days.
- [ ] **11. Partial follow-up updates** — a "replace hotels" follow-up regenerated the whole itinerary. Follow-ups should regenerate only the affected section (hotels → hotels, flights → flights, itinerary → itinerary).

---
Notes:
- Items 1–9 are shaping/schema fixes (mostly deterministic, easy to unit-test).
- Items 10–11 touch the LangGraph planner/agent behavior (harder; may need prompt + graph changes).
