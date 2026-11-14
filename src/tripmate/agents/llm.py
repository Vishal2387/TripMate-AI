"""LLM factory and small invocation helpers shared by all agents."""

import json
from functools import lru_cache
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_groq import ChatGroq

from tripmate.config import get_settings


@lru_cache
def get_llm() -> ChatGroq:
    settings = get_settings()
    return ChatGroq(
        model=settings.groq_model,
        api_key=settings.groq_api_key,
        max_retries=4,
    )


def clip(text: object, limit: int = 2000) -> str:
    """Cap text fed into downstream prompts (Groq free tier: 8k tokens/min)."""
    text = str(text or "").strip()
    return text if len(text) <= limit else text[:limit].rstrip() + " ...[truncated]"


def llm_text(system_prompt: str, user_prompt: str) -> str:
    response = get_llm().invoke(
        [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
    )
    return str(response.content)


def json_from_llm(text: str) -> dict[str, Any]:
    """Extract the first complete JSON object returned by the model."""
    start = text.find("{")
    end = text.rfind("}")

    if start == -1 or end == -1 or end < start:
        raise ValueError("The model did not return a JSON object.")

    return json.loads(text[start : end + 1])
