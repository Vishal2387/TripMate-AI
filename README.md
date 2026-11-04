# TripMate AI

A multi-agent travel-planning assistant built with **LangGraph** and **MCP**: a supervisor agent routes each request to specialist agents (flights, hotels, weather, budget), an input guardrail filters non-travel requests, and every draft itinerary pauses for **human-in-the-loop** approval before the final plan is generated. Served through a FastAPI backend with a lightweight web UI.

## Key ideas

- Multi-agent coordination using LangGraph and MCP
- Supervisor agent that selects only the specialists a request needs
- Input guardrail to validate user requests (fails open on model errors)
- Human-in-the-loop approval via LangGraph `interrupt` + PostgreSQL checkpointing

## Project structure

```
├── pyproject.toml              # Project metadata, dependencies, tooling (uv-managed)
├── uv.lock                     # Locked, reproducible dependency versions
├── .env.example                # Template for required environment variables
├── Dockerfile                  # Multi-stage uv build, non-root runtime
├── src/tripmate/
│   ├── app.py                  # FastAPI app factory + lifespan (DB pool, graph)
│   ├── __main__.py             # Dev server entrypoint (uv run tripmate)
│   ├── config.py               # Pydantic settings loaded from env/.env
│   ├── logging_config.py       # Central logging setup
│   ├── api/
│   │   ├── routes.py           # /api/travel, /api/travel/approve, /health
│   │   └── schemas.py          # Request/response models
│   ├── agents/
│   │   ├── state.py            # TravelState + agent registry
│   │   ├── llm.py              # Groq LLM factory + JSON helpers
│   │   ├── prompts.py          # All prompt templates
│   │   ├── supervisor.py       # Guardrail + supervisor routing
│   │   ├── specialists.py      # Flight, hotel, weather, budget agents
│   │   ├── review.py           # Itinerary draft, HITL approval, final agent
│   │   ├── graph.py            # LangGraph wiring and conditional routing
│   │   └── runner.py           # TravelPlanner async facade + serialization
│   ├── services/
│   │   ├── mcp.py              # MCP client (Tavily, AviationStack, weather)
│   │   └── checkpointer.py     # PostgreSQL connection pool + checkpointer
│   ├── mcp_servers/
│   │   └── weather.py          # Bundled OpenWeather MCP server (stdio)
│   └── web/                    # Templates and static assets
└── tests/                      # API contract + routing unit tests
```

## Prerequisites

- [uv](https://docs.astral.sh/uv/getting-started/installation/) (manages Python and dependencies; installs Python 3.11 automatically)
- A PostgreSQL database (e.g. a free [Render](https://render.com) or [Neon](https://neon.tech) instance) for LangGraph checkpointing
- API keys: [Groq](https://console.groq.com) (required), plus [Tavily](https://tavily.com), [AviationStack](https://aviationstack.com), and [OpenWeather](https://openweathermap.org/api) for live data (agents degrade gracefully without them)

## Quick start

```bash
# 1. Install dependencies (creates .venv and installs everything from uv.lock)
uv sync

# 2. Configure secrets
cp .env.example .env      # then fill in your keys (Windows: copy .env.example .env)

# 3. Run the development server
uv run tripmate
```

Open http://127.0.0.1:8000 to use the web UI, or http://127.0.0.1:8000/docs for the interactive API docs.

Alternative ways to run:

```bash
uv run python -m tripmate                          # same as uv run tripmate
uv run uvicorn tripmate.app:app --reload           # direct uvicorn
```

## Configuration

All settings come from environment variables or a `.env` file (see `.env.example`):

| Variable | Required | Description |
|---|---|---|
| `GROQ_API_KEY` | Yes | LLM used by every agent |
| `DATABASE_URL` | Yes | PostgreSQL DSN for checkpointing (`sslmode=require` auto-appended) |
| `TAVILY_API_KEY` | For live hotels | Tavily MCP search |
| `AVIATION_STACK_API_KEY` | For live flights | AviationStack MCP (launched via `uvx`) |
| `OPENWEATHER_API_KEY` | For live weather | Bundled weather MCP server |
| `TRIPMATE_HOST` / `TRIPMATE_PORT` | No | Dev server bind (default `127.0.0.1:8000`) |
| `TRIPMATE_LOG_LEVEL` | No | Default `INFO` |
| `TRIPMATE_GROQ_MODEL` | No | Default `llama-3.3-70b-versatile` |

## API

- `POST /api/travel` — start or continue a planning thread. Body: `{ "message": "<prompt>", "thread_id": "optional" }`. Returns the draft itinerary with `requires_approval: true`.
- `POST /api/travel/approve` — resume a paused thread. Body: `{ "thread_id": "<id>", "approved": true|false, "feedback": "required when rejecting" }`.
- `GET /health` — health check and feature list.

Error responses always have the shape `{ "success": false, "error": "<message>" }`.

## Development

```bash
uv sync                 # includes the dev group (pytest, ruff, httpx)
uv run pytest           # run the test suite
uv run ruff check .     # lint
uv run ruff format .    # format
```

Tests inject a fake planner before startup, so no database or API keys are needed to run them.

Adding a dependency:

```bash
uv add <package>            # runtime dependency
uv add --dev <package>      # dev-only dependency
```

## Docker

```bash
docker build -t tripmate-ai .
docker run --rm -p 8000:8000 --env-file .env tripmate-ai
```

The image is a multi-stage build: dependencies are installed from `uv.lock` with uv in a builder stage, and the runtime stage runs as a non-root user with `uvx` available for the AviationStack MCP server.

## Architecture notes

- **No import-time side effects.** The database pool, checkpointer, and compiled graph are created in the FastAPI lifespan and closed on shutdown.
- **Event loop safety.** Graph execution is blocking (LLM + MCP calls), so the API dispatches it to a worker thread with `asyncio.to_thread`; each MCP call runs on its own short-lived event loop inside that thread (no `nest_asyncio`).
- **HITL flow.** `itinerary_agent` → `human_approval` calls LangGraph `interrupt()`, persisting the thread in PostgreSQL until `/api/travel/approve` resumes it with a `Command`.
- **Resilience.** The guardrail and supervisor fail open (full workflow fallback); each specialist catches MCP failures and returns clearly-labeled non-live guidance instead of crashing the run.

## License

See [LICENSE](LICENSE).
