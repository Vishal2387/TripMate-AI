"""FastAPI application factory and lifespan wiring."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from tripmate import __version__
from tripmate.api.routes import router
from tripmate.config import configure_ssl_certificates, get_settings
from tripmate.logging_config import configure_logging

logger = logging.getLogger(__name__)

WEB_DIR = Path(__file__).resolve().parent / "web"

templates = Jinja2Templates(directory=str(WEB_DIR / "templates"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Tests may inject a planner before startup; skip infrastructure then.
    if getattr(app.state, "planner", None) is not None:
        yield
        return

    from tripmate.agents.graph import build_travel_graph
    from tripmate.agents.runner import TravelPlanner
    from tripmate.services.checkpointer import (
        create_checkpointer,
        create_connection_pool,
    )

    settings = get_settings()
    pool = create_connection_pool(settings)
    try:
        checkpointer = create_checkpointer(pool)
        app.state.planner = TravelPlanner(build_travel_graph(checkpointer))
        logger.info("Travel planner ready")
        yield
    finally:
        pool.close()
        logger.info("PostgreSQL connection pool closed")


def create_app() -> FastAPI:
    configure_ssl_certificates()
    configure_logging(get_settings().log_level if _settings_available() else "INFO")

    app = FastAPI(
        title="TripMate AI",
        description=(
            "LangGraph Multi-Agent Travel Planner with Supervisor, Guardrails, "
            "Human-in-the-Loop, and FastAPI Frontend"
        ),
        version=__version__,
        lifespan=lifespan,
    )

    app.mount(
        "/static",
        StaticFiles(directory=str(WEB_DIR / "static")),
        name="static",
    )
    app.include_router(router)

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def home(request: Request):
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={},
        )

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon():
        return JSONResponse(content={})

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        # The frontend expects {"success": false, "error": "..."} on failures.
        return JSONResponse(
            status_code=exc.status_code,
            content={"success": False, "error": str(exc.detail)},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ):
        return JSONResponse(
            status_code=422,
            content={"success": False, "error": str(exc.errors())},
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        logger.exception("Unhandled server error")
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": "Internal server error."},
        )

    return app


def _settings_available() -> bool:
    """True when required environment variables are present.

    Allows the module to be imported (docs builds, tests) without a
    fully configured environment; startup still fails fast in lifespan.
    """
    try:
        get_settings()
        return True
    except Exception:
        return False


app = create_app()
