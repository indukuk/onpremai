"""Unit tests for data-only mode (keyword matching fallback).

Covers:
- Keyword matching: status, tasks, overdue, evidence, risks, audit, team
- Unknown keyword returns the data-only menu
- Partial match (keyword in sentence)
- MCP tool call success formatting
- MCP tool call error handling
- Estimated recovery time display
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.agent.data_only_mode import (
    KeywordIntent,
    _build_data_only_menu,
    _format_data_response,
    handle_data_only_message,
    match_keyword_intent,
)
from src.models import SessionState, UserContext


# ---------------------------------------------------------------------------
# Test: match_keyword_intent - direct keyword matches
# ---------------------------------------------------------------------------


class TestKeywordMatching:
    """Tests for the match_keyword_intent function."""

    def test_status_keyword(self) -> None:
        """'status' matches the evidence.check_coverage tool."""
        intent = match_keyword_intent("status")
        assert intent is not None
        assert intent.tool_name == "evidence.check_coverage"
        assert intent.params == {"framework_id": "all"}

    def test_tasks_keyword(self) -> None:
        """'tasks' matches the memory.task_list tool."""
        intent = match_keyword_intent("tasks")
        assert intent is not None
        assert intent.tool_name == "memory.task_list"
        assert intent.params == {"status": "open"}

    def test_overdue_keyword(self) -> None:
        """'overdue' matches the escalation.check_overdue tool."""
        intent = match_keyword_intent("overdue")
        assert intent is not None
        assert intent.tool_name == "escalation.check_overdue"
        assert intent.params == {"framework_id": "all"}

    def test_evidence_keyword(self) -> None:
        """'evidence' matches evidence.check_coverage."""
        intent = match_keyword_intent("evidence")
        assert intent is not None
        assert intent.tool_name == "evidence.check_coverage"

    def test_risks_keyword(self) -> None:
        """'risks' matches risk.list."""
        intent = match_keyword_intent("risks")
        assert intent is not None
        assert intent.tool_name == "risk.list"

    def test_risk_singular_keyword(self) -> None:
        """'risk' (singular) also matches risk.list."""
        intent = match_keyword_intent("risk")
        assert intent is not None
        assert intent.tool_name == "risk.list"

    def test_audit_keyword(self) -> None:
        """'audit' matches audit.get_readiness."""
        intent = match_keyword_intent("audit")
        assert intent is not None
        assert intent.tool_name == "audit.get_readiness"

    def test_team_keyword(self) -> None:
        """'team' matches users.list."""
        intent = match_keyword_intent("team")
        assert intent is not None
        assert intent.tool_name == "users.list"

    def test_readiness_keyword(self) -> None:
        """'readiness' matches evidence.check_coverage."""
        intent = match_keyword_intent("readiness")
        assert intent is not None
        assert intent.tool_name == "evidence.check_coverage"

    def test_deadline_keyword(self) -> None:
        """'deadline' matches escalation.check_overdue."""
        intent = match_keyword_intent("deadline")
        assert intent is not None
        assert intent.tool_name == "escalation.check_overdue"

    def test_controls_keyword(self) -> None:
        """'controls' matches evidence.check_coverage."""
        intent = match_keyword_intent("controls")
        assert intent is not None
        assert intent.tool_name == "evidence.check_coverage"

    def test_gaps_keyword(self) -> None:
        """'gaps' matches evidence.check_coverage with show_gaps."""
        intent = match_keyword_intent("gaps")
        assert intent is not None
        assert intent.tool_name == "evidence.check_coverage"
        assert intent.params.get("show_gaps") is True

    def test_unknown_keyword_returns_none(self) -> None:
        """Unknown keyword returns None (will show menu)."""
        intent = match_keyword_intent("banana")
        assert intent is None

    def test_empty_string_returns_none(self) -> None:
        """Empty string returns None."""
        intent = match_keyword_intent("")
        assert intent is None

    def test_case_insensitive_match(self) -> None:
        """Keywords are matched case-insensitively."""
        intent = match_keyword_intent("STATUS")
        assert intent is not None
        assert intent.tool_name == "evidence.check_coverage"

    def test_mixed_case_match(self) -> None:
        """Mixed case keywords match."""
        intent = match_keyword_intent("Overdue")
        assert intent is not None
        assert intent.tool_name == "escalation.check_overdue"


# ---------------------------------------------------------------------------
# Test: Partial keyword matching (keyword in a sentence)
# ---------------------------------------------------------------------------


class TestPartialMatching:
    """Tests for keyword matching within sentences."""

    def test_keyword_in_sentence(self) -> None:
        """Keyword embedded in a sentence is matched."""
        intent = match_keyword_intent("show me the status of controls")
        assert intent is not None
        # Should match either 'status' or 'controls'
        assert intent.tool_name == "evidence.check_coverage"

    def test_overdue_in_question(self) -> None:
        """'overdue' in a full question is matched."""
        intent = match_keyword_intent("what items are overdue?")
        assert intent is not None
        assert intent.tool_name == "escalation.check_overdue"

    def test_multiple_keywords_best_match(self) -> None:
        """When multiple keywords appear, best scoring one wins."""
        intent = match_keyword_intent("show me audit readiness")
        assert intent is not None
        # Both 'audit' and 'readiness' are keywords; one should win
        assert intent.tool_name in ("audit.get_readiness", "evidence.check_coverage")

    def test_no_match_in_irrelevant_text(self) -> None:
        """Text without any recognized keywords returns None."""
        intent = match_keyword_intent("hello how are you today")
        assert intent is None


# ---------------------------------------------------------------------------
# Test: handle_data_only_message
# ---------------------------------------------------------------------------


class TestHandleDataOnlyMessage:
    """Tests for the handle_data_only_message async function."""

    @pytest.fixture
    def session(self) -> SessionState:
        return SessionState(
            session_id="sess-data-only",
            tenant_id="tenant-001",
            user_id="user-001",
            role="admin",
            mode="data_only",
        )

    @pytest.fixture
    def user(self) -> UserContext:
        return UserContext(
            tenant_id="tenant-001",
            user_id="user-001",
            role="admin",
            email="admin@acme.com",
            name="Admin",
        )

    @pytest.mark.asyncio
    async def test_matched_keyword_calls_mcp(
        self,
        session: SessionState,
        user: UserContext,
        mock_mcp_client: AsyncMock,
    ) -> None:
        """Matched keyword triggers MCP tool call and returns formatted data."""
        mock_mcp_client.call_tool.return_value = {
            "status": "success",
            "data": {"readiness": "85%", "controls_met": 42},
        }

        result = await handle_data_only_message(
            message="status",
            session=session,
            user=user,
            mcp=mock_mcp_client,
        )

        assert "Readiness" in result or "readiness" in result.lower()
        mock_mcp_client.call_tool.assert_called_once()

    @pytest.mark.asyncio
    async def test_unmatched_keyword_shows_menu(
        self,
        session: SessionState,
        user: UserContext,
        mock_mcp_client: AsyncMock,
    ) -> None:
        """Unmatched keyword returns the data-only menu."""
        result = await handle_data_only_message(
            message="banana",
            session=session,
            user=user,
            mcp=mock_mcp_client,
        )

        assert "data-only mode" in result.lower()
        assert "STATUS" in result
        assert "TASKS" in result
        assert "OVERDUE" in result
        mock_mcp_client.call_tool.assert_not_called()

    @pytest.mark.asyncio
    async def test_mcp_error_returns_friendly_message(
        self,
        session: SessionState,
        user: UserContext,
        mock_mcp_client: AsyncMock,
    ) -> None:
        """MCP tool error returns user-friendly error message."""
        mock_mcp_client.call_tool.return_value = {
            "status": "error",
            "message": "Service temporarily unavailable",
        }

        result = await handle_data_only_message(
            message="status",
            session=session,
            user=user,
            mcp=mock_mcp_client,
        )

        assert "failed" in result.lower() or "error" in result.lower()
        assert "Service temporarily unavailable" in result

    @pytest.mark.asyncio
    async def test_estimated_recovery_shown(
        self,
        session: SessionState,
        user: UserContext,
        mock_mcp_client: AsyncMock,
    ) -> None:
        """Estimated recovery time is displayed in menu."""
        result = await handle_data_only_message(
            message="xyz-no-match",
            session=session,
            user=user,
            mcp=mock_mcp_client,
            estimated_recovery="2026-07-01T00:00:00Z",
        )

        assert "2026-07-01" in result

    @pytest.mark.asyncio
    async def test_list_data_formatted_correctly(
        self,
        session: SessionState,
        user: UserContext,
        mock_mcp_client: AsyncMock,
    ) -> None:
        """List data from MCP is formatted as bullet points."""
        mock_mcp_client.call_tool.return_value = {
            "status": "success",
            "data": [
                {"title": "Upload SOC2 evidence", "status": "open"},
                {"title": "Review access controls", "status": "overdue"},
            ],
        }

        result = await handle_data_only_message(
            message="tasks",
            session=session,
            user=user,
            mcp=mock_mcp_client,
        )

        assert "Upload SOC2 evidence" in result
        assert "Review access controls" in result
        assert "(open)" in result
        assert "(overdue)" in result


# ---------------------------------------------------------------------------
# Test: _format_data_response
# ---------------------------------------------------------------------------


class TestFormatDataResponse:
    """Tests for the _format_data_response helper."""

    def test_dict_data_formats_key_value(self) -> None:
        """Dict data is formatted as key-value pairs."""
        data = {"readiness": "85%", "total_controls": 50}
        result = _format_data_response(data, "Compliance Status", None)
        assert "Readiness: 85%" in result
        assert "Total Controls: 50" in result

    def test_list_data_formats_bullets(self) -> None:
        """List data is formatted as bullet items."""
        data = [
            {"title": "Task A", "status": "open"},
            {"title": "Task B", "status": "done"},
        ]
        result = _format_data_response(data, "Open Tasks", None)
        assert "Task A" in result
        assert "Task B" in result

    def test_list_capped_at_20(self) -> None:
        """List data is capped at 20 items."""
        data = [{"title": f"Item {i}"} for i in range(30)]
        result = _format_data_response(data, "Many Items", None)
        assert "Item 19" in result
        assert "Item 20" not in result

    def test_scalar_data_converted_to_string(self) -> None:
        """Non-dict/list data is converted to string."""
        result = _format_data_response("Simple text result", "Result", None)
        assert "Simple text result" in result

    def test_private_keys_excluded(self) -> None:
        """Dict keys starting with _ are excluded."""
        data = {"readiness": "85%", "_internal_id": "xyz"}
        result = _format_data_response(data, "Status", None)
        assert "Readiness" in result
        assert "_internal_id" not in result
        assert "xyz" not in result

    def test_includes_data_only_note(self) -> None:
        """Response includes data-only mode note."""
        result = _format_data_response({"x": 1}, "Test", None)
        assert "data-only mode" in result.lower()

    def test_includes_recovery_time(self) -> None:
        """When recovery time is provided, it's included."""
        result = _format_data_response({"x": 1}, "Test", "2026-08-01")
        assert "2026-08-01" in result


# ---------------------------------------------------------------------------
# Test: _build_data_only_menu
# ---------------------------------------------------------------------------


class TestBuildDataOnlyMenu:
    """Tests for the _build_data_only_menu helper."""

    def test_menu_lists_all_keywords(self) -> None:
        """Menu lists all supported keywords."""
        menu = _build_data_only_menu(None)
        assert "STATUS" in menu
        assert "TASKS" in menu
        assert "EVIDENCE" in menu
        assert "OVERDUE" in menu
        assert "RISKS" in menu
        assert "AUDIT" in menu
        assert "TEAM" in menu

    def test_menu_explains_data_only_mode(self) -> None:
        """Menu explains why it's in data-only mode."""
        menu = _build_data_only_menu(None)
        assert "data-only mode" in menu.lower()
        assert "budget" in menu.lower()

    def test_menu_includes_recovery_time(self) -> None:
        """Menu shows estimated recovery when available."""
        menu = _build_data_only_menu("2026-07-15")
        assert "2026-07-15" in menu

    def test_menu_without_recovery_time(self) -> None:
        """Menu works without estimated recovery."""
        menu = _build_data_only_menu(None)
        assert "Estimated resumption" not in menu
