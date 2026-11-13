"""TravelPlanner: async facade over the compiled LangGraph workflow.

Graph execution is synchronous and blocking (LLM + MCP calls), so it is
dispatched to a worker thread with ``asyncio.to_thread`` to keep the
FastAPI event loop responsive.
"""

import asyncio
import uuid
from typing import Any

from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from tripmate.agents.state import initial_state


def _interrupt_payload(result: dict[str, Any]) -> dict[str, Any] | None:
    interrupts = result.get("__interrupt__", [])
    if not interrupts:
        return None

    first_interrupt = interrupts[0]
    payload = getattr(first_interrupt, "value", first_interrupt)
    return payload if isinstance(payload, dict) else {"value": payload}


def serialize_result(result: dict[str, Any], thread_id: str) -> dict[str, Any]:
    messages = result.get("messages", [])
    last_message = messages[-1].content if messages else ""
    answer = result.get("final_response") or last_message
    interrupt_payload = _interrupt_payload(result)

    if interrupt_payload:
        answer = interrupt_payload.get("draft_itinerary") or result.get("itinerary", "")

    return {
        "thread_id": thread_id,
        "answer": answer,
        "requires_approval": interrupt_payload is not None,
        "approval_request": (
            interrupt_payload.get("approval_request", "")
            if interrupt_payload
            else result.get("approval_request", "")
        ),
        "flight_results": result.get("flight_results", ""),
        "hotel_results": result.get("hotel_results", ""),
        "weather_results": result.get("weather_results", ""),
        "budget_results": result.get("budget_results", ""),
        "itinerary": (
            interrupt_payload.get("draft_itinerary", "")
            if interrupt_payload
            else result.get("itinerary", "")
        ),
        "selected_agents": result.get("selected_agents", []),
        "trip_constraints": result.get("trip_constraints", {}),
        "supervisor_reasoning": result.get("supervisor_reasoning", ""),
        "guardrail_allowed": result.get("guardrail_allowed", True),
        "guardrail_reason": result.get("guardrail_reason", ""),
        "approved": result.get("approved"),
        "human_feedback": result.get("human_feedback", ""),
        "llm_calls": result.get("llm_calls", 0),
    }


class TravelPlanner:
    """Starts and resumes travel-planning threads on the compiled graph."""

    def __init__(self, graph: CompiledStateGraph):
        self._graph = graph

    def _start_sync(self, user_input: str, thread_id: str) -> dict[str, Any]:
        config = {"configurable": {"thread_id": thread_id}}
        result = self._graph.invoke(initial_state(user_input), config=config)
        return serialize_result(result, thread_id)

    def _resume_sync(
        self,
        thread_id: str,
        approved: bool,
        feedback: str,
    ) -> dict[str, Any]:
        config = {"configurable": {"thread_id": thread_id}}
        result = self._graph.invoke(
            Command(resume={"approved": approved, "feedback": feedback.strip()}),
            config=config,
        )
        return serialize_result(result, thread_id)

    async def start(
        self,
        user_input: str,
        thread_id: str | None = None,
    ) -> dict[str, Any]:
        """Start a new travel-planning run; pauses at human approval."""
        thread_id = thread_id or f"user_{uuid.uuid4().hex}"
        return await asyncio.to_thread(self._start_sync, user_input, thread_id)

    async def resume(
        self,
        thread_id: str,
        approved: bool,
        feedback: str = "",
    ) -> dict[str, Any]:
        """Resume the paused LangGraph thread after human review."""
        if not thread_id:
            raise ValueError("thread_id is required to resume a travel plan.")
        return await asyncio.to_thread(self._resume_sync, thread_id, approved, feedback)
