"""API routes for travel planning and health checks."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from tripmate.agents.runner import TravelPlanner
from tripmate.api.schemas import (
    ApprovalRequest,
    HealthResponse,
    PlanResponse,
    TravelRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def get_planner(request: Request) -> TravelPlanner:
    planner = getattr(request.app.state, "planner", None)
    if planner is None:
        raise HTTPException(
            status_code=503,
            detail="The travel planner is not ready yet. Try again shortly.",
        )
    return planner


PlannerDep = Annotated[TravelPlanner, Depends(get_planner)]


@router.post("/api/travel", response_model=PlanResponse)
async def create_travel_plan(
    request_data: TravelRequest,
    planner: PlannerDep,
) -> PlanResponse:
    user_message = request_data.message.strip()
    if not user_message:
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    try:
        result = await planner.start(
            user_input=user_message,
            thread_id=request_data.thread_id,
        )
    except Exception as exc:
        logger.exception("Travel planning failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return PlanResponse(**result)


@router.post("/api/travel/approve", response_model=PlanResponse)
async def approve_travel_plan(
    request_data: ApprovalRequest,
    planner: PlannerDep,
) -> PlanResponse:
    if not request_data.approved and not request_data.feedback.strip():
        raise HTTPException(
            status_code=400,
            detail="Please provide revision feedback when rejecting the draft.",
        )

    try:
        result = await planner.resume(
            thread_id=request_data.thread_id,
            approved=request_data.approved,
            feedback=request_data.feedback,
        )
    except Exception as exc:
        logger.exception("Travel plan approval failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return PlanResponse(**result)


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    return HealthResponse()
