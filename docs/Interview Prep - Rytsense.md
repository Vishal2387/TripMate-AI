# TripMate AI — Interview Cheat Sheet (Rytsense, Agentic AI Engineer)

JD match: multi-agent coordination, LangGraph, MCP, human-in-the-loop, guardrails, retries/fallbacks, API integration.

---

## 1. 30-second pitch (say this first)

> "TripMate AI is a multi-agent travel planner I built with LangGraph and MCP. A **supervisor agent** first checks the request with a **guardrail**, then decides which **specialist agents** are needed — flights, hotels, weather, budget. Each specialist calls real tools through **MCP servers**. An **itinerary agent** merges the results into a draft, and the graph **pauses for human approval** before a **final agent** produces the plan. State is saved in **PostgreSQL**, so a paused run can resume later. It's served through **FastAPI**."

---

## 2. The flow (draw this on paper/whiteboard)

```
User request
    ↓
Supervisor  (guardrail → pick agents + extract trip constraints)
    ↓ (not travel? → blocked, END)
Flight → Hotel → Weather → Budget      (only the ones selected)
    ↓
Itinerary agent  (merges all results into a draft)
    ↓
Human approval   ← graph PAUSES here (interrupt)
    ↓ resume with approve / feedback
Final agent  → answer
```

## 3. Key pieces in simple words

| Piece | What it does | File |
|---|---|---|
| **Shared state** (`TravelState`) | One dict all agents read/write: query, selected agents, each agent's results, approval | `agents/state.py` |
| **Guardrail** | LLM check: is this a travel request? Blocks if not. Fails open on error | `agents/supervisor.py` |
| **Supervisor** | LLM returns JSON: which agents to run + trip constraints. Fallback = run all agents | `agents/supervisor.py` |
| **Specialists** | Each calls MCP tools (Tavily, AviationStack, own weather server), then LLM summarises | `agents/specialists.py` |
| **Conditional edges** | Code decides the next node from `selected_agents` | `agents/graph.py` |
| **HITL** | `interrupt()` pauses; `Command(resume=...)` continues | `agents/review.py`, `runner.py` |
| **Checkpointer** | PostgreSQL stores state per `thread_id` so pause/resume survives | `services/checkpointer.py` |
| **MCP** | Standard way to plug tools in. 3 servers: Tavily (HTTP), AviationStack (stdio), my own weather server | `services/mcp.py`, `mcp_servers/weather.py` |
| **API** | `POST /api/travel` starts, `POST /api/travel/approve` resumes | `api/routes.py` |

---

## 3b. MCP tools — how they are connected (simple version)

**What is MCP?** A standard "plug" for tools. My app is the **client**. Each tool provider (Tavily, AviationStack, weather) is a **server**. The agent just says "call this tool" and doesn't care where the tool lives.

**Two ways the client talks to a server:**
- **HTTP** = the server is online somewhere, I call its URL.
- **stdio** = my app starts the server as a small program on my own machine and talks to it directly. No internet or port needed.

| Tool | How connected | What it gives | Used by |
|---|---|---|---|
| **Tavily** | HTTP (hosted by Tavily, URL + API key) | Web search | Hotel agent |
| **AviationStack** | stdio (my app runs `uvx aviationstack-mcp`) | List of airports and airlines | Flight agent |
| **Weather (I built it)** | stdio (my app runs `python -m tripmate.mcp_servers.weather`) | Current weather + short forecast | Weather agent |

API keys for the stdio servers are handed over as environment variables when they start.

**How AviationStack works (simple):**
- **AviationStack** = a website/API (aviationstack.com) that gives flight data (airports, airlines, flights) with an API key.
- **`aviationstack-mcp`** = a ready-made third-party package that wraps that API as MCP tools (`list_airports`, `list_airlines`). I didn't write it.
- My app runs `uvx aviationstack-mcp` (uvx downloads and runs it), talks to it over stdio, and passes my key as `AVIATION_STACK_API_KEY`.
- Flight agent calls the tools → package calls the AviationStack API → data goes to the LLM → flight recommendations.
- **Say in interview:** "AviationStack is a flight-data API. I used an existing MCP server for it, launched it as a local process with the key in the environment, and called its tools. For weather I wrote my own MCP server the same way."
- I haven't read its source, so don't claim its internals.

**One weather call, step by step:**
1. The agent finds the city from the user's request.
2. The app starts my weather server and asks "what tools do you have?"
3. It calls `get_current_weather(city)`.
4. My server calls the OpenWeather website and sends back only the useful bits (temperature, humidity, condition, wind).
5. The agent gives this to the LLM, which writes the weather advice into the shared state.

**My own server:** I wrote it with `FastMCP`. Put `@mcp.tool()` on a normal Python function and it becomes a tool; the docstring becomes its description.

**Why it is built this way (say these):**
- One server per call, so if one breaks the others still work.
- If a tool fails, the agent says "live data unavailable" and the plan still finishes.
- Keys come from environment variables, never in code.
- Tool output is cut to 3000 characters to save tokens.

**Limits (be honest):** tools are called from fixed code, the LLM doesn't pick them; every call starts a fresh connection; the flight agent only lists airports/airlines, not live flights.

**Q: Why stdio for some and HTTP for Tavily?**
Tavily already runs its own online server, so HTTP. The other two are local programs, so stdio is simplest. In production I'd host the weather server online so it can be shared.

**Q: Why build your own MCP server?**
No ready weather server fit, and it shows I understand both sides: making tools and using them.

**Q: MCP vs normal function calling?**
Function calling = how the LLM asks for a tool. MCP = a standard way to package and find tools, so the same server works in any app.

---

## 4. Likely questions & short answers

**Q: Why multi-agent instead of one big prompt?**
Each agent has one job, one small prompt and its own tools, so it's easier to debug, test and change. A single prompt with all tools gets confused and costs more tokens.

**Q: How do the agents communicate?**
Through the shared LangGraph state. An agent writes e.g. `flight_results`; the itinerary agent later reads all result fields. No agent calls another directly.

**Q: What does the supervisor do? Is routing hard-coded?**
The LLM decides *which* specialists are needed (e.g. "just weather" skips flights). Then plain Python conditional edges follow that list in a fixed order. So: LLM decides *what*, code controls *how* — predictable and safe.

**Q: How did you implement human-in-the-loop?**
Itinerary agent drafts → `human_approval` node calls `interrupt()` → graph stops and the draft goes to the UI. User approves or sends feedback → API calls `Command(resume={approved, feedback})` with the same `thread_id` → final agent applies the feedback.

**Q: What if the server restarts while waiting for approval?**
PostgreSQL checkpointer saved the state under `thread_id`, so the run resumes from the pause point. In-memory would lose it.

**Q: What is MCP and why use it?**
Model Context Protocol — a standard interface for tools. I can swap or add tools (Tavily, AviationStack) without rewriting agent code, and I wrote one MCP server myself (weather) to show both client and server sides.

**Q: How do you handle failures / make it reliable?**
- Each specialist has try/except → returns a labelled "unavailable, general advice" fallback instead of crashing the graph.
- Supervisor parse fails → fallback to running all agents.
- Guardrail errors → fail open (don't block real users because of a JSON glitch).
- Each MCP server is loaded separately, so one broken server doesn't break others.
- Tool output is truncated (3000 chars) to control tokens.

**Q: Guardrails?**
Input guardrail on the supervisor blocks non-travel requests before any tool or cost is spent. Plus HITL as an output-side safety check.

**Q: How do you track cost/latency?**
I count LLM calls per run in state (`llm_calls`). *(Honest gap: no token/latency dashboard yet — I'd add LangSmith or Langfuse.)*

**Q: How would you evaluate it?**
Be honest: I have routing unit tests and API tests, not full evals yet. Plan:
1. Test set of ~30 queries with expected agents → measure supervisor routing accuracy.
2. LLM-as-judge or rubric for itinerary quality (uses weather? respects budget?).
3. Track guardrail false-positive/negative rate, latency, cost per run.

**Q: How would you take this to production?**
- Run specialists **in parallel** (flights/hotels/weather are independent) — cuts latency.
- Retries with backoff + timeouts on MCP calls; cache weather/search.
- Tracing (LangSmith), evals in CI, rate limits, secrets manager, auth on API.
- Persistent session store + approval timeouts.
- Structured outputs (Pydantic) instead of parsing JSON from text.

**Q: What would you improve / what are the limits?** *(good to say proactively)*
- Specialists run **sequentially**, not in parallel.
- Supervisor is a one-shot planner; it doesn't re-plan if a specialist fails.
- Only one revision round after feedback (no loop back to itinerary).
- Not deployed to real users — it's a portfolio/learning project.

**Q: Why LangGraph, not CrewAI/AutoGen?**
I needed explicit control: conditional routing, state, pause/resume and checkpointing. LangGraph gives a graph with durable state; role-based frameworks hide the control flow.

**Q: Why Groq?**
Fast and cheap inference for a multi-call workflow. LLM is behind one factory (`llm.py`), so switching to Claude/GPT is a one-line config change.

**Q: Hardest problem you solved?**
Async MCP calls inside sync LangGraph nodes inside FastAPI. Solution: run the graph via `asyncio.to_thread` and use a short-lived `asyncio.run` per MCP call, so the web server's event loop is never blocked.

---

## 5. Be careful with (JD honesty)

- JD says **3+ years LangGraph** — don't claim it. Say: *"I've built LangGraph multi-agent workflows hands-on, including supervisor routing, interrupts and checkpointing, and I learn fast."*
- JD bonus is "multi-agent **in production**" — say this is a **self-built, end-to-end project**, and then show you know what production needs (list above).
- Strong points to stress: **MCP (client + own server), HITL, guardrails, graceful degradation, Postgres checkpointing.**

## 6. One-line closers

- "I design agents so they fail safely — fallbacks everywhere, human approval before the final answer."
- "Next step I'd add evals and parallel execution — that's what separates a demo from production."
