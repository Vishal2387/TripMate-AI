# TripMate AI — Architecture

## 1. What the system is

TripMate AI is a **multi-agent travel planner**. A supervisor LLM decides which specialist agents (flights, hotels, weather, budget) a request needs; the specialists gather data via **MCP servers**; an itinerary agent drafts a plan; the workflow then **pauses for human approval** (human-in-the-loop) before a final agent produces the polished answer. All of this is orchestrated by **LangGraph** with state checkpointed in **PostgreSQL**, and served by **FastAPI**.

## 2. System overview

```
┌────────────┐  HTTP/JSON   ┌──────────────────────────────────────────────┐
│  Browser   │◄────────────►│  FastAPI (src/tripmate/app.py + api/)        │
│  (web UI)  │              │  - routes, schemas, error shaping            │
└────────────┘              │  - lifespan owns all infrastructure          │
                            └──────────────┬───────────────────────────────┘
                                           │ asyncio.to_thread (worker thread)
                            ┌──────────────▼───────────────────────────────┐
                            │  TravelPlanner (agents/runner.py)            │
                            │  start() / resume() + result serialization   │
                            └──────────────┬───────────────────────────────┘
                                           │ graph.invoke(state | Command)
                            ┌──────────────▼───────────────────────────────┐
                            │  LangGraph workflow (agents/graph.py)        │
                            │  supervisor → specialists → itinerary        │
                            │  → human_approval (interrupt) → final        │
                            └───────┬──────────────────────────┬───────────┘
                                    │ checkpoints              │ tool calls
                     ┌──────────────▼──────────┐   ┌───────────▼───────────────┐
                     │ PostgreSQL              │   │ MCP servers               │
                     │ (PostgresSaver via      │   │ • Tavily (remote HTTP)    │
                     │  psycopg ConnectionPool)│   │ • AviationStack (uvx)     │
                     └─────────────────────────┘   │ • Weather (bundled, stdio)│
                                                   └───────────┬───────────────┘
                                                   ┌───────────▼───────────────┐
                                                   │ External APIs             │
                                                   │ Groq LLM · OpenWeather ·  │
                                                   │ Tavily · AviationStack    │
                                                   └───────────────────────────┘
```

## 3. Layers and their responsibilities

| Layer | Modules | Responsibility |
|---|---|---|
| **Presentation** | `web/` (templates + static) | Static HTML/JS/CSS UI; renders markdown, drives the approve/revise flow |
| **API** | `api/routes.py`, `api/schemas.py` | HTTP contract: validation (pydantic), dependency injection, error shape `{"success": false, "error": ...}` |
| **Application** | `agents/runner.py` (`TravelPlanner`) | Async facade over the graph; thread dispatch; serializing graph output to the API contract |
| **Domain (agents)** | `agents/state.py`, `supervisor.py`, `specialists.py`, `review.py`, `graph.py`, `prompts.py`, `llm.py` | The multi-agent workflow itself: routing rules, agent behaviors, prompt templates |
| **Infrastructure** | `services/mcp.py`, `services/checkpointer.py`, `mcp_servers/weather.py` | External world: MCP tool access, Postgres persistence |
| **Cross-cutting** | `config.py`, `logging_config.py`, `app.py` | Settings, logging, app assembly/lifespan |

Dependency direction is strictly downward: API → Application → Domain → Infrastructure. Nothing imports upward, and nothing connects to anything at import time.

## 4. The agent graph

```
START ─► supervisor ──(blocked)──► guardrail_blocked ─► END
             │
       (selected agents, canonical order, skipping unselected)
             ▼
   flight_agent ─► hotel_agent ─► weather_agent ─► budget_agent
             └───────────┬─────────────┴─────────────┘
                         ▼
                 itinerary_agent          (always included)
                         ▼
                 human_approval  ◄── interrupt(): state saved to Postgres,
                         ▼           HTTP request returns "requires_approval"
                  final_agent    ◄── resumed by POST /api/travel/approve
                         ▼
                        END
```

**Supervisor** makes two LLM calls: a *guardrail* (is this a travel request?) and a *router* (which specialists are needed + extracted trip constraints). Both **fail open** — a parsing failure selects the full workflow rather than erroring.

**Routing** is data-driven: `selected_agents` in the state + `AGENT_ORDER` in `state.py`. Each specialist's conditional edge finds the *next selected* agent, so unselected agents are skipped with zero cost.

**Specialists** each own one concern and one data source; every MCP failure degrades to clearly-labeled non-live guidance instead of failing the run.

**Human-in-the-loop** is implemented with LangGraph's `interrupt()`: the graph pauses, its state persists in Postgres keyed by `thread_id`, and a later `Command(resume=...)` continues exactly where it stopped — across HTTP requests and process restarts.

## 5. Concurrency model

- FastAPI endpoints are `async` and run on **one event loop**.
- `graph.invoke()` is blocking (seconds of LLM/MCP work), so `TravelPlanner` dispatches it with **`asyncio.to_thread`** — the event loop stays free; N concurrent plans use N worker threads.
- Inside a worker thread there is no running event loop, so specialist agents call async MCP helpers with **`asyncio.run()`** (a short-lived loop per call). This removed the old `nest_asyncio` hack.
- Each concurrent graph run borrows its own connection from the **psycopg `ConnectionPool`** — the checkpointer is safe under concurrency (a single shared connection would not be).

## 6. State & persistence

- **`TravelState`** (TypedDict) is the single state object flowing through the graph. `messages` accumulates via an `operator.add` reducer; all other fields are last-write-wins.
- **PostgresSaver** checkpoints the state after every node. `thread_id` is the persistence key: the frontend stores it in `localStorage` and sends it back for approval/continuation.
- The checkpointer's tables are created idempotently at startup (`checkpointer.setup()`).

## 7. Configuration & startup

- All config flows through `Settings` (pydantic-settings) — typed, validated, loaded from env/`.env`. Missing required keys fail at startup, not mid-request.
- **No import-time side effects**: importing any module is cheap and safe. The FastAPI **lifespan** is the only place infrastructure is created (pool → checkpointer → graph → planner on `app.state`) and torn down (pool close).
- Tests exploit this: injecting a fake planner into `app.state` before startup short-circuits the lifespan, so the suite runs with no DB, LLM, or network.

## 8. Error-handling strategy

| Failure | Behavior |
|---|---|
| Guardrail/supervisor LLM returns malformed JSON | Fail open: allow request / select full workflow |
| An MCP server or provider API is down | That agent returns labeled non-live fallback text; the plan still completes |
| Missing optional API key | Same graceful fallback, with an actionable message in logs |
| Missing required config, unreachable DB | Fail fast at startup (pool `wait()`, settings validation) |
| Any exception in a route | Logged with traceback; client gets `{"success": false, "error": ...}` (500), matching the frontend contract |
| Unhandled server error | Catch-all handler: generic message to client, full traceback in logs |

## 9. Key design decisions (and why)

1. **`src/` layout + installable package** — tests import the installed package, preventing "works from repo root only" bugs.
2. **Factory + lifespan over module-level globals** — testability, clean startup/shutdown, no hidden connection at import.
3. **Fail-open guardrail** — a safety feature must not become an availability bug; blocking is reserved for confident negative verdicts.
4. **Per-server MCP isolation** — tools are loaded from exactly one server per call, so one broken integration can't cascade.
5. **uv + `uv.lock`** — reproducible environments locally, in CI, and in the Docker build (same lockfile everywhere).
6. **Frontend contract preserved** — every response carries `success`, errors always `{"success": false, "error"}`; the UI needed zero changes during the restructure.
