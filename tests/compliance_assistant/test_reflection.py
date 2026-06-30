"""Unit tests for the SessionReflector and should_reflect logic.

Covers:
- should_reflect threshold and goodbye signal detection
- Conversation formatting (system messages excluded, tool results truncated)
- LLM response parsing (valid JSON, parse failures)
- LLM failure handling (LLMUnavailableError returns None)
- Memory store calls (interaction_store, user_store)
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.agent.reflection import SessionReflector, should_reflect
from src.models import SessionState


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def session_short() -> SessionState:
    """Session with message_count below reflection threshold."""
    return SessionState(
        session_id="sess-001",
        tenant_id="tenant-001",
        user_id="user-001",
        role="admin",
        message_count=3,
        conversation_history=[
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
            {"role": "user", "content": "What is SOC2?"},
        ],
    )


@pytest.fixture
def session_long() -> SessionState:
    """Session with message_count at/above reflection threshold."""
    return SessionState(
        session_id="sess-002",
        tenant_id="tenant-001",
        user_id="user-001",
        role="admin",
        message_count=8,
        conversation_history=[
            {"role": "system", "content": "You are the compliance assistant."},
            {"role": "user", "content": "Check my SOC2 status"},
            {"role": "assistant", "content": "Let me look that up."},
            {"role": "tool", "content": "x" * 500},
            {"role": "assistant", "content": "Your readiness is 85%."},
            {"role": "user", "content": "What about ISO?"},
            {"role": "assistant", "content": "ISO is at 72%."},
            {"role": "user", "content": "Thanks!"},
        ],
    )


# ---------------------------------------------------------------------------
# Test: should_reflect below threshold
# ---------------------------------------------------------------------------


def test_should_reflect_below_threshold(session_short: SessionState) -> None:
    """Returns False when message_count < reflection_min_messages (6)."""
    result = should_reflect(session_short, "hello")
    assert result is False


# ---------------------------------------------------------------------------
# Test: should_reflect above threshold
# ---------------------------------------------------------------------------


def test_should_reflect_above_threshold(session_long: SessionState) -> None:
    """Returns True when message_count >= reflection_min_messages."""
    result = should_reflect(session_long, "what else?")
    assert result is True


# ---------------------------------------------------------------------------
# Test: should_reflect goodbye signal
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("signal", ["bye", "thanks", "done", "goodbye", "cheers"])
def test_should_reflect_goodbye_signal(
    session_long: SessionState, signal: str
) -> None:
    """Returns True on recognized goodbye signals when above threshold."""
    result = should_reflect(session_long, signal)
    assert result is True


def test_should_reflect_goodbye_signal_below_threshold(
    session_short: SessionState,
) -> None:
    """Returns False even with goodbye signal when below threshold."""
    result = should_reflect(session_short, "bye")
    assert result is False


# ---------------------------------------------------------------------------
# Test: _format_conversation (system excluded, tool truncated)
# ---------------------------------------------------------------------------


def test_reflect_formats_conversation(
    mock_llm_client: AsyncMock,
    mock_memory_client: AsyncMock,
    session_long: SessionState,
) -> None:
    """System messages are excluded; tool results truncated to 200 chars."""
    reflector = SessionReflector(llm=mock_llm_client, memory=mock_memory_client)
    formatted = reflector._format_conversation(session_long.conversation_history)

    # System message should not appear
    assert "You are the compliance assistant" not in formatted

    # User messages should appear
    assert "User: Check my SOC2 status" in formatted

    # Tool content should be truncated (original was 500 chars)
    tool_lines = [line for line in formatted.split("\n") if "[tool result]:" in line]
    assert len(tool_lines) == 1
    # Truncated content should end with "..."
    assert tool_lines[0].endswith("...")

    # Assistant messages should appear
    assert "Agent: Your readiness is 85%." in formatted


# ---------------------------------------------------------------------------
# Test: reflect parses valid JSON response
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reflect_parses_json_response(
    mock_llm_client: AsyncMock,
    mock_memory_client: AsyncMock,
    session_long: SessionState,
) -> None:
    """Mock LLM returning valid JSON is parsed into structured reflection."""
    reflection_json = json.dumps({
        "accomplished": ["Reviewed SOC2 readiness"],
        "pending": ["ISO audit next week"],
        "commitments": ["Follow up on control CC6.1"],
        "preferences": ["Prefers concise answers"],
    })

    class FakeLLMResponse:
        content = reflection_json
        model_used = "anthropic.claude-3-haiku"
        tier_used = "fast"
        tokens = 100
        latency = 0.2

    mock_llm_client.complete.return_value = FakeLLMResponse()

    reflector = SessionReflector(llm=mock_llm_client, memory=mock_memory_client)
    result = await reflector.reflect(
        session=session_long,
        user_id="user-001",
        tenant_id="tenant-001",
    )

    assert result is not None
    assert result["accomplished"] == ["Reviewed SOC2 readiness"]
    assert result["pending"] == ["ISO audit next week"]
    assert result["commitments"] == ["Follow up on control CC6.1"]
    assert result["preferences"] == ["Prefers concise answers"]


# ---------------------------------------------------------------------------
# Test: reflect handles LLM failure gracefully
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reflect_handles_llm_failure(
    mock_llm_client: AsyncMock,
    mock_memory_client: AsyncMock,
    session_long: SessionState,
) -> None:
    """When LLM raises LLMUnavailableError, reflect() returns None."""
    from common.errors import LLMUnavailableError

    mock_llm_client.complete.side_effect = LLMUnavailableError("Gateway down")

    reflector = SessionReflector(llm=mock_llm_client, memory=mock_memory_client)
    result = await reflector.reflect(
        session=session_long,
        user_id="user-001",
        tenant_id="tenant-001",
    )

    assert result is None


# ---------------------------------------------------------------------------
# Test: reflect stores interaction in memory
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reflect_stores_interaction(
    mock_llm_client: AsyncMock,
    mock_memory_client: AsyncMock,
    session_long: SessionState,
) -> None:
    """Verify memory.interaction_store is called with correct type."""
    reflection_json = json.dumps({
        "accomplished": ["Completed audit review"],
        "pending": [],
        "commitments": [],
        "preferences": [],
    })

    class FakeLLMResponse:
        content = reflection_json
        model_used = "anthropic.claude-3-haiku"
        tier_used = "fast"
        tokens = 80
        latency = 0.15

    mock_llm_client.complete.return_value = FakeLLMResponse()

    reflector = SessionReflector(llm=mock_llm_client, memory=mock_memory_client)
    await reflector.reflect(
        session=session_long,
        user_id="user-001",
        tenant_id="tenant-001",
    )

    mock_memory_client.interaction_store.assert_called_once()
    call_kwargs = mock_memory_client.interaction_store.call_args.kwargs
    assert call_kwargs["user_id"] == "user-001"
    assert call_kwargs["tenant_id"] == "tenant-001"
    assert call_kwargs["interaction_type"] == "session_reflection"
    assert "session_id" in call_kwargs["data"]
    assert call_kwargs["data"]["session_id"] == "sess-002"


# ---------------------------------------------------------------------------
# Test: reflect stores preferences in memory
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reflect_stores_preferences(
    mock_llm_client: AsyncMock,
    mock_memory_client: AsyncMock,
    session_long: SessionState,
) -> None:
    """Verify memory.user_store called for each extracted preference."""
    reflection_json = json.dumps({
        "accomplished": ["Done something"],
        "pending": [],
        "commitments": [],
        "preferences": ["Prefers bullet points", "Likes short answers"],
    })

    class FakeLLMResponse:
        content = reflection_json
        model_used = "anthropic.claude-3-haiku"
        tier_used = "fast"
        tokens = 90
        latency = 0.2

    mock_llm_client.complete.return_value = FakeLLMResponse()

    reflector = SessionReflector(llm=mock_llm_client, memory=mock_memory_client)
    await reflector.reflect(
        session=session_long,
        user_id="user-001",
        tenant_id="tenant-001",
    )

    assert mock_memory_client.user_store.call_count == 2

    first_call = mock_memory_client.user_store.call_args_list[0].kwargs
    assert first_call["user_id"] == "user-001"
    assert first_call["fact"] == "Prefers bullet points"
    assert first_call["category"] == "preference"

    second_call = mock_memory_client.user_store.call_args_list[1].kwargs
    assert second_call["fact"] == "Likes short answers"
