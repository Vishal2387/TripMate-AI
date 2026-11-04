"""Shared graph state and agent registry."""

import operator
from typing import Annotated, Any, TypedDict

from langchain_core.messages import AnyMessage


class TravelState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], operator.add]
    user_query: str

    # Supervisor + guardrail state
    guardrail_allowed: bool
    guardrail_reason: str
    selected_agents: list[str]
    trip_constraints: dict[str, Any]
    supervisor_reasoning: str

    # Specialist results
    flight_results: str
    hotel_results: str
    weather_results: str
    budget_results: str
    itinerary: str

    # Human-in-the-loop state
    approval_request: str
    approved: bool
    human_feedback: str
    final_response: str

    llm_calls: int


AGENT_ORDER = [
    "flight_agent",
    "hotel_agent",
    "weather_agent",
    "budget_agent",
    "itinerary_agent",
]

KNOWN_AGENTS = frozenset(AGENT_ORDER)


def empty_constraints() -> dict[str, Any]:
    return {
        "destination": "",
        "origin": "",
        "duration": "",
        "budget": "",
        "travel_style": "",
        "special_preferences": [],
    }


def initial_state(user_query: str) -> TravelState:
    """Fresh graph input for a new planning run."""
    from langchain_core.messages import HumanMessage

    return TravelState(
        messages=[HumanMessage(content=user_query)],
        user_query=user_query,
        guardrail_allowed=True,
        guardrail_reason="",
        selected_agents=[],
        trip_constraints=empty_constraints(),
        supervisor_reasoning="",
        flight_results="",
        hotel_results="",
        weather_results="",
        budget_results="",
        itinerary="",
        approval_request="",
        approved=False,
        human_feedback="",
        final_response="",
        llm_calls=0,
    )
