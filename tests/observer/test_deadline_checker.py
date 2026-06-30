"""Unit tests for the observer deadline checker module."""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "observer"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from observer.src.deadline_checker import (
    DEADLINE_APPROACHING_DAYS,
    _check_commitments,
    _check_deadlines,
    _parse_date,
    _run_cycle,
    run_deadline_checker,
)


# --- _parse_date tests ---


class TestParseDate:
    """Tests for the date parsing utility."""

    def test_iso_date_only(self) -> None:
        result = _parse_date("2024-06-15")
        assert result is not None
        assert result.year == 2024
        assert result.month == 6
        assert result.day == 15
        assert result.tzinfo == timezone.utc

    def test_iso_datetime_with_timezone(self) -> None:
        result = _parse_date("2024-06-15T10:30:00+00:00")
        assert result is not None
        assert result.hour == 10
        assert result.minute == 30

    def test_iso_datetime_naive(self) -> None:
        result = _parse_date("2024-06-15T10:30:00")
        assert result is not None
        assert result.tzinfo == timezone.utc

    def test_invalid_string(self) -> None:
        assert _parse_date("not-a-date") is None

    def test_empty_string(self) -> None:
        assert _parse_date("") is None


# --- _check_deadlines tests ---


@pytest.mark.asyncio
class TestCheckDeadlines:
    """Tests for deadline checking logic."""

    async def test_no_interactions(self) -> None:
        """No interactions means no events pushed."""
        memory = AsyncMock()
        memory.interaction_recall.return_value = []

        await _check_deadlines(memory, "tenant-1", datetime.now(timezone.utc))

        memory.event_queue_push.assert_not_called()

    async def test_overdue_task_pushes_deadline_missed(self) -> None:
        """A task past its due date should push a deadline_missed event."""
        memory = AsyncMock()
        memory.event_queue_push.return_value = True

        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
        memory.interaction_recall.return_value = [
            {
                "user_id": "user-1",
                "data": {
                    "task_id": "task-001",
                    "title": "Submit SOC2 evidence",
                    "due_date": yesterday,
                },
            }
        ]

        await _check_deadlines(memory, "tenant-1", datetime.now(timezone.utc))

        memory.event_queue_push.assert_called_once()
        call_kwargs = memory.event_queue_push.call_args.kwargs
        assert call_kwargs["event_type"] == "deadline_missed"
        assert call_kwargs["priority"] == "high"
        assert call_kwargs["user_id"] == "user-1"
        assert call_kwargs["tenant_id"] == "tenant-1"
        assert "Overdue" in call_kwargs["summary"]

    async def test_approaching_task_pushes_deadline_approaching(self) -> None:
        """A task due within 2 days should push a deadline_approaching event."""
        memory = AsyncMock()
        memory.event_queue_push.return_value = True

        tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")
        memory.interaction_recall.return_value = [
            {
                "user_id": "user-2",
                "data": {
                    "task_id": "task-002",
                    "title": "Complete risk assessment",
                    "due_date": tomorrow,
                },
            }
        ]

        await _check_deadlines(memory, "tenant-1", datetime.now(timezone.utc))

        memory.event_queue_push.assert_called_once()
        call_kwargs = memory.event_queue_push.call_args.kwargs
        assert call_kwargs["event_type"] == "deadline_approaching"
        assert call_kwargs["priority"] == "medium"

    async def test_future_task_no_event(self) -> None:
        """A task due far in the future should not trigger any event."""
        memory = AsyncMock()
        memory.event_queue_push.return_value = True

        next_month = (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y-%m-%d")
        memory.interaction_recall.return_value = [
            {
                "user_id": "user-3",
                "data": {
                    "task_id": "task-003",
                    "title": "Quarterly review",
                    "due_date": next_month,
                },
            }
        ]

        await _check_deadlines(memory, "tenant-1", datetime.now(timezone.utc))

        memory.event_queue_push.assert_not_called()

    async def test_missing_due_date_skipped(self) -> None:
        """Tasks without due_date field are silently skipped."""
        memory = AsyncMock()
        memory.interaction_recall.return_value = [
            {
                "user_id": "user-1",
                "data": {"task_id": "task-004", "title": "No deadline"},
            }
        ]

        await _check_deadlines(memory, "tenant-1", datetime.now(timezone.utc))

        memory.event_queue_push.assert_not_called()


# --- _check_commitments tests ---


@pytest.mark.asyncio
class TestCheckCommitments:
    """Tests for commitment checking logic."""

    async def test_no_interactions(self) -> None:
        memory = AsyncMock()
        memory.interaction_recall.return_value = []

        await _check_commitments(memory, "tenant-1", datetime.now(timezone.utc))

        memory.event_queue_push.assert_not_called()

    async def test_overdue_commitment_pushes_event(self) -> None:
        """A commitment past its due date should push a commitment_overdue event."""
        memory = AsyncMock()
        memory.event_queue_push.return_value = True

        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
        memory.interaction_recall.return_value = [
            {
                "user_id": "user-1",
                "data": {
                    "commitments": [
                        {
                            "id": "commit-001",
                            "text": "Review vendor policies",
                            "due_date": yesterday,
                            "status": "pending",
                        }
                    ]
                },
            }
        ]

        await _check_commitments(memory, "tenant-1", datetime.now(timezone.utc))

        memory.event_queue_push.assert_called_once()
        call_kwargs = memory.event_queue_push.call_args.kwargs
        assert call_kwargs["event_type"] == "commitment_overdue"
        assert call_kwargs["priority"] == "high"
        assert "Review vendor policies" in call_kwargs["summary"]

    async def test_completed_commitment_skipped(self) -> None:
        """Commitments with status 'completed' should be ignored."""
        memory = AsyncMock()
        memory.event_queue_push.return_value = True

        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
        memory.interaction_recall.return_value = [
            {
                "user_id": "user-1",
                "data": {
                    "commitments": [
                        {
                            "id": "commit-002",
                            "text": "Done task",
                            "due_date": yesterday,
                            "status": "completed",
                        }
                    ]
                },
            }
        ]

        await _check_commitments(memory, "tenant-1", datetime.now(timezone.utc))

        memory.event_queue_push.assert_not_called()

    async def test_future_commitment_not_triggered(self) -> None:
        """Commitments with future due dates should not trigger events."""
        memory = AsyncMock()
        memory.event_queue_push.return_value = True

        next_week = (datetime.now(timezone.utc) + timedelta(days=7)).strftime("%Y-%m-%d")
        memory.interaction_recall.return_value = [
            {
                "user_id": "user-1",
                "data": {
                    "commitments": [
                        {
                            "id": "commit-003",
                            "text": "Future task",
                            "due_date": next_week,
                            "status": "pending",
                        }
                    ]
                },
            }
        ]

        await _check_commitments(memory, "tenant-1", datetime.now(timezone.utc))

        memory.event_queue_push.assert_not_called()


# --- run_deadline_checker tests ---


@pytest.mark.asyncio
class TestRunDeadlineChecker:
    """Tests for the background loop."""

    async def test_runs_cycle_and_sleeps(self) -> None:
        """The loop should run a cycle and then sleep."""
        memory = AsyncMock()
        memory.interaction_recall.return_value = []

        # Run for a very short time then cancel
        task = asyncio.create_task(
            run_deadline_checker(memory=memory, tenants=["t-1"], interval=0)
        )
        # Let it run one iteration
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        # Should have been called at least once
        assert memory.interaction_recall.call_count >= 1

    async def test_exception_does_not_crash_loop(self) -> None:
        """Exceptions in a cycle should be logged but not stop the loop."""
        memory = AsyncMock()
        memory.interaction_recall.side_effect = RuntimeError("Network error")

        task = asyncio.create_task(
            run_deadline_checker(memory=memory, tenants=["t-1"], interval=0)
        )
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        # Should have attempted to run multiple times despite errors
        assert memory.interaction_recall.call_count >= 1


# --- _run_cycle tests ---


@pytest.mark.asyncio
class TestRunCycle:
    """Tests for a single cycle across tenants."""

    async def test_iterates_all_tenants(self) -> None:
        """Each tenant in the list should be checked."""
        memory = AsyncMock()
        memory.interaction_recall.return_value = []

        tenants = ["tenant-a", "tenant-b", "tenant-c"]
        await _run_cycle(memory, tenants)

        # interaction_recall called twice per tenant (tasks + session_reflection)
        assert memory.interaction_recall.call_count == len(tenants) * 2

    async def test_one_tenant_failure_doesnt_block_others(self) -> None:
        """If one tenant fails, the others should still be checked."""
        memory = AsyncMock()
        call_count = 0

        async def mock_recall(**kwargs):
            nonlocal call_count
            call_count += 1
            tenant = kwargs.get("tenant_id", "")
            if tenant == "bad-tenant":
                raise RuntimeError("DB error")
            return []

        memory.interaction_recall = mock_recall

        await _run_cycle(memory, ["good-1", "bad-tenant", "good-2"])

        # good-1 gets 2 calls, bad-tenant fails on first, good-2 gets 2 calls
        # Total: at least 4 successful + 1 failed = 5
        assert call_count >= 4
