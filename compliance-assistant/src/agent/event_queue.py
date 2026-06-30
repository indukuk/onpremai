"""Proactive Event Queue: drain events accumulated between sessions.

Events are pushed by other services (agent-eval, preprocessor, scheduler)
via memory-service. On session start, the shadow agent drains the queue
and incorporates events into the proactive opener.
"""

from __future__ import annotations

from typing import Any

import structlog

from common.clients import MemoryClient

logger = structlog.get_logger(__name__)

PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}


class EventQueueHandler:
    """Drains and formats the per-user event queue."""

    def __init__(self, memory: MemoryClient) -> None:
        self._memory = memory

    async def drain(self, user_id: str, tenant_id: str) -> list[dict[str, Any]]:
        """Drain all pending events for a user. Returns [] if empty or unavailable."""
        events = await self._memory.event_queue_drain(user_id, tenant_id)
        if not events:
            return []

        events.sort(key=lambda e: PRIORITY_ORDER.get(e.get("priority", "low"), 2))

        logger.info(
            "events_drained",
            user_id=user_id,
            count=len(events),
        )
        return events

    def format_for_context(self, events: list[dict[str, Any]]) -> str:
        """Format events as a system prompt section."""
        if not events:
            return ""

        lines = ["## Since Your Last Session"]
        for event in events[:10]:
            priority = event.get("priority", "medium")
            summary = event.get("summary", "")
            marker = "!" if priority == "high" else "-"
            lines.append(f"{marker} {summary}")

        commitments = [
            e for e in events if e.get("event_type") == "agent_commitment_due"
        ]
        if commitments:
            lines.append("\nDue commitments:")
            for c in commitments:
                lines.append(f"  - {c.get('summary', '')}")

        return "\n".join(lines)

    def format_for_opener(self, events: list[dict[str, Any]]) -> str:
        """Format events for the opener user message (more detailed)."""
        if not events:
            return ""

        parts = ["Since your last session, the following happened:"]
        for event in events[:10]:
            summary = event.get("summary", "")
            source = event.get("source_service", "")
            parts.append(f"- {summary}" + (f" (from {source})" if source else ""))

        return "\n".join(parts)
