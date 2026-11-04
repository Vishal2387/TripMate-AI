"""Pydantic request and response models for the travel API."""

from typing import Any

from pydantic import BaseModel, Field


class TravelRequest(BaseModel):
    message: str = Field(min_length=1, description="The user's travel request.")
    thread_id: str | None = Field(
        default=None,
        description="Existing thread to continue; a new one is created when omitted.",
    )


class ApprovalRequest(BaseModel):
    thread_id: str = Field(min_length=1)
    approved: bool
    feedback: str = ""


class PlanResponse(BaseModel):
    success: bool = True
    thread_id: str
    answer: str
    requires_approval: bool
    approval_request: str = ""
    flight_results: Any = ""
    hotel_results: Any = ""
    weather_results: Any = ""
    budget_results: Any = ""
    itinerary: Any = ""
    selected_agents: list[str] = []
    trip_constraints: dict[str, Any] = {}
    supervisor_reasoning: str = ""
    guardrail_allowed: bool = True
    guardrail_reason: str = ""
    approved: bool | None = None
    human_feedback: str = ""
    llm_calls: int = 0


class ErrorResponse(BaseModel):
    success: bool = False
    error: str


class HealthResponse(BaseModel):
    status: str = "ok"
    message: str = "TripMate AI API is running"
    features: list[str] = [
        "supervisor_agent",
        "input_guardrail",
        "human_in_the_loop",
    ]
