"""Unit tests for supervisor routing and result serialization."""

import os

os.environ.setdefault("GROQ_API_KEY", "test-groq-key")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")

from tripmate.agents.graph import route_after_agent, route_from_supervisor
from tripmate.agents.runner import serialize_result
from tripmate.agents.state import AGENT_ORDER, empty_constraints


def test_blocked_request_routes_to_guardrail():
    state = {"guardrail_allowed": False, "selected_agents": AGENT_ORDER}
    assert route_from_supervisor(state) == "guardrail_blocked"


def test_supervisor_routes_to_first_selected_agent():
    state = {
        "guardrail_allowed": True,
        "selected_agents": ["hotel_agent", "itinerary_agent"],
    }
    assert route_from_supervisor(state) == "hotel_agent"


def test_supervisor_defaults_to_itinerary_when_nothing_selected():
    state = {"guardrail_allowed": True, "selected_agents": []}
    assert route_from_supervisor(state) == "itinerary_agent"


def test_route_after_agent_skips_unselected_agents():
    state = {"selected_agents": ["flight_agent", "budget_agent", "itinerary_agent"]}
    assert route_after_agent("flight_agent")(state) == "budget_agent"


def test_route_after_agent_falls_back_to_itinerary():
    state = {"selected_agents": ["weather_agent"]}
    assert route_after_agent("weather_agent")(state) == "itinerary_agent"


def test_serialize_result_without_interrupt():
    result = {
        "final_response": "Final plan",
        "messages": [],
        "selected_agents": ["itinerary_agent"],
        "trip_constraints": empty_constraints(),
        "llm_calls": 3,
    }
    serialized = serialize_result(result, "thread-9")

    assert serialized["thread_id"] == "thread-9"
    assert serialized["answer"] == "Final plan"
    assert serialized["requires_approval"] is False
    assert serialized["llm_calls"] == 3


def test_serialize_result_with_interrupt():
    class FakeInterrupt:
        value = {
            "draft_itinerary": "Day 1: arrive.",
            "approval_request": "Approve the draft?",
        }

    result = {
        "messages": [],
        "itinerary": "Day 1: arrive.",
        "__interrupt__": [FakeInterrupt()],
    }
    serialized = serialize_result(result, "thread-9")

    assert serialized["requires_approval"] is True
    assert serialized["answer"] == "Day 1: arrive."
    assert serialized["approval_request"] == "Approve the draft?"
    assert serialized["itinerary"] == "Day 1: arrive."
