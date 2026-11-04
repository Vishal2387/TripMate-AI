# TripMate AI — Interview Project Explanation

> Written in first person so it can be spoken aloud. Everything below is grounded in the actual code in `src/tripmate/`, so any claim here can be defended if an interviewer opens the repo.

---

## Quick Reference (glance at this before the interview)

| Item | Value |
|---|---|
| One-liner | Multi-agent travel planner: supervisor routes to specialists, human approves the draft, final plan is generated |
| Orchestration | LangGraph `StateGraph`, 9 nodes, conditional edges, `interrupt()` for human-in-the-loop |
| LLM | Groq, `llama-3.3-70b-versatile` (configurable), via `langchain-groq` |
| Tools | MCP (Model Context Protocol): Tavily (remote HTTP), AviationStack (stdio via `uvx`), bundled OpenWeather server (stdio, FastMCP) |
| Persistence | PostgreSQL via `PostgresSaver` + psycopg `ConnectionPool` |
| API | FastAPI: `POST /api/travel`, `POST /api/travel/approve`, `GET /health` |
| Concurrency | `asyncio.to_thread` for graph runs; `asyncio.run` per MCP call inside the worker thread |
| Packaging | uv + `uv.lock`, `src/` layout, hatchling, multi-stage Docker, non-root runtime |
| Tests | pytest: API contract tests with an injected fake planner + pure unit tests for routing and serialization |
| LLM calls per full run | ~7 (2 supervisor + flight + weather-extraction + budget + itinerary + final) |
| Version | 2.0.0 (v2 was a restructure from a single-file prototype) |

---

## 1. Two-Minute Summary

TripMate AI is a travel-planning assistant I built to explore how you take a multi-agent LLM system from a demo to something that behaves like real software.

The idea is simple from the user's side: you type something like "Plan a 5-day trip to Japan under $3,000," and the system comes back with a full plan covering flights, hotels, weather, budget, and a day-by-day itinerary. Under the hood it's not one big prompt. A **supervisor agent** first checks that the request is actually about travel, then decides which **specialist agents** are needed. If you only ask about weather in Lisbon, it doesn't waste time and money running the flight and hotel agents. Each specialist pulls live data through **MCP servers**, which is an open protocol for connecting LLMs to tools, so the hotel agent uses Tavily search, the flight agent uses AviationStack, and the weather agent uses a small OpenWeather server I wrote myself.

The part I'm most proud of is the **human-in-the-loop step**. Before the system commits to a final plan, it pauses and shows you a draft. You can approve it or send feedback like "add a free day." The entire workflow state is saved in PostgreSQL at that pause point, so the approval can come minutes or days later, or even after the server restarts, and the workflow picks up exactly where it stopped.

I built it with LangGraph for orchestration, FastAPI for the backend, and a lightweight web UI. I put a lot of effort into making it resilient: if an external API is down or a key is missing, the affected agent gracefully falls back to clearly-labelled general guidance instead of crashing the whole plan. It's fully containerized, has tests that run without any database or API keys, and uses locked dependencies so it builds identically everywhere.

The takeaway for me was that the agent logic is maybe a third of the work. The other two-thirds is state management, failure handling, concurrency, and making it testable.

---

## 2. Detailed Walkthrough (8–10 Minutes)

### 2.1 Problem & Stakes

Travel planning is a good testbed for multi-agent systems because it naturally decomposes into sub-problems (flights, lodging, weather, budget) that each need a different data source, and then those pieces have to be integrated into one coherent plan. A single prompt can't do this well: it hallucinates prices, it doesn't know today's weather, and it has no way to check itself.

The stakes I set for myself were engineering stakes rather than business stakes. I wanted to answer: **can I build an agentic system where a human stays in control of the final output, where one flaky external API doesn't take down the whole system, and where the code is structured well enough that I'd be comfortable handing it to a teammate?** Those are the things that separate a notebook demo from a service.

### 2.2 Constraints & Context

- **Solo project, limited budget.** I used Groq for inference because it's fast and cheap, and free-tier hosted Postgres (Render/Neon) for persistence. That pushed me toward minimizing LLM calls, which is one reason the supervisor selectively routes.
- **External APIs are unreliable and partially gated.** AviationStack's free tier doesn't return ticket prices. Tavily and OpenWeather need keys. I had to design for "the data may not be there."
- **Long-running requests.** A full plan takes many seconds of LLM and tool calls. A naïve FastAPI implementation would block the event loop and make the server unresponsive to everyone else.
- **Human approval spans HTTP requests.** The pause between "here's your draft" and "approved" can't live in process memory. It needs durable state keyed by something the client can hand back.
- **Windows dev environment quirks.** Corporate certificate stores caused SSL failures in subprocesses, which is why the app points HTTPS clients at the certifi bundle at startup.
- **It started as a prototype.** Version 1 was essentially a single script with module-level globals and a `nest_asyncio` hack. Version 2 was a deliberate restructure into a proper package.

### 2.3 Approach & Key Decisions

**Architecture in one sentence:** browser → FastAPI → `TravelPlanner` facade → LangGraph graph → (PostgreSQL for checkpoints, MCP servers for tools).

The layers are strictly one-directional: API → Application → Domain (agents) → Infrastructure. Nothing imports upward, and nothing connects to anything at import time.

**Decision 1: LangGraph over a hand-rolled agent loop or a chain framework.**
I needed three things: explicit control over routing, durable state, and a first-class pause/resume primitive. LangGraph gives me a typed `StateGraph`, conditional edges, and `interrupt()` with pluggable checkpointers. Writing that myself would have meant reinventing checkpoint serialization and resume semantics. Frameworks like plain LangChain chains don't have the pause concept at all.

**Decision 2: A supervisor that routes, with a guardrail in front of it.**
The supervisor node makes two LLM calls. First a guardrail: "is this a travel request?" Second the router: "which specialists are needed, and what constraints (destination, origin, duration, budget, travel style) can you extract?" Both return strict JSON. The routing is data-driven: the supervisor writes a `selected_agents` list into state, and there's a canonical `AGENT_ORDER` list. Each specialist's conditional edge simply finds the *next selected agent* in that order, or falls through to the itinerary agent. Unselected agents are skipped at zero cost. The itinerary agent is always force-included because it's the integration point.

**Decision 3: Fail open on the guardrail and supervisor.**
This was a conscious trade-off. A guardrail is a safety feature, but if the model returns malformed JSON and I block the request, I've turned a safety feature into an availability bug. So on parse failure the guardrail allows the request and the supervisor selects the full workflow. Blocking is reserved for confident negative verdicts. I log the fallback so it's observable.

**Decision 4: MCP for tool access, with per-server isolation.**
I used the Model Context Protocol rather than writing three bespoke API clients because it standardizes tool discovery and invocation and lets me swap providers. I run three servers: Tavily over streamable HTTP, AviationStack as a stdio subprocess launched via `uvx`, and a weather server I wrote with FastMCP that wraps two OpenWeather endpoints and returns slim dictionaries. Critically, each helper loads tools from *exactly one* server per call, so a broken AviationStack subprocess can't break a Tavily request. Prerequisite checks (is the key set? is `uvx` on PATH?) raise actionable errors before any network call.

**Decision 5: Graceful degradation inside every specialist.**
Each specialist wraps its MCP calls in a try/except. On failure it writes clearly-labelled fallback text into state, for example "Live hotel search is temporarily unavailable, provide general neighbourhood guidance and label it as non-live." The downstream agents are prompted to respect those labels. The plan still completes, and the user knows which parts are live.

**Decision 6: Human-in-the-loop via `interrupt()` + PostgreSQL.**
After the itinerary agent drafts a plan, the `human_approval` node calls `interrupt()` with the draft and a question. LangGraph checkpoints the whole state to Postgres keyed by `thread_id` and returns control to the HTTP handler, which responds with `requires_approval: true`. The browser stores `thread_id` in `localStorage`. When the user hits approve or revise, `/api/travel/approve` resumes the graph with `Command(resume={"approved": ..., "feedback": ...})`. LangGraph reloads the checkpoint, `interrupt()` now *returns* the payload, and execution flows into the final agent, which is told either "preserve the approved decisions while polishing" or "apply this feedback carefully."

**Decision 7: Concurrency model.**
FastAPI endpoints are async on one event loop, but `graph.invoke()` is blocking for many seconds. So the `TravelPlanner` facade dispatches it with `asyncio.to_thread`. Inside that worker thread there's no running event loop, so the specialists call the async MCP helpers with `asyncio.run()`, giving each call a short-lived loop. That removed the `nest_asyncio` hack from v1. Each concurrent graph run borrows its own connection from a psycopg `ConnectionPool`, so the checkpointer is safe under concurrency.

**Decision 8: App factory + lifespan, no import-time side effects.**
The DB pool, checkpointer, compiled graph, and planner are created only inside FastAPI's lifespan and stored on `app.state`. The pool's `wait()` fails fast if the DB is unreachable, and pydantic-settings fails fast if required keys are missing. Importing any module is cheap and safe. This is also what makes testing trivial: tests inject a fake planner onto `app.state` before startup, and the lifespan short-circuits.

**Decision 9: Tooling for reproducibility.**
uv with a committed `uv.lock`, `src/` layout so tests import the installed package, ruff for lint/format, and a multi-stage Dockerfile that installs from the lockfile in a builder stage and runs as a non-root user with a built-in health check.

### 2.4 Evaluation & Validation

I want to be honest here: this project has **engineering validation, not a formal LLM evaluation harness.** That's a gap I'd address next (see 2.6).

What is validated:

- **API contract tests** (pytest + `TestClient`): every endpoint, every error path, the exact error shape `{"success": false, "error": ...}` that the frontend depends on, message stripping, 400 on blank input, 400 on reject-without-feedback, 422 on missing fields, 500 shape when the planner raises. These run with no DB, no LLM, no network because of the fake planner injection.
- **Routing unit tests**: pure functions. Blocked requests route to `guardrail_blocked`; the supervisor routes to the first selected agent; unselected agents are skipped; everything falls back to `itinerary_agent`.
- **Serialization unit tests**: both the "interrupted" and "completed" shapes of the graph result serialize correctly to the API contract.
- **Manual end-to-end smoke tests** via curl and the web UI, including deliberate failure injection: removing API keys to confirm each agent degrades gracefully, killing the server mid-approval to confirm the thread resumes after restart.
- **Observability**: `llm_calls` is tracked in state and returned in every response, so I can see cost per request. Supervisor reasoning and the selected-agent list are returned too, which makes routing decisions inspectable from the UI.

### 2.5 Failures & Iteration

- **`nest_asyncio` in v1.** The prototype patched the event loop so async MCP calls could run inside sync graph nodes. It worked until it didn't: hard-to-debug hangs under concurrent requests. The fix was to move the blocking graph run off the event loop with `asyncio.to_thread` and use plain `asyncio.run()` inside the thread. Cleaner, and it exposed that the real problem was mixing sync and async at the wrong boundary.
- **Single shared DB connection.** Early on the checkpointer used one connection. Two overlapping requests corrupted each other's checkpoint writes. Switching to a psycopg `ConnectionPool` fixed it and also gave me fail-fast startup via `pool.wait()`.
- **Guardrail as an outage.** An early version treated any JSON parse error as "blocked." A model formatting hiccup made the app refuse every request for a while. That's where the fail-open policy came from.
- **Cross-server MCP failures.** Loading all tools from all servers at once meant a missing `uvx` on PATH broke weather and hotel lookups too. Per-server tool loading isolated the blast radius.
- **SSL on corporate Windows.** MCP subprocesses failed TLS verification. Setting `SSL_CERT_FILE` and `REQUESTS_CA_BUNDLE` to the certifi bundle at startup fixed it for both the parent and child processes.
- **Module-level globals blocked testing.** v1 connected to Postgres at import. You couldn't even import the module in CI. The factory + lifespan pattern fixed it and made the fake-planner test strategy possible.
- **Known rough edges I haven't fixed yet** (good to volunteer before being asked): the weather agent's destination-extraction LLM call sits *outside* its try/except, so an LLM failure there would raise rather than degrade; the hotel agent increments `llm_calls` though it makes no LLM call; the Tavily key is passed as a URL query parameter, which could leak into logs; specialists run sequentially even though flight/hotel/weather are independent.

### 2.6 Outcome & Reflection

The outcome is a working, containerized, tested multi-agent service with durable human-in-the-loop approval, selective routing that saves LLM calls on narrow requests, and graceful degradation across three external providers. The frontend contract survived the entire v1→v2 restructure with zero UI changes, which I take as evidence the API boundary was drawn in the right place.

What I'd do next, in priority order: (1) an LLM evaluation harness with a golden set of prompts scoring routing accuracy, guardrail precision/recall, and itinerary quality via an LLM-as-judge; (2) parallel fan-out of the independent specialists using LangGraph's `Send` API to cut wall-clock latency by roughly half; (3) structured output via Pydantic models and Groq's JSON mode instead of my find/rfind JSON extraction; (4) a multi-round revision loop so rejected drafts go back through approval rather than straight to final; (5) tracing with LangSmith or OpenTelemetry.

---

## 3. Likely Follow-Up Questions

> Note: this isn't a model-training project, so "Data & Preprocessing" questions will really be about data *flow*: what the agents consume, how tool payloads are shaped, and how state is structured.

### Data & Preprocessing

- **Q: What data actually flows into each agent, and where does it come from?**
  - The supervisor sees only the raw user query and extracts structured `trip_constraints` (destination, origin, duration, budget, style, preferences) into state.
  - Flight agent: airport and airline catalogues from AviationStack via MCP, truncated to 3,000 characters each, plus the query. The LLM reasons over that context.
  - Hotel agent: Tavily search results for "Best hotels for <query>", passed through as-is (no LLM call in that node).
  - Weather agent: an LLM call extracts the destination city, then two MCP tools return current weather and a five-entry three-hour forecast as slim dicts I shaped in my own server.
  - Budget, itinerary, and final agents consume the accumulated results from state, so each later agent has strictly more context than the one before.

- **Q: How do you handle the LLM returning malformed JSON?**
  - A small helper finds the first `{` and last `}` and parses that slice, which tolerates preamble text and markdown fences.
  - On any exception the calling node falls open: guardrail allows, supervisor selects the full workflow, and a warning with traceback is logged.
  - I'd upgrade this to Pydantic structured output with Groq's JSON mode; I kept the simple version because fail-open made the failure cheap.

- **Q: Why truncate MCP payloads to 3,000 characters?**
  - AviationStack catalogue responses can be huge and mostly irrelevant. Truncation caps token cost and keeps the flight prompt within a sane context size.
  - It's a blunt instrument. A better approach is to filter airports by the extracted origin/destination before prompting.

- **Q: How is graph state structured?**
  - A single `TravelState` TypedDict. `messages` uses an `operator.add` reducer so it accumulates as an audit trail; every other field is last-write-wins.
  - Each node returns only the keys it changed, so nodes are decoupled and easy to unit test.

### Modeling & Architecture

- **Q: Why a supervisor pattern instead of one big prompt or a fixed pipeline?**
  - One prompt can't call tools per sub-problem and tends to hallucinate prices and weather.
  - A fixed pipeline runs every agent every time. The supervisor skips unneeded specialists, so "what's the weather in Lisbon?" costs about 4 LLM calls instead of 7.
  - It also gives me an explicit, inspectable routing decision (`supervisor_reasoning` is returned to the UI).

- **Q: Why LangGraph specifically?**
  - `interrupt()` plus pluggable checkpointers gave me durable pause/resume for free; that's the hardest part to build by hand.
  - Typed state with reducers and conditional edges made the routing data-driven and testable as pure functions.
  - Trade-off: framework lock-in and a fast-moving API surface.

- **Q: Why MCP instead of direct API clients?**
  - Standard tool discovery and invocation across providers; swapping Tavily for another search server is a config change.
  - I could reuse a community AviationStack server and write my own weather server in about 90 lines with FastMCP.
  - Cost: stdio servers are spawned as subprocesses per call in my current design, which adds latency. I'd move to long-lived sessions next.

- **Q: Walk me through the human-in-the-loop mechanics.**
  - `human_approval` node calls `interrupt(payload)`. LangGraph raises internally, checkpoints full state to Postgres under `thread_id`, and `graph.invoke()` returns with an `__interrupt__` key.
  - My serializer detects that and responds `requires_approval: true` with the draft. The HTTP request ends.
  - `/api/travel/approve` calls `graph.invoke(Command(resume={...}), config)`. LangGraph reloads the checkpoint, re-enters the node, and `interrupt()` now returns the resume payload. Execution continues to `final_agent`.
  - It survives process restarts because nothing lives in memory between the two requests.

- **Q: Why are the specialists sequential? Couldn't flight, hotel, and weather run in parallel?**
  - Yes, and they should. Budget depends on all three, but the three are independent.
  - I kept them sequential in v2 to keep routing logic simple and because `asyncio.run` per node inside a single worker thread made parallelism awkward.
  - Next step is LangGraph's `Send` API for fan-out with a join before budget, roughly halving wall-clock latency.

### Evaluation

- **Q: How do you know the supervisor routes correctly? How do you know the guardrail isn't over-blocking?**
  - Today: routing *mechanics* are unit tested; routing *decisions* are only validated manually and made inspectable via `supervisor_reasoning` in every response.
  - What I'd build: a golden set of ~100 prompts labelled with expected agents and expected guardrail verdict, run nightly, reporting routing accuracy and guardrail precision/recall.
  - Fail-open is my mitigation for over-blocking in the meantime.

- **Q: How would you evaluate itinerary quality?**
  - LLM-as-judge with a rubric: respects budget, respects duration, incorporates weather advice, honours human feedback on revision, correctly labels non-live data.
  - Pairwise comparison across model or prompt versions.
  - Track `llm_calls` and latency per run as cost metrics alongside quality.

- **Q: How do your tests run without a database or API keys?**
  - The FastAPI lifespan checks whether a planner is already on `app.state`; tests inject a deterministic `FakePlanner` before startup, so no pool, checkpointer, or graph is built.
  - Routing and serialization are pure functions tested directly.
  - This gives fast, hermetic CI. The gap is integration coverage of the real graph, which I'd add with a Postgres test container and a mocked LLM.

### Deployment & LLMOps

- **Q: How does this handle concurrent users?**
  - Each request's graph run goes to a worker thread via `asyncio.to_thread`; the event loop stays free.
  - Each run borrows its own connection from a psycopg pool (default max 5, configurable).
  - Multiple uvicorn workers each build their own pool and graph; state is in Postgres, so any worker can resume any thread.
  - Bottleneck would be Groq rate limits and thread count, not the app.

- **Q: What happens when an external API is down or a key is missing?**
  - Prerequisite check raises an actionable error ("TAVILY_API_KEY is missing. Add it to your .env file.") before any network call.
  - The specialist catches it, logs with traceback, and writes labelled fallback text; the plan completes with that section marked as non-live.
  - Missing *required* config (Groq key, DB URL) fails fast at startup, not mid-request.

- **Q: How is it deployed and configured?**
  - Multi-stage Docker: dependencies installed from `uv.lock` in a builder stage, runtime is `python:3.11-slim` as a non-root user with `uvx` copied in and a `/health` healthcheck.
  - All config via pydantic-settings from env or `.env`; `sslmode=require` is appended to the DSN automatically.
  - Same lockfile locally, in CI, and in the image.

- **Q: What would you add for observability in production?**
  - Tracing (LangSmith or OpenTelemetry) per node with token counts and latency.
  - Structured logs with `thread_id` as a correlation key.
  - Metrics: guardrail block rate, fallback rate per MCP server, approval vs. revision ratio, p95 latency per node.

### Trade-offs & Improvements

- **Q: What's the biggest weakness of the current design?**
  - No automated evaluation of LLM behaviour; correctness of routing and plan quality rests on manual testing.
  - Sequential specialists leave latency on the table.
  - Small known bugs: destination extraction outside the weather agent's try/except, hotel agent over-counting `llm_calls`, Tavily key in a URL query string.

- **Q: Why fail open on the guardrail? Isn't that a security risk?**
  - The guardrail here is a scope filter (travel vs. non-travel), not a security boundary; the downside of a false allow is a wasted LLM call, the downside of a false block is a broken product.
  - Fallbacks are logged, so a spike would be visible.
  - If the guardrail were enforcing something with real harm potential, I'd fail closed and add a retry with a repair prompt.

- **Q: How would you handle a multi-round revision loop?**
  - Currently rejection with feedback goes straight to `final_agent` once. For multiple rounds I'd add a conditional edge from `final_agent` back to `human_approval` when `approved` is false, with a max-iterations counter in state to prevent infinite loops.

- **Q: Is there any auth or ownership check on `thread_id`?**
  - No. Thread IDs are random UUIDs so they're not guessable, but anyone holding one can resume it.
  - For production I'd bind threads to an authenticated user ID in the checkpoint config and check ownership on resume.

- **Q: If you had to cut cost by half, what would you change?**
  - Use a smaller model for the guardrail and destination extraction; they're classification tasks.
  - Cache MCP results per destination for a short TTL.
  - Merge guardrail and supervisor into one structured-output call.

---

## 4. One-Paragraph Reflection

The biggest lesson from TripMate was that the agent logic is the smallest part of an agentic system; the hard, valuable work is everything around it: durable state so a human can approve a plan across requests and restarts, concurrency boundaries drawn in the right place so one slow LLM call doesn't freeze the server, and failure handling that degrades a single section rather than the whole answer. I also learned to think about guardrails as availability decisions, not just safety decisions. If I did it again, I'd build the evaluation harness *first*, a golden set of prompts scoring routing and guardrail behaviour, because right now my confidence in the LLM-driven decisions comes from manual testing rather than metrics. After that I'd parallelize the independent specialists, move to structured outputs with Pydantic, and add tracing so cost and latency per node are visible from day one.
