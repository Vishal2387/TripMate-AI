"""Specialist agents: flights, hotels, weather, and budget.

These nodes run inside a worker thread (the graph is invoked with
``asyncio.to_thread``), so each MCP call gets its own short-lived event
loop via ``asyncio.run`` without blocking the FastAPI event loop.
"""

import asyncio
import logging

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from tripmate.agents import prompts
from tripmate.agents.llm import get_llm
from tripmate.agents.state import TravelState
from tripmate.services import mcp

logger = logging.getLogger(__name__)

MCP_PAYLOAD_CHAR_LIMIT = 3000


def extract_destination(query: str) -> str:
    """Ask the LLM for the destination city or country in the request."""
    response = get_llm().invoke(
        prompts.DESTINATION_EXTRACTION_PROMPT.format(query=query)
    )
    destination = str(response.content).strip()

    if not destination:
        raise ValueError("The destination could not be extracted.")

    return destination


def flight_agent(state: TravelState) -> dict:
    query = state["user_query"]

    try:
        airports = asyncio.run(mcp.aviation_call("list_airports"))
        airlines = asyncio.run(mcp.aviation_call("list_airlines"))

        prompt = prompts.FLIGHT_AGENT_PROMPT.format(
            query=query,
            airport_data=str(airports)[:MCP_PAYLOAD_CHAR_LIMIT],
            airline_data=str(airlines)[:MCP_PAYLOAD_CHAR_LIMIT],
        )

        response = get_llm().invoke(
            [
                SystemMessage(content=prompts.FLIGHT_AGENT_SYSTEM),
                HumanMessage(content=prompt),
            ]
        )
        flight_results = response.content
    except Exception as exc:
        logger.error("Flight agent MCP error", exc_info=True)
        flight_results = f"Flight information unavailable: {exc}"

    return {
        "flight_results": flight_results,
        "messages": [AIMessage(content="Flight recommendations generated.")],
        "llm_calls": state.get("llm_calls", 0) + 1,
    }


def hotel_agent(state: TravelState) -> dict:
    query = f"Best hotels for {state['user_query']}"

    try:
        hotel_results = asyncio.run(mcp.tavily_search(query))
    except Exception:
        logger.error("Hotel agent MCP error", exc_info=True)
        hotel_results = (
            "Live hotel search is temporarily unavailable. "
            "Provide general accommodation and neighborhood guidance based "
            "on the destination and clearly label it as non-live advice."
        )

    return {
        "hotel_results": hotel_results,
        "messages": [AIMessage(content="Hotel information processed.")],
        "llm_calls": state.get("llm_calls", 0) + 1,
    }


def weather_agent(state: TravelState) -> dict:
    city = extract_destination(state["user_query"])

    try:
        weather_data = asyncio.run(mcp.current_weather(city))
        forecast_data = asyncio.run(mcp.weather_forecast(city))

        weather_results = (
            f"\nCurrent Weather:\n{weather_data}\n\nForecast:\n{forecast_data}\n"
        )
    except Exception:
        logger.error("Weather agent MCP error", exc_info=True)
        weather_results = (
            f"Live weather information for {city} is temporarily unavailable. "
            "Give general seasonal guidance and advise the traveler to verify "
            "the forecast before departure."
        )

    return {
        "weather_results": weather_results,
        "messages": [AIMessage(content="Weather information processed.")],
    }


def budget_agent(state: TravelState) -> dict:
    prompt = prompts.BUDGET_AGENT_PROMPT.format(
        query=state["user_query"],
        trip_constraints=state.get("trip_constraints", {}),
        flight_results=state.get("flight_results", ""),
        hotel_results=state.get("hotel_results", ""),
        weather_results=state.get("weather_results", ""),
    )

    response = get_llm().invoke(
        [
            SystemMessage(content=prompts.BUDGET_AGENT_SYSTEM),
            HumanMessage(content=prompt),
        ]
    )

    return {
        "budget_results": response.content,
        "messages": [AIMessage(content="Budget assessment generated.")],
        "llm_calls": state.get("llm_calls", 0) + 1,
    }
