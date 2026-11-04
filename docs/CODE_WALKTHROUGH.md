# TripMate AI — Code Walkthrough (Execution & Data Flow)

This document traces the app **from the moment it starts executing to the moment a final travel plan is returned**, file by file, with the exact data that flows at each step.

---

## Phase 0 — Process startup

**Command:** `uv run tripmate` (dev) or `uvicorn tripmate.app:app` (prod/Docker)

```
uv run tripmate
 └─► src/tripmate/__main__.py: main()
      └─► uvicorn.run("tripmate.app:app", host, port, reload=True)
           └─► uvicorn imports tripmate.app  ─►  module bottom: app = create_app()
```

**`src/tripmate/app.py: create_app()`** (cheap — no external connections yet):
1. `configure_ssl_certificates()` — points HTTPS clients at the certifi CA bundle (`config.py`).
2. `configure_logging(...)` — root logger → stdout with timestamps (`logging_config.py`).
3. Builds the `FastAPI` instance, mounts `/static`, includes the API router, registers the `/` page, favicon, and the three exception handlers that normalize every error to `{"success": false, "error": ...}`.

**Lifespan startup** (uvicorn fires it once the server boots) — `app.py: lifespan()`:

```
get_settings()                      config.py      validates env; missing GROQ_API_KEY/DATABASE_URL → crash now
create_connection_pool(settings)    services/checkpointer.py   psycopg ConnectionPool; pool.wait() fails fast if DB is down
create_checkpointer(pool)           services/checkpointer.py   PostgresSaver + setup() (creates tables, idempotent)
build_travel_graph(checkpointer)    agents/graph.py            wires 9 nodes + edges, compiles the graph
app.state.planner = TravelPlanner(graph)   agents/runner.py    stored where routes can reach it
```

The server is now listening. **Nothing else happens until a request arrives.**

---

## Phase 1 — Serving the UI

```
GET /            → app.py: home()      → renders web/templates/index.html
GET /static/...  → StaticFiles mount   → script.js, style.css
```

The user types a prompt; `script.js: sendMessage()` POSTs it to `/api/travel` (including a `thread_id` from `localStorage` if one exists).

---

## Phase 2 — `POST /api/travel` (draft creation)

### 2.1 HTTP boundary — `api/routes.py: create_travel_plan()`

```
JSON body ──pydantic──► TravelRequest(message, thread_id?)     api/schemas.py
                        (empty/missing message → 422/400, error shape preserved)
Depends(get_planner) ──► planner from app.state (503 if startup incomplete)
```

### 2.2 Thread dispatch — `agents/runner.py: TravelPlanner.start()`

```
thread_id = thread_id or f"user_{uuid4().hex}"
await asyncio.to_thread(_start_sync, ...)     ← blocking work leaves the event loop
    _start_sync:
        config = {"configurable": {"thread_id": thread_id}}
        result = graph.invoke(initial_state(user_input), config)
```

`initial_state()` (`agents/state.py`) seeds `TravelState`: `user_query`, empty result fields, `llm_calls=0`, `messages=[HumanMessage]`.

### 2.3 Inside the graph — node by node

**(a) `supervisor` — `agents/supervisor.py`**

```
state.user_query ─► LLM call 1 (guardrail)  ─► {"allowed": bool, "reason": str}
                 ─► LLM call 2 (supervisor) ─► {"selected_agents": [...],
                                                "trip_constraints": {...},
                                                "reasoning": str}
writes → guardrail_allowed, selected_agents (validated + ordered,
         itinerary_agent force-included), trip_constraints, supervisor_reasoning
```
Both calls fail open (allow / full workflow) on JSON errors.

**(b) Conditional routing — `agents/graph.py`**

```
route_from_supervisor: blocked → guardrail_blocked → END (reason becomes final_response)
                       else    → first selected agent
route_after_agent(X):  next selected agent after X in AGENT_ORDER, else itinerary_agent
```

**(c) Specialists** (only the selected ones run) — `agents/specialists.py`

| Node | Input from state | External calls | Writes |
|---|---|---|---|
| `flight_agent` | `user_query` | MCP `aviationstack`: `list_airports`, `list_airlines` (via `uvx aviationstack-mcp` subprocess) → results truncated to 3000 chars → Groq LLM | `flight_results` |
| `hotel_agent` | `user_query` | MCP `tavily`: `tavily_search("Best hotels for <query>")` (remote HTTP) | `hotel_results` |
| `weather_agent` | `user_query` | Groq LLM extracts destination city → MCP `weather`: `get_current_weather`, `get_forecast` (bundled subprocess → OpenWeather API) | `weather_results` |
| `budget_agent` | `user_query` + constraints + all three results above | Groq LLM | `budget_results` |

Every MCP call goes through `services/mcp.py: _get_server_tool()` — prerequisite check (key present? `uvx` found?) → load tools from **that server only** → `tool.ainvoke(...)`. Any failure is caught in the agent and replaced with labeled non-live fallback text; **the pipeline never stops here**.

*(The bundled weather server, `mcp_servers/weather.py`, is a separate FastMCP process speaking stdio; it wraps two OpenWeather REST endpoints and returns slim dicts.)*

**(d) `itinerary_agent` — `agents/review.py`**

```
user_query + trip_constraints + flight/hotel/weather/budget results ─► Groq LLM
writes → itinerary (the draft), approval_request
```

**(e) `human_approval` — `agents/review.py` — THE PAUSE**

```
interrupt({question, draft_itinerary, approval_request, selected_agents, ...})
   └─► LangGraph saves the ENTIRE state to PostgreSQL (thread_id key)
   └─► graph.invoke() RETURNS with "__interrupt__" in the result
```

### 2.4 Back up the stack — response to the browser

```
runner.serialize_result(result, thread_id):
    interrupt detected → requires_approval=True, answer=draft itinerary
routes: PlanResponse(**result)  →  JSON to browser
script.js: stores thread_id in localStorage,
           shows workflow chips + draft + Approve/Revise panel
```

**The HTTP request is over.** The half-finished plan lives only in PostgreSQL. Minutes or days can pass; the process can even restart.

---

## Phase 3 — `POST /api/travel/approve` (resume)

```
Browser sends {thread_id, approved, feedback}
routes.approve_travel_plan:  reject without feedback → 400
planner.resume() ─► to_thread ─► graph.invoke(Command(resume={approved, feedback}), config)
```

LangGraph **reloads the checkpointed state** for `thread_id` and re-enters `human_approval`:

```
(e') human_approval  interrupt() now RETURNS the resume payload
                     writes → approved, human_feedback
(f)  final_agent     builds review_instruction:
                        approved  → "preserve decisions while polishing"
                        rejected  → "apply this feedback: <human_feedback>"
                     + full state (query, constraints, all results, draft)
                     ─► Groq LLM ─► writes final_response (7-section plan)
(g)  END             state checkpointed one last time
```

```
serialize_result: no interrupt → requires_approval=False, answer=final_response
PlanResponse JSON → script.js hides approval panel, renders "Your Final AI Travel Plan"
```

---

## Complete data-flow pipeline (one picture)

```
user prompt (browser)
   │ POST /api/travel {message, thread_id?}
   ▼
TravelRequest (validated) ──► TravelPlanner.start ──► worker thread
   ▼
TravelState{user_query}
   ▼
supervisor:   query ──Groq──► guardrail verdict ──Groq──► selected_agents + constraints
   ▼ (route: skip unselected)
flight_agent:  aviationstack MCP ──► airports/airlines ──Groq──► flight_results
hotel_agent:   tavily MCP        ──► search results          ──► hotel_results
weather_agent: Groq(city) ──► weather MCP ──► OpenWeather ──► weather_results
budget_agent:  all results ──Groq──► budget_results
   ▼
itinerary_agent: everything ──Groq──► itinerary (draft)
   ▼
human_approval: interrupt ──► checkpoint to PostgreSQL ──► HTTP response (draft, requires_approval)
   ║                                   ...human decides...
   ▼ POST /api/travel/approve {thread_id, approved, feedback}
human_approval (resumed): approved + human_feedback into state
   ▼
final_agent: draft + feedback + all results ──Groq──► final_response
   ▼
serialize_result ──► PlanResponse JSON ──► browser renders final plan
```

## Where things end

- **Blocked request:** `supervisor → guardrail_blocked → END`; response has `guardrail_allowed: false` and the reason as the answer.
- **Normal request:** two HTTP round trips — draft (paused at approval) and final (after resume) — with PostgreSQL holding the state in between.
- **Process shutdown:** lifespan's `finally` closes the connection pool; paused threads survive in the database and can be resumed after restart.

## LLM call budget per full run

| Step | Calls |
|---|---|
| Guardrail + supervisor | 2 |
| Flight / budget / itinerary / final agents | 1 each |
| Weather agent (destination extraction) | 1 |
| Hotel agent | 0 (Tavily does the work) |
| **Typical full-workflow total** | **~7** (tracked in `state.llm_calls`) |
