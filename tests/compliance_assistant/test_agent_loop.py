"""Unit tests for the compliance-assistant agent loop.

Covers:
- Normal flow: LLM responds with text (no tool calls)
- Tool call flow: LLM calls a tool, MCP executes it, loop continues
- Max rounds reached: loop terminates after max_tool_rounds
- Confirmation pending: tool requires user approval
- LLM credit exhaustion: switches to data-only mode
- LLM unavailable: switches to data-only mode
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agent.loop import AgentLoop
from src.models import ChatResponse, PendingConfirmation, SessionState, UserContext


# ---------------------------------------------------------------------------
# Helper to build an AgentLoop with mocked deps
# ---------------------------------------------------------------------------


def _build_agent_loop(
    mock_llm_client: AsyncMock,
    mock_memory_client: AsyncMock,
    mock_mcp_client: AsyncMock,
    mock_session_manager: AsyncMock,
    mock_context_builder: AsyncMock,
    mock_skill_loader: AsyncMock,
    mock_skill_matcher: MagicMock,
    mock_playbook_engine: AsyncMock,
    mock_confirmation_handler: AsyncMock,
) -> AgentLoop:
    return AgentLoop(
        llm=mock_llm_client,
        memory=mock_memory_client,
        mcp=mock_mcp_client,
        sessions=mock_session_manager,
        context_builder=mock_context_builder,
        skill_loader=mock_skill_loader,
        skill_matcher=mock_skill_matcher,
        playbook_engine=mock_playbook_engine,
        confirmation_handler=mock_confirmation_handler,
    )


# ---------------------------------------------------------------------------
# Test: Normal text response flow (no tool calls)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_message_normal_text_response(
    mock_llm_client: AsyncMock,
    mock_memory_client: AsyncMock,
    mock_mcp_client: AsyncMock,
    mock_session_manager: AsyncMock,
    mock_context_builder: AsyncMock,
    mock_skill_loader: AsyncMock,
    mock_skill_matcher: MagicMock,
    mock_playbook_engine: AsyncMock,
    mock_confirmation_handler: AsyncMock,
    fake_session: SessionState,
    fake_user_admin: UserContext,
) -> None:
    """LLM returns only text with no tool calls -> returns ChatResponse with message."""
    loop = _build_agent_loop(
        mock_llm_client,
        mock_memory_client,
        mock_mcp_client,
        mock_session_manager,
        mock_context_builder,
        mock_skill_loader,
        mock_skill_matcher,
        mock_playbook_engine,
        mock_confirmation_handler,
    )

    response = await loop.handle_message("What is our readiness?", fake_session, fake_user_admin)

    assert isinstance(response, ChatResponse)
    assert response.message == "Hello! Here is your compliance status."
    assert response.data_only_mode is False
    assert response.pending_confirmation is None
    assert response.session_id == fake_session.session_id
    mock_session_manager.save.assert_called_once()


# ---------------------------------------------------------------------------
# Test: Tool call flow (LLM calls tool, MCP executes, LLM responds text)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_message_tool_call_flow(
    mock_llm_client: AsyncMock,
    mock_memory_client: AsyncMock,
    mock_mcp_client: AsyncMock,
    mock_session_manager: AsyncMock,
    mock_context_builder: AsyncMock,
    mock_skill_loader: AsyncMock,
    mock_skill_matcher: MagicMock,
    mock_playbook_engine: AsyncMock,
    mock_confirmation_handler: AsyncMock,
    fake_session: SessionState,
    fake_user_admin: UserContext,
) -> None:
    """LLM returns tool_calls first round, then text second round."""

    class ToolCallResponse:
        content = ""
        model_used = "anthropic.claude-3-sonnet"
        tier_used = "mid"
        tokens = 200
        latency = 0.5
        tool_calls = [
            {
                "id": "call-001",
                "name": "evidence.check_coverage",
                "arguments": {"framework_id": "SOC2"},
            }
        ]

    class TextResponse:
        content = "Your SOC2 readiness is 85%."
        model_used = "anthropic.claude-3-sonnet"
        tier_used = "mid"
        tokens = 100
        latency = 0.3
        tool_calls: list[dict[str, Any]] = []

    # First call returns tool_calls, second returns text
    mock_llm_client.complete.side_effect = [ToolCallResponse(), TextResponse()]

    loop = _build_agent_loop(
        mock_llm_client,
        mock_memory_client,
        mock_mcp_client,
        mock_session_manager,
        mock_context_builder,
        mock_skill_loader,
        mock_skill_matcher,
        mock_playbook_engine,
        mock_confirmation_handler,
    )

    response = await loop.handle_message("Check SOC2 coverage", fake_session, fake_user_admin)

    assert response.message == "Your SOC2 readiness is 85%."
    assert len(response.actions) == 1
    assert response.actions[0].tool_name == "evidence.check_coverage"
    assert response.actions[0].success is True
    assert mock_mcp_client.call_tool.call_count == 1
    assert mock_llm_client.complete.call_count == 2


# ---------------------------------------------------------------------------
# Test: Max rounds reached
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_message_max_rounds_reached(
    mock_llm_client: AsyncMock,
    mock_memory_client: AsyncMock,
    mock_mcp_client: AsyncMock,
    mock_session_manager: AsyncMock,
    mock_context_builder: AsyncMock,
    mock_skill_loader: AsyncMock,
    mock_skill_matcher: MagicMock,
    mock_playbook_engine: AsyncMock,
    mock_confirmation_handler: AsyncMock,
    fake_session: SessionState,
    fake_user_admin: UserContext,
) -> None:
    """When LLM keeps calling tools for max_tool_rounds, loop terminates gracefully."""

    class AlwaysToolResponse:
        content = ""
        model_used = "anthropic.claude-3-sonnet"
        tier_used = "mid"
        tokens = 200
        latency = 0.5
        tool_calls = [
            {
                "id": "call-loop",
                "name": "evidence.check_coverage",
                "arguments": {"framework_id": "all"},
            }
        ]

    # Always return tool calls
    mock_llm_client.complete.return_value = AlwaysToolResponse()

    loop = _build_agent_loop(
        mock_llm_client,
        mock_memory_client,
        mock_mcp_client,
        mock_session_manager,
        mock_context_builder,
        mock_skill_loader,
        mock_skill_matcher,
        mock_playbook_engine,
        mock_confirmation_handler,
    )

    # Patch settings.max_tool_rounds to a small value for test speed
    with patch("src.agent.loop.settings") as mock_settings:
        mock_settings.max_tool_rounds = 3
        response = await loop.handle_message("run everything", fake_session, fake_user_admin)

    assert "processing limit" in response.message.lower() or "reached" in response.message.lower()
    # Should have 3 tool actions (one per round)
    assert len(response.actions) == 3
    assert response.pending_confirmation is None


# ---------------------------------------------------------------------------
# Test: Confirmation pending (destructive tool)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_message_confirmation_pending(
    mock_llm_client: AsyncMock,
    mock_memory_client: AsyncMock,
    mock_mcp_client: AsyncMock,
    mock_session_manager: AsyncMock,
    mock_context_builder: AsyncMock,
    mock_skill_loader: AsyncMock,
    mock_skill_matcher: MagicMock,
    mock_playbook_engine: AsyncMock,
    mock_confirmation_handler: AsyncMock,
    fake_session: SessionState,
    fake_user_admin: UserContext,
) -> None:
    """When MCP returns confirmation_required, loop pauses and returns pending confirmation."""

    class ToolCallResponse:
        content = "I will delete that evidence record."
        model_used = "anthropic.claude-3-sonnet"
        tier_used = "mid"
        tokens = 100
        latency = 0.3
        tool_calls = [
            {
                "id": "call-delete",
                "name": "evidence.delete",
                "arguments": {"evidence_id": "ev-123"},
            }
        ]

    mock_llm_client.complete.return_value = ToolCallResponse()

    # MCP returns confirmation_required
    mock_mcp_client.call_tool.return_value = {
        "status": "confirmation_required",
        "summary": "Delete evidence record ev-123? This cannot be undone.",
    }

    loop = _build_agent_loop(
        mock_llm_client,
        mock_memory_client,
        mock_mcp_client,
        mock_session_manager,
        mock_context_builder,
        mock_skill_loader,
        mock_skill_matcher,
        mock_playbook_engine,
        mock_confirmation_handler,
    )

    response = await loop.handle_message("delete evidence ev-123", fake_session, fake_user_admin)

    assert response.pending_confirmation is not None
    assert response.pending_confirmation.tool_name == "evidence.delete"
    assert "ev-123" in response.pending_confirmation.summary or "confirm" in response.message.lower()
    mock_session_manager.set_pending_confirmation.assert_called_once()


# ---------------------------------------------------------------------------
# Test: LLM credit exhaustion triggers data-only mode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_message_credit_exhausted(
    mock_llm_client: AsyncMock,
    mock_memory_client: AsyncMock,
    mock_mcp_client: AsyncMock,
    mock_session_manager: AsyncMock,
    mock_context_builder: AsyncMock,
    mock_skill_loader: AsyncMock,
    mock_skill_matcher: MagicMock,
    mock_playbook_engine: AsyncMock,
    mock_confirmation_handler: AsyncMock,
    fake_session: SessionState,
    fake_user_admin: UserContext,
) -> None:
    """LLMCreditExhaustedError switches session to data-only mode."""
    from common.errors import LLMCreditExhaustedError

    mock_llm_client.complete.side_effect = LLMCreditExhaustedError(
        "Budget exhausted", estimated_recovery="2026-07-01"
    )

    loop = _build_agent_loop(
        mock_llm_client,
        mock_memory_client,
        mock_mcp_client,
        mock_session_manager,
        mock_context_builder,
        mock_skill_loader,
        mock_skill_matcher,
        mock_playbook_engine,
        mock_confirmation_handler,
    )

    response = await loop.handle_message("status", fake_session, fake_user_admin)

    assert response.data_only_mode is True
    assert fake_session.mode == "data_only"
    mock_session_manager.save.assert_called()


# ---------------------------------------------------------------------------
# Test: LLM unavailable triggers data-only mode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_message_llm_unavailable(
    mock_llm_client: AsyncMock,
    mock_memory_client: AsyncMock,
    mock_mcp_client: AsyncMock,
    mock_session_manager: AsyncMock,
    mock_context_builder: AsyncMock,
    mock_skill_loader: AsyncMock,
    mock_skill_matcher: MagicMock,
    mock_playbook_engine: AsyncMock,
    mock_confirmation_handler: AsyncMock,
    fake_session: SessionState,
    fake_user_admin: UserContext,
) -> None:
    """LLMUnavailableError switches session to data-only mode."""
    from common.errors import LLMUnavailableError

    mock_llm_client.complete.side_effect = LLMUnavailableError("Gateway down")

    loop = _build_agent_loop(
        mock_llm_client,
        mock_memory_client,
        mock_mcp_client,
        mock_session_manager,
        mock_context_builder,
        mock_skill_loader,
        mock_skill_matcher,
        mock_playbook_engine,
        mock_confirmation_handler,
    )

    response = await loop.handle_message("what is my status", fake_session, fake_user_admin)

    assert response.data_only_mode is True
    assert fake_session.mode == "data_only"


# ---------------------------------------------------------------------------
# Test: handle_confirm success
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_confirm_executes_tool(
    mock_llm_client: AsyncMock,
    mock_memory_client: AsyncMock,
    mock_mcp_client: AsyncMock,
    mock_session_manager: AsyncMock,
    mock_context_builder: AsyncMock,
    mock_skill_loader: AsyncMock,
    mock_skill_matcher: MagicMock,
    mock_playbook_engine: AsyncMock,
    mock_confirmation_handler: AsyncMock,
    fake_session: SessionState,
    fake_user_admin: UserContext,
) -> None:
    """handle_confirm executes the pending tool and returns result."""
    # Set up pending confirmation on session
    fake_session.pending_confirmation = PendingConfirmation(
        confirmation_id="confirm-abc",
        tool_name="evidence.delete",
        summary="Delete evidence ev-123?",
        params={"evidence_id": "ev-123"},
    )

    loop = _build_agent_loop(
        mock_llm_client,
        mock_memory_client,
        mock_mcp_client,
        mock_session_manager,
        mock_context_builder,
        mock_skill_loader,
        mock_skill_matcher,
        mock_playbook_engine,
        mock_confirmation_handler,
    )

    response = await loop.handle_confirm(fake_session, fake_user_admin, "confirm-abc")

    assert response.message  # Non-empty response
    assert len(response.actions) == 1
    assert response.actions[0].tool_name == "evidence.delete"
    mock_confirmation_handler.execute_confirmed.assert_called_once()
    mock_session_manager.clear_pending_confirmation.assert_called_once()


# ---------------------------------------------------------------------------
# Test: handle_confirm with mismatched ID
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_confirm_mismatched_id(
    mock_llm_client: AsyncMock,
    mock_memory_client: AsyncMock,
    mock_mcp_client: AsyncMock,
    mock_session_manager: AsyncMock,
    mock_context_builder: AsyncMock,
    mock_skill_loader: AsyncMock,
    mock_skill_matcher: MagicMock,
    mock_playbook_engine: AsyncMock,
    mock_confirmation_handler: AsyncMock,
    fake_session: SessionState,
    fake_user_admin: UserContext,
) -> None:
    """handle_confirm with wrong confirmation_id returns error message."""
    fake_session.pending_confirmation = PendingConfirmation(
        confirmation_id="confirm-abc",
        tool_name="evidence.delete",
        summary="Delete evidence ev-123?",
        params={"evidence_id": "ev-123"},
    )

    loop = _build_agent_loop(
        mock_llm_client,
        mock_memory_client,
        mock_mcp_client,
        mock_session_manager,
        mock_context_builder,
        mock_skill_loader,
        mock_skill_matcher,
        mock_playbook_engine,
        mock_confirmation_handler,
    )

    response = await loop.handle_confirm(fake_session, fake_user_admin, "wrong-id")

    assert "does not match" in response.message
    mock_confirmation_handler.execute_confirmed.assert_not_called()


# ---------------------------------------------------------------------------
# Test: handle_cancel
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_cancel(
    mock_llm_client: AsyncMock,
    mock_memory_client: AsyncMock,
    mock_mcp_client: AsyncMock,
    mock_session_manager: AsyncMock,
    mock_context_builder: AsyncMock,
    mock_skill_loader: AsyncMock,
    mock_skill_matcher: MagicMock,
    mock_playbook_engine: AsyncMock,
    mock_confirmation_handler: AsyncMock,
    fake_session: SessionState,
    fake_user_admin: UserContext,
) -> None:
    """handle_cancel clears pending confirmation and returns cancel message."""
    fake_session.pending_confirmation = PendingConfirmation(
        confirmation_id="confirm-xyz",
        tool_name="evidence.delete",
        summary="Delete evidence?",
        params={},
    )

    loop = _build_agent_loop(
        mock_llm_client,
        mock_memory_client,
        mock_mcp_client,
        mock_session_manager,
        mock_context_builder,
        mock_skill_loader,
        mock_skill_matcher,
        mock_playbook_engine,
        mock_confirmation_handler,
    )

    response = await loop.handle_cancel(fake_session, fake_user_admin, "confirm-xyz")

    assert "cancelled" in response.message.lower() or "not executed" in response.message.lower()
    mock_session_manager.clear_pending_confirmation.assert_called_once()


# ---------------------------------------------------------------------------
# Test: Data-only mode session routes through data-only handler
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_message_data_only_mode_routes_correctly(
    mock_llm_client: AsyncMock,
    mock_memory_client: AsyncMock,
    mock_mcp_client: AsyncMock,
    mock_session_manager: AsyncMock,
    mock_context_builder: AsyncMock,
    mock_skill_loader: AsyncMock,
    mock_skill_matcher: MagicMock,
    mock_playbook_engine: AsyncMock,
    mock_confirmation_handler: AsyncMock,
    fake_session_data_only: SessionState,
    fake_user_admin: UserContext,
) -> None:
    """When session is data_only, message is routed to data-only handler."""
    from common.errors import LLMUnavailableError

    # LLM still down (ping fails)
    mock_llm_client.complete.side_effect = LLMUnavailableError("Still down")

    loop = _build_agent_loop(
        mock_llm_client,
        mock_memory_client,
        mock_mcp_client,
        mock_session_manager,
        mock_context_builder,
        mock_skill_loader,
        mock_skill_matcher,
        mock_playbook_engine,
        mock_confirmation_handler,
    )

    response = await loop.handle_message("status", fake_session_data_only, fake_user_admin)

    assert response.data_only_mode is True
    # MCP should have been called with the status tool
    mock_mcp_client.call_tool.assert_called()


# ---------------------------------------------------------------------------
# Test: Tool call with string arguments (JSON string parsing)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_message_tool_call_string_arguments(
    mock_llm_client: AsyncMock,
    mock_memory_client: AsyncMock,
    mock_mcp_client: AsyncMock,
    mock_session_manager: AsyncMock,
    mock_context_builder: AsyncMock,
    mock_skill_loader: AsyncMock,
    mock_skill_matcher: MagicMock,
    mock_playbook_engine: AsyncMock,
    mock_confirmation_handler: AsyncMock,
    fake_session: SessionState,
    fake_user_admin: UserContext,
) -> None:
    """Tool call with arguments as JSON string (not dict) is parsed correctly."""

    class ToolCallResponse:
        content = ""
        model_used = "anthropic.claude-3-sonnet"
        tier_used = "mid"
        tokens = 200
        latency = 0.5
        tool_calls = [
            {
                "id": "call-str-args",
                "name": "evidence.check_coverage",
                "arguments": '{"framework_id": "ISO27001"}',  # JSON string
            }
        ]

    class TextResponse:
        content = "ISO 27001 coverage is at 72%."
        model_used = "anthropic.claude-3-sonnet"
        tier_used = "mid"
        tokens = 80
        latency = 0.2
        tool_calls: list[dict[str, Any]] = []

    mock_llm_client.complete.side_effect = [ToolCallResponse(), TextResponse()]

    loop = _build_agent_loop(
        mock_llm_client,
        mock_memory_client,
        mock_mcp_client,
        mock_session_manager,
        mock_context_builder,
        mock_skill_loader,
        mock_skill_matcher,
        mock_playbook_engine,
        mock_confirmation_handler,
    )

    response = await loop.handle_message("check ISO coverage", fake_session, fake_user_admin)

    assert response.message == "ISO 27001 coverage is at 72%."
    # Verify MCP was called with the parsed dict
    call_args = mock_mcp_client.call_tool.call_args
    assert call_args.kwargs.get("params") == {"framework_id": "ISO27001"} or \
           call_args[1].get("params") == {"framework_id": "ISO27001"}
