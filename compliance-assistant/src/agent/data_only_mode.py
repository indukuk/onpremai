"""Data-only mode: keyword intent matching fallback when LLM is unavailable.

When LLMCreditExhaustedError is raised, the agent switches to data-only mode.
It uses keyword matching to determine user intent and directly calls MCP tools
or memory queries without LLM involvement.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import structlog

from src.mcp.client import MCPClient
from src.models import SessionState, UserContext

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class KeywordIntent:
    """A matched intent from keyword analysis."""

    tool_name: str
    params: dict[str, Any]
    description: str


# Keyword-to-intent mapping for data-only mode
KEYWORD_INTENTS: dict[str, tuple[str, dict[str, Any], str]] = {
    "status": (
        "evidence.check_coverage",
        {"framework_id": "all"},
        "Show compliance readiness and control status",
    ),
    "readiness": (
        "evidence.check_coverage",
        {"framework_id": "all"},
        "Show compliance readiness percentage",
    ),
    "tasks": (
        "memory.task_list",
        {"status": "open"},
        "View open tasks and deadlines",
    ),
    "overdue": (
        "escalation.check_overdue",
        {"framework_id": "all"},
        "See overdue items",
    ),
    "evidence": (
        "evidence.check_coverage",
        {},
        "Check evidence coverage",
    ),
    "upload": (
        "evidence.upload_url",
        {},
        "Get evidence upload link",
    ),
    "risks": (
        "risk.list",
        {},
        "View risk register",
    ),
    "risk": (
        "risk.list",
        {},
        "View risk register",
    ),
    "audit": (
        "audit.get_readiness",
        {},
        "Check audit timeline and readiness score",
    ),
    "team": (
        "users.list",
        {},
        "View team workload",
    ),
    "remind": (
        "escalation.check_overdue",
        {},
        "Show overdue items to send reminders",
    ),
    "reminder": (
        "escalation.check_overdue",
        {},
        "Show overdue items to send reminders",
    ),
    "deadline": (
        "escalation.check_overdue",
        {},
        "Show items approaching deadline",
    ),
    "controls": (
        "evidence.check_coverage",
        {"framework_id": "all"},
        "Show control status",
    ),
    "gaps": (
        "evidence.check_coverage",
        {"show_gaps": True},
        "Show evidence gaps",
    ),
    "timeline": (
        "audit.get_readiness",
        {},
        "Show audit timeline",
    ),
}


def match_keyword_intent(message: str) -> KeywordIntent | None:
    """Match user message to an intent using keyword analysis.

    This is the fallback when LLM is unavailable. Uses simple keyword
    matching against the KEYWORD_INTENTS dictionary.

    Args:
        message: The user's message text.

    Returns:
        A KeywordIntent if a match is found, None otherwise.
    """
    normalized = message.lower().strip()

    # Direct keyword match (single word)
    for keyword, (tool, params, desc) in KEYWORD_INTENTS.items():
        if normalized == keyword:
            return KeywordIntent(tool_name=tool, params=params, description=desc)

    # Partial match (keyword appears in message)
    best_match: KeywordIntent | None = None
    best_score = 0

    for keyword, (tool, params, desc) in KEYWORD_INTENTS.items():
        # Use word boundary matching for better precision
        pattern = rf"\b{re.escape(keyword)}\b"
        matches = re.findall(pattern, normalized)
        score = len(matches) * len(keyword)

        if score > best_score:
            best_score = score
            best_match = KeywordIntent(tool_name=tool, params=params, description=desc)

    return best_match


async def handle_data_only_message(
    message: str,
    session: SessionState,
    user: UserContext,
    mcp: MCPClient,
    estimated_recovery: str | None = None,
) -> str:
    """Handle a user message in data-only mode (no LLM available).

    Attempts keyword intent matching to execute tools directly.
    If no match, shows the data-only menu.
    """
    intent = match_keyword_intent(message)

    if intent:
        logger.info(
            "data_only_intent_matched",
            intent_tool=intent.tool_name,
            message_excerpt=message[:50],
        )

        # Try to call the tool via MCP
        result = await mcp.call_tool(
            tool_name=intent.tool_name,
            params=intent.params,
            jwt_token=user.jwt_token,
        )

        if result.get("status") == "error":
            return (
                f"I tried to fetch {intent.description.lower()}, but the request "
                f"failed: {result.get('message', 'unknown error')}.\n\n"
                "Please try again or contact support if this persists."
            )

        # Format the result as a simple response
        data = result.get("data", result.get("result", result))
        return _format_data_response(data, intent.description, estimated_recovery)

    # No match - show the menu
    return _build_data_only_menu(estimated_recovery)


def _format_data_response(
    data: Any,
    description: str,
    estimated_recovery: str | None,
) -> str:
    """Format tool result data as a user-friendly text response."""
    lines: list[str] = [
        f"**{description}**",
        "",
    ]

    if isinstance(data, dict):
        for key, value in data.items():
            if key.startswith("_"):
                continue
            label = key.replace("_", " ").title()
            lines.append(f"- {label}: {value}")
    elif isinstance(data, list):
        for item in data[:20]:  # Cap at 20 items
            if isinstance(item, dict):
                summary = item.get("title", item.get("name", item.get("id", str(item))))
                status = item.get("status", "")
                lines.append(f"- {summary} {f'({status})' if status else ''}")
            else:
                lines.append(f"- {item}")
    else:
        lines.append(str(data))

    lines.append("")
    lines.append("---")
    lines.append(
        "Note: I'm in data-only mode (AI analysis budget reached). "
        "Type STATUS, TASKS, OVERDUE, EVIDENCE, RISKS, or AUDIT for quick info."
    )
    if estimated_recovery:
        lines.append(f"Full capabilities resume: {estimated_recovery}")

    return "\n".join(lines)


def _build_data_only_menu(estimated_recovery: str | None) -> str:
    """Build the data-only mode menu shown when no keyword matches."""
    lines = [
        "I'm currently in data-only mode - our AI analysis budget has been reached "
        "for this billing period. Here's what I can still help with:",
        "",
        "STATUS    - Show your compliance readiness and control status",
        "TASKS     - View your open tasks and deadlines",
        "EVIDENCE  - Check evidence coverage, get upload links",
        "OVERDUE   - See overdue items, send reminders",
        "RISKS     - View risk register",
        "AUDIT     - Check audit timeline and readiness score",
        "TEAM      - View team workload",
        "",
        "Type one of these keywords or ask me a specific status question.",
        "",
        "Full AI capabilities (guidance, policy drafting, evaluations) are queued "
        "and will resume when the budget resets.",
    ]

    if estimated_recovery:
        lines.append(f"Estimated resumption: {estimated_recovery}")

    return "\n".join(lines)
