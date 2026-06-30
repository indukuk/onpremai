"""Unit tests for the EventQueueHandler class.

Covers:
- drain returns empty list on failure or empty queue
- drain sorts events by priority (high > medium > low)
- format_for_context returns "" for empty events
- format_for_context formats as markdown with priority markers
- format_for_context shows agent_commitment_due events separately
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.agent.event_queue import EventQueueHandler


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def event_handler(mock_memory_client: AsyncMock) -> EventQueueHandler:
    """EventQueueHandler with a mocked memory client."""
    return EventQueueHandler(memory=mock_memory_client)


@pytest.fixture
def sample_events() -> list[dict[str, Any]]:
    """Sample events with mixed priorities."""
    return [
        {
            "event_type": "eval_completed",
            "priority": "low",
            "summary": "ISO audit scored 78%",
            "source_service": "agent-eval",
        },
        {
            "event_type": "evidence_uploaded",
            "priority": "high",
            "summary": "New evidence uploaded for CC6.1",
            "source_service": "preprocessor",
        },
        {
            "event_type": "task_assigned",
            "priority": "medium",
            "summary": "New task assigned: Review vendor risk",
            "source_service": "memory-service",
        },
    ]


@pytest.fixture
def events_with_commitments() -> list[dict[str, Any]]:
    """Events including agent_commitment_due entries."""
    return [
        {
            "event_type": "eval_completed",
            "priority": "medium",
            "summary": "SOC2 eval finished",
            "source_service": "agent-eval",
        },
        {
            "event_type": "agent_commitment_due",
            "priority": "high",
            "summary": "Send audit report to Carol",
            "source_service": "compliance-assistant",
        },
        {
            "event_type": "agent_commitment_due",
            "priority": "high",
            "summary": "Follow up on CC6.1 remediation",
            "source_service": "compliance-assistant",
        },
    ]


# ---------------------------------------------------------------------------
# Test: drain returns empty list on failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_drain_returns_empty_on_failure(
    event_handler: EventQueueHandler,
    mock_memory_client: AsyncMock,
) -> None:
    """When memory returns [] or None, handler returns []."""
    mock_memory_client.event_queue_drain.return_value = []

    result = await event_handler.drain("user-001", "tenant-001")
    assert result == []


@pytest.mark.asyncio
async def test_drain_returns_empty_on_none(
    event_handler: EventQueueHandler,
    mock_memory_client: AsyncMock,
) -> None:
    """When memory returns None, handler returns []."""
    mock_memory_client.event_queue_drain.return_value = None

    result = await event_handler.drain("user-001", "tenant-001")
    assert result == []


# ---------------------------------------------------------------------------
# Test: drain sorts by priority
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_drain_sorts_by_priority(
    event_handler: EventQueueHandler,
    mock_memory_client: AsyncMock,
    sample_events: list[dict[str, Any]],
) -> None:
    """High events come before medium, medium before low."""
    mock_memory_client.event_queue_drain.return_value = sample_events

    result = await event_handler.drain("user-001", "tenant-001")

    assert len(result) == 3
    assert result[0]["priority"] == "high"
    assert result[1]["priority"] == "medium"
    assert result[2]["priority"] == "low"


# ---------------------------------------------------------------------------
# Test: format_for_context returns "" for empty events
# ---------------------------------------------------------------------------


def test_format_for_context_empty(event_handler: EventQueueHandler) -> None:
    """Returns empty string for empty events list."""
    result = event_handler.format_for_context([])
    assert result == ""


# ---------------------------------------------------------------------------
# Test: format_for_context with events (priority markers)
# ---------------------------------------------------------------------------


def test_format_for_context_with_events(
    event_handler: EventQueueHandler,
    sample_events: list[dict[str, Any]],
) -> None:
    """Formats as markdown with '!' for high priority and '-' for others."""
    # Sort events first (as drain would)
    sorted_events = sorted(
        sample_events,
        key=lambda e: {"high": 0, "medium": 1, "low": 2}.get(e.get("priority", "low"), 2),
    )

    result = event_handler.format_for_context(sorted_events)

    assert "## Since Your Last Session" in result
    # High priority event gets "!" marker
    assert "! New evidence uploaded for CC6.1" in result
    # Medium and low get "-" marker
    assert "- New task assigned: Review vendor risk" in result
    assert "- ISO audit scored 78%" in result


# ---------------------------------------------------------------------------
# Test: format_for_context shows commitments separately
# ---------------------------------------------------------------------------


def test_format_for_context_shows_commitments(
    event_handler: EventQueueHandler,
    events_with_commitments: list[dict[str, Any]],
) -> None:
    """agent_commitment_due events shown in a separate 'Due commitments' section."""
    result = event_handler.format_for_context(events_with_commitments)

    assert "Due commitments:" in result
    assert "Send audit report to Carol" in result
    assert "Follow up on CC6.1 remediation" in result
