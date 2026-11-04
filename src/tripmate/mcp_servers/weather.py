"""OpenWeather MCP server exposing current weather and forecast tools.

Launched as a stdio subprocess by the MCP client
(``python -m tripmate.mcp_servers.weather``); the OPENWEATHER_API_KEY is
passed through the subprocess environment.
"""

import os
from typing import Any

import requests
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Weather MCP Server")

OPENWEATHER_BASE_URL = "https://api.openweathermap.org/data/2.5"
REQUEST_TIMEOUT_SECONDS = 20
FORECAST_ENTRIES = 5


def _get_api_key() -> str:
    api_key = os.getenv("OPENWEATHER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENWEATHER_API_KEY is missing from the environment.")
    return api_key


def _request_json(url: str, params: dict[str, Any]) -> dict[str, Any]:
    try:
        response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        details = ""
        failed_response = getattr(exc, "response", None)
        if failed_response is not None:
            details = f" Response: {failed_response.text[:500]}"
        raise RuntimeError(f"OpenWeather request failed: {exc}.{details}") from exc


@mcp.tool()
def get_current_weather(city: str) -> dict[str, Any]:
    """Return the current weather for a city."""
    city = city.strip()
    if not city:
        raise ValueError("city cannot be empty")

    data = _request_json(
        f"{OPENWEATHER_BASE_URL}/weather",
        {"q": city, "appid": _get_api_key(), "units": "metric"},
    )

    return {
        "city": data["name"],
        "temperature_c": data["main"]["temp"],
        "feels_like_c": data["main"]["feels_like"],
        "humidity": data["main"]["humidity"],
        "condition": data["weather"][0]["description"],
        "wind_speed": data["wind"]["speed"],
    }


@mcp.tool()
def get_forecast(city: str) -> dict[str, Any]:
    """Return the first five three-hour forecast entries for a city."""
    city = city.strip()
    if not city:
        raise ValueError("city cannot be empty")

    data = _request_json(
        f"{OPENWEATHER_BASE_URL}/forecast",
        {"q": city, "appid": _get_api_key(), "units": "metric"},
    )

    forecast = [
        {
            "datetime": item["dt_txt"],
            "temperature_c": item["main"]["temp"],
            "condition": item["weather"][0]["description"],
        }
        for item in data.get("list", [])[:FORECAST_ENTRIES]
    ]

    return {
        "city": data.get("city", {}).get("name", city),
        "forecast": forecast,
    }


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
