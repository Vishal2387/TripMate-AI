"""Itinerary drafting, human-in-the-loop approval, and final response."""

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.types import interrupt

from tripmate.agents import prompts
from tripmate.agents.llm import clip, get_llm
from tripmate.agents.state import TravelState


def itinerary_agent(state: TravelState) -> dict:
    prompt = prompts.ITINERARY_AGENT_PROMPT.format(
        query=state["user_query"],
        trip_constraints=state.get("trip_constraints", {}),
        flight_results=clip(state.get("flight_results", "")),
        hotel_results=clip(state.get("hotel_results", ""), 2500),
        weather_results=clip(state.get("weather_results", "")),
        budget_results=clip(state.get("budget_results", "")),
    )

    response = get_llm().invoke(
        [
            SystemMessage(content=prompts.ITINERARY_AGENT_SYSTEM),
            HumanMessage(content=prompt),
        ]
    )

    return {
        "itinerary": response.content,
        "approval_request": prompts.APPROVAL_REQUEST_MESSAGE,
        "messages": [AIMessage(content="Draft itinerary created for human review.")],
        "llm_calls": state.get("llm_calls", 0) + 1,
    }


def human_approval_agent(state: TravelState) -> dict:
    # Do not wrap interrupt() in try/except: LangGraph raises internally to
    # pause execution here until the thread is resumed with a Command.
    review = interrupt(
        {
            "question": "Do you approve this itinerary?",
            "draft_itinerary": state.get("itinerary", ""),
            "approval_request": state.get("approval_request", ""),
            "selected_agents": state.get("selected_agents", []),
            "supervisor_reasoning": state.get("supervisor_reasoning", ""),
            "expected_response": {
                "approved": True,
                "feedback": "Optional revision feedback",
            },
        }
    )

    return {
        "approved": bool(review.get("approved", False)),
        "human_feedback": str(review.get("feedback", "")).strip(),
        "messages": [AIMessage(content="Human approval step completed.")],
    }


def final_agent(state: TravelState) -> dict:
    if state.get("approved", False):
        review_instruction = (
            "The user approved the draft. Preserve its decisions while polishing it."
        )
    else:
        feedback = (
            state.get("human_feedback", "") or "Improve the draft before finalizing it."
        )
        review_instruction = (
            f"The user requested a revision. Apply this feedback carefully:\n{feedback}"
        )

    prompt = prompts.FINAL_AGENT_PROMPT.format(
        review_instruction=review_instruction,
        query=state["user_query"],
        trip_constraints=state.get("trip_constraints", {}),
        flight_results=clip(state.get("flight_results", "")),
        hotel_results=clip(state.get("hotel_results", ""), 2500),
        weather_results=clip(state.get("weather_results", "")),
        budget_results=clip(state.get("budget_results", "")),
        itinerary=state.get("itinerary", ""),
    )

    response = get_llm().invoke(
        [
            SystemMessage(content=prompts.FINAL_AGENT_SYSTEM),
            HumanMessage(content=prompt),
        ]
    )

    return {
        "final_response": response.content,
        "messages": [response],
        "llm_calls": state.get("llm_calls", 0) + 1,
    }
