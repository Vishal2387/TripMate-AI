"""MCP client helpers for Tavily search, AviationStack, and the weather server.

Each helper loads tools from exactly one MCP server so a broken weather or
AviationStack server cannot break an unrelated Tavily request.
"""

import logging
import os
import shutil
import sys
from functools import lru_cache
from typing import Any

from langchain_mcp_adapters.client import MultiServerMCPClient

from tripmate.config import get_settings

logger = logging.getLogger(__name__)


def _subprocess_env(**updates: str | None) -> dict[str, str]:
    """Preserve the current environment and add MCP API keys."""
    env = os.environ.copy()
    for key, value in updates.items():
        if value:
            env[key] = value
    return env


@lru_cache
def get_mcp_client() -> MultiServerMCPClient:
    settings = get_settings()

    return MultiServerMCPClient(
        {
            "tavily": {
                "transport": "streamable_http",
                "url": (
                    "https://mcp.tavily.com/mcp/"
                    f"?tavilyApiKey={settings.tavily_api_key}"
                ),
            },
            "aviationstack": {
                "transport": "stdio",
                "command": shutil.which("uvx") or "uvx",
                "args": ["aviationstack-mcp"],
                "env": _subprocess_env(
                    AVIATION_STACK_API_KEY=settings.aviation_stack_api_key,
                ),
            },
            "weather": {
                "transport": "stdio",
                # Run the bundled weather MCP server with the active interpreter.
                "command": sys.executable,
                "args": ["-m", "tripmate.mcp_servers.weather"],
                "env": _subprocess_env(
                    OPENWEATHER_API_KEY=settings.openweather_api_key,
                ),
            },
        }
    )


def _check_server_prerequisites(server_name: str) -> None:
    settings = get_settings()

    if server_name == "tavily" and not settings.tavily_api_key:
        raise RuntimeError("TAVILY_API_KEY is missing. Add it to your .env file.")

    if server_name == "aviationstack":
        if not settings.aviation_stack_api_key:
            raise RuntimeError(
                "AVIATION_STACK_API_KEY is missing. Add it to your .env file."
            )
        if shutil.which("uvx") is None:
            raise RuntimeError(
                "uvx was not found on PATH. Install uv (https://docs.astral.sh/uv/) "
                "and reopen the terminal."
            )

    if server_name == "weather" and not settings.openweather_api_key:
        raise RuntimeError("OPENWEATHER_API_KEY is missing. Add it to your .env file.")


async def _get_server_tool(server_name: str, tool_name: str):
    """Load one tool from one MCP server."""
    _check_server_prerequisites(server_name)

    tools = await get_mcp_client().get_tools(server_name=server_name)
    tool = next((item for item in tools if item.name == tool_name), None)

    if tool is None:
        available = ", ".join(sorted(item.name for item in tools)) or "none"
        raise RuntimeError(
            f"MCP tool '{tool_name}' was not found on server '{server_name}'. "
            f"Available tools: {available}"
        )

    return tool


async def tavily_search(query: str) -> Any:
    tool = await _get_server_tool("tavily", "tavily_search")
    return await tool.ainvoke({"query": query})


async def aviation_call(
    tool_name: str,
    tool_args: dict[str, Any] | None = None,
) -> Any:
    tool = await _get_server_tool("aviationstack", tool_name)
    return await tool.ainvoke(tool_args or {})


async def current_weather(city: str) -> Any:
    tool = await _get_server_tool("weather", "get_current_weather")
    return await tool.ainvoke({"city": city})


async def weather_forecast(city: str) -> Any:
    tool = await _get_server_tool("weather", "get_forecast")
    return await tool.ainvoke({"city": city})


async def check_all_servers() -> None:
    """Diagnostics: test every MCP server independently."""
    for server_name in ("tavily", "aviationstack", "weather"):
        try:
            tools = await get_mcp_client().get_tools(server_name=server_name)
            names = ", ".join(tool.name for tool in tools) or "no tools"
            logger.info("%s: OK -> %s", server_name, names)
        except Exception as exc:
            logger.error("%s: FAILED -> %s: %s", server_name, type(exc).__name__, exc)
