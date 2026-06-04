"""Intent classification node for the evaluation graph.

Determines whether the incoming request is:
- evaluate: run the compliance evaluation pipeline
- chat: respond to a compliance question
- status: check evaluation status

For POST /evaluate requests the intent is always "evaluate".
The router logic exists for the POST /chat endpoint where the user's
message may imply evaluation, status checking, or general Q&A.
"""

from __future__ import annotations

import re
from typing import Any

import structlog

from common.clients import LLMClient

from src.graph.state import EvalGraphState

logger = structlog.get_logger(__name__)

ROUTER_PROMPT = """You are an intent classifier for a compliance evaluation system.

Classify the user's message into exactly one intent:
- "evaluate": User wants to evaluate a specific control or upload evidence for evaluation
- "status": User is asking about the status of an evaluation or results
- "chat": User has a general compliance question or needs help

User message: {message}

Respond with ONLY one word: evaluate, status, or chat"""

# Heuristic patterns to avoid LLM call for obvious cases
_EVALUATE_PATTERNS = [
    re.compile(r"\bevaluat(e|ion)\b", re.IGNORECASE),
    re.compile(r"\bassess\b", re.IGNORECASE),
    re.compile(r"\bcheck compliance\b", re.IGNORECASE),
    re.compile(r"\brun\s+(the\s+)?eval", re.IGNORECASE),
]

_STATUS_PATTERNS = [
    re.compile(r"\bstatus\b", re.IGNORECASE),
    re.compile(r"\bprogress\b", re.IGNORECASE),
    re.compile(r"\bresult(s)?\b", re.IGNORECASE),
    re.compile(r"\bhow\s+(is|are)\s+(the|my)\b", re.IGNORECASE),
]


def _classify_heuristic(message: str) -> str | None:
    """Try to classify intent using regex patterns before calling LLM."""
    for pattern in _EVALUATE_PATTERNS:
        if pattern.search(message):
            return "evaluate"
    for pattern in _STATUS_PATTERNS:
        if pattern.search(message):
            return "status"
    return None


async def router_node(state: EvalGraphState) -> dict[str, Any]:
    """Classify the intent of the incoming request.

    For direct /evaluate API calls, the intent is pre-set to "evaluate".
    For /chat calls, this node classifies the user's message.
    """
    # If intent is already set (from direct /evaluate call), skip classification
    if state.get("intent"):
        logger.info(
            "router_skip",
            intent=state["intent"],
            trace_id=state.get("trace_id", ""),
        )
        return {"intent": state["intent"]}

    message = state.get("chat_message", "")
    if not message:
        return {"intent": "evaluate"}

    # Try heuristic first (no LLM cost)
    heuristic_result = _classify_heuristic(message)
    if heuristic_result is not None:
        logger.info(
            "router_heuristic",
            intent=heuristic_result,
            trace_id=state.get("trace_id", ""),
        )
        return {"intent": heuristic_result}

    # Fall back to LLM classification
    llm = LLMClient()
    try:
        response = await llm.complete(
            messages=[
                {"role": "user", "content": ROUTER_PROMPT.format(message=message)},
            ],
            task="classify_intent",
            tenant_id=state.get("tenant_id", ""),
            trace_id=state.get("trace_id", ""),
            temperature=0.0,
            max_tokens=10,
        )
        intent = response.content.strip().lower()
        if intent not in ("evaluate", "status", "chat"):
            intent = "chat"
    except Exception:
        logger.warning("router_llm_fallback", trace_id=state.get("trace_id", ""))
        intent = "chat"
    finally:
        await llm.close()

    logger.info(
        "router_classified",
        intent=intent,
        trace_id=state.get("trace_id", ""),
    )
    return {"intent": intent}
