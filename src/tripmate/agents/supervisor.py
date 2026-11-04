"""Supervisor agent with input guardrail and dynamic agent routing."""

import logging

from langchain_core.messages import AIMessage

from tripmate.agents import prompts
from tripmate.agents.llm import json_from_llm, llm_text
from tripmate.agents.state import (
    AGENT_ORDER,
    KNOWN_AGENTS,
    TravelState,
    empty_constraints,
)

logger = logging.getLogger(__name__)

GUARDRAIL_BLOCK_MESSAGE = (
    "TripMate AI can only help with travel-planning requests. "
    "Please ask about a destination, flight, hotel, weather, budget, "
    "or itinerary."
)


def _run_guardrail(query: str) -> tuple[bool, str, int]:
    """Return (allowed, reason, llm_calls_used).

    Fails open on parser/model errors so a temporary JSON-format issue does
    not break travel planning.
    """
    try:
        raw = llm_text(
            prompts.GUARDRAIL_SYSTEM,
            prompts.GUARDRAIL_PROMPT.format(query=query),
        )
        result = json_from_llm(raw)
        allowed = bool(result.get("allowed", True))
        reason = str(result.get("reason", "")).strip()
        return allowed, reason, 1
    except Exception:
        logger.warning("Guardrail fallback used", exc_info=True)
        return True, "Guardrail validation fallback allowed the request.", 0


def _run_supervisor(query: str) -> tuple[list[str], dict, str, int]:
    """Return (selected_agents, constraints, reasoning, llm_calls_used)."""
    try:
        raw = llm_text(
            prompts.SUPERVISOR_SYSTEM,
            prompts.SUPERVISOR_PROMPT.format(query=query),
        )
        parsed = json_from_llm(raw)

        requested = parsed.get("selected_agents", [])
        selected = [
            name
            for name in AGENT_ORDER
            if name in requested and name in KNOWN_AGENTS
        ]
        # The itinerary agent integrates whichever specialist results
        # were selected, so it is always required.
        if "itinerary_agent" not in selected:
            selected.append("itinerary_agent")

        constraints = empty_constraints()
        parsed_constraints = parsed.get("trip_constraints", {})
        if isinstance(parsed_constraints, dict):
            constraints.update(parsed_constraints)

        reasoning = str(parsed.get("reasoning", "")).strip()
        return selected, constraints, reasoning, 1
    except Exception:
        logger.warning("Supervisor fallback used", exc_info=True)
        # The full workflow is the safe fallback.
        return (
            AGENT_ORDER.copy(),
            empty_constraints(),
            "Supervisor parsing failed, so the full travel workflow "
            "was selected as a safe fallback.",
            0,
        )


def supervisor_agent(state: TravelState) -> dict:
    query = state["user_query"]
    llm_calls = state.get("llm_calls", 0)

    allowed, guardrail_reason, guardrail_calls = _run_guardrail(query)
    llm_calls += guardrail_calls

    if not allowed:
        reason = guardrail_reason or GUARDRAIL_BLOCK_MESSAGE
        return {
            "guardrail_allowed": False,
            "guardrail_reason": reason,
            "selected_agents": [],
            "trip_constraints": empty_constraints(),
            "supervisor_reasoning": reason,
            "final_response": reason,
            "messages": [AIMessage(content=f"Guardrail blocked request: {reason}")],
            "llm_calls": llm_calls,
        }

    selected, constraints, reasoning, supervisor_calls = _run_supervisor(query)
    llm_calls += supervisor_calls

    return {
        "guardrail_allowed": True,
        "guardrail_reason": guardrail_reason,
        "selected_agents": selected,
        "trip_constraints": constraints,
        "supervisor_reasoning": reasoning,
        "messages": [AIMessage(content="Supervisor created the agent plan.")],
        "llm_calls": llm_calls,
    }


def guardrail_blocked_agent(state: TravelState) -> dict:
    reason = (
        state.get("final_response")
        or state.get("guardrail_reason")
        or "This request was blocked by the travel input guardrail."
    )
    return {
        "final_response": reason,
        "messages": [AIMessage(content=reason)],
    }
