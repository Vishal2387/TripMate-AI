"""Shared test fixtures.

The app is exercised with a fake planner injected into ``app.state`` before
startup, so no database, LLM, or MCP servers are needed.
"""

import os

import pytest
from fastapi.testclient import TestClient

# Provide required settings before tripmate.config is imported.
os.environ.setdefault("GROQ_API_KEY", "test-groq-key")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")

from tripmate.app import create_app  # noqa: E402


class FakePlanner:
    """Deterministic stand-in for TravelPlanner."""

    def __init__(self):
        self.start_calls: list[dict] = []
        self.resume_calls: list[dict] = []

    @staticmethod
    def _result(thread_id: str, requires_approval: bool) -> dict:
        return {
            "thread_id": thread_id,
            "answer": "Draft plan" if requires_approval else "Final plan",
            "requires_approval": requires_approval,
            "approval_request": "Review the draft." if requires_approval else "",
            "flight_results": "",
            "hotel_results": "",
            "weather_results": "",
            "budget_results": "",
            "itinerary": "Day 1: arrive." if requires_approval else "",
            "selected_agents": ["flight_agent", "itinerary_agent"],
            "trip_constraints": {},
            "supervisor_reasoning": "Test routing.",
            "guardrail_allowed": True,
            "guardrail_reason": "",
            "approved": None if requires_approval else True,
            "human_feedback": "",
            "llm_calls": 2,
        }

    async def start(self, user_input: str, thread_id: str | None = None) -> dict:
        self.start_calls.append({"user_input": user_input, "thread_id": thread_id})
        return self._result(thread_id or "thread-new", requires_approval=True)

    async def resume(self, thread_id: str, approved: bool, feedback: str = "") -> dict:
        self.resume_calls.append(
            {"thread_id": thread_id, "approved": approved, "feedback": feedback}
        )
        return self._result(thread_id, requires_approval=False)


@pytest.fixture
def fake_planner() -> FakePlanner:
    return FakePlanner()


@pytest.fixture
def client(fake_planner: FakePlanner):
    app = create_app()
    app.state.planner = fake_planner
    with TestClient(app) as test_client:
        yield test_client
