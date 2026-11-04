# How to Run TripMate AI

This guide covers running the app in **development** and **production**, plus prerequisites, configuration, and troubleshooting.

---

## 1. Prerequisites

| Requirement | Why | Check |
|---|---|---|
| [uv](https://docs.astral.sh/uv/getting-started/installation/) | Manages Python + dependencies; also provides `uvx` used by the AviationStack MCP server | `uv --version` |
| PostgreSQL database | LangGraph checkpointing (pauses/resumes the human-approval step). A free hosted instance (Render, Neon, Supabase) works | can connect with the DSN |
| Groq API key | Powers every LLM agent — **required** | https://console.groq.com |
| Tavily / AviationStack / OpenWeather keys | Live hotel / flight / weather data — *optional* (agents fall back to non-live guidance) | see `.env.example` |

> You do **not** need to install Python yourself — uv reads `.python-version` (3.11) and downloads it automatically.

## 2. Configuration

```bash
# Windows
copy .env.example .env
# macOS/Linux
cp .env.example .env
```

Then edit `.env` and fill in at minimum:

```env
GROQ_API_KEY=gsk_...
DATABASE_URL=postgresql://user:password@host:5432/dbname
```

`sslmode=require` is appended to `DATABASE_URL` automatically if missing. All other settings (`TRIPMATE_HOST`, `TRIPMATE_PORT`, `TRIPMATE_LOG_LEVEL`, `TRIPMATE_GROQ_MODEL`, pool sizes) have sensible defaults — see `.env.example`.

---

## 3. Development

```bash
# 1. Install everything (creates .venv from uv.lock, includes dev tools)
uv sync

# 2. Start the dev server (auto-reloads on code changes)
uv run tripmate
```

Then open:

- **Web UI:** http://127.0.0.1:8000
- **Interactive API docs (Swagger):** http://127.0.0.1:8000/docs
- **Health check:** http://127.0.0.1:8000/health

Equivalent ways to start the dev server:

```bash
uv run python -m tripmate                 # same entrypoint
uv run uvicorn tripmate.app:app --reload  # uvicorn directly
```

### Development tasks

```bash
uv run pytest             # run the test suite (no DB/keys needed)
uv run ruff check .       # lint
uv run ruff format .      # auto-format
uv add <package>          # add a runtime dependency
uv add --dev <package>    # add a dev-only dependency
uv lock --upgrade         # refresh locked dependency versions
```

### What happens at startup (dev and prod)

1. `create_app()` builds the FastAPI app (cheap — no external connections).
2. On startup, the **lifespan** opens the Postgres connection pool (fails fast if unreachable), runs the checkpointer setup (creates tables if missing), compiles the LangGraph workflow, and stores the `TravelPlanner` on `app.state`.
3. On shutdown the pool is closed cleanly.

---

## 4. Production

### Option A — Docker (recommended)

The `Dockerfile` is a multi-stage uv build: dependencies are installed from `uv.lock` in a builder stage; the runtime stage runs as a **non-root user**, includes `uvx` for the AviationStack MCP server, and has a built-in `/health` healthcheck.

```bash
# Build
docker build -t tripmate-ai .

# Run (secrets come from your .env file — never baked into the image)
docker run --rm -p 8000:8000 --env-file .env tripmate-ai
```

The container listens on `0.0.0.0:8000`. Check `docker ps` for health status (`healthy` after ~15s).

Example `docker-compose.yml` if you prefer compose:

```yaml
services:
  tripmate:
    build: .
    ports:
      - "8000:8000"
    env_file: .env
    restart: unless-stopped
```

### Option B — Bare metal / VM with uv

```bash
uv sync --no-dev          # install runtime dependencies only
uv run uvicorn tripmate.app:app --host 0.0.0.0 --port 8000 --workers 2
```

Production notes:

- **No `--reload`** in production — that's a dev-only feature.
- **Workers:** each uvicorn worker builds its own DB pool and graph. `--workers 2` is a good start; scale with CPU/memory. Thread safety is handled (each request runs the graph on its own pooled DB connection).
- **Process manager:** run under systemd, supervisor, or your platform's runner so the process restarts on failure. Minimal systemd unit:

  ```ini
  [Service]
  WorkingDirectory=/opt/tripmate-ai
  ExecStart=/usr/local/bin/uv run uvicorn tripmate.app:app --host 0.0.0.0 --port 8000
  EnvironmentFile=/opt/tripmate-ai/.env
  Restart=always
  ```

- **Reverse proxy:** put nginx/Caddy/a load balancer in front for TLS; point its health probe at `GET /health`.

### Option C — PaaS (Render, Railway, Fly.io, …)

Point the platform at the repo — it will detect the `Dockerfile`. Set the environment variables from `.env.example` in the platform's dashboard (never commit `.env`). The container's port is `8000`.

---

## 5. Smoke test

With the server running:

```bash
curl http://127.0.0.1:8000/health
# {"status":"ok","message":"TripMate AI API is running","features":[...]}

curl -X POST http://127.0.0.1:8000/api/travel \
  -H "Content-Type: application/json" \
  -d '{"message": "Plan a 5 day trip to Japan under $3000"}'
# -> returns a draft with "requires_approval": true and a "thread_id"

curl -X POST http://127.0.0.1:8000/api/travel/approve \
  -H "Content-Type: application/json" \
  -d '{"thread_id": "<thread_id from above>", "approved": true}'
# -> returns the final plan
```

---

## 6. Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| Startup crash: `GROQ_API_KEY ... Field required` | `.env` missing or key not set — copy `.env.example` and fill it in |
| Startup hangs then fails on pool | `DATABASE_URL` wrong or DB unreachable; verify you can connect with `psql` |
| Flight agent always falls back | `AVIATION_STACK_API_KEY` missing, or `uvx` not on PATH (install uv, reopen terminal) |
| Hotel/weather agents fall back | `TAVILY_API_KEY` / `OPENWEATHER_API_KEY` missing — this is by design (graceful degradation) |
| SSL certificate errors on corporate Windows | Already mitigated: the app points HTTP clients at the `certifi` bundle at startup |
| Port already in use | Set `TRIPMATE_PORT` in `.env`, or pass `--port` to uvicorn |
