"""Deadline and commitment checker — periodic background task.

Runs on a configurable interval (default: 1 hour) and scans monitored tenants
for tasks with approaching or missed deadlines, then pushes events to the
memory-service event queue so that Shadow AI agents can surface them to users.

Checks performed each cycle:
1. Deadline check: queries task interactions, identifies due within 2 days or overdue
2. Commitment check: queries session_reflection interactions for commitments with
   due dates that have arrived

Configuration:
- SCHEDULER_ENABLED: set to "false" to disable (default: "true")
- DEADLINE_CHECK_INTERVAL_SEC: seconds between cycles (default: 3600)
- MONITORED_TENANTS: comma-separated tenant IDs to scan (default: empty = no-op)
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog

from common.clients.memory_client import MemoryClient

logger = structlog.get_logger(__name__)

# Threshold: tasks due within this many days trigger "approaching" event
DEADLINE_APPROACHING_DAYS: int = 2


async def run_deadline_checker(
    memory: MemoryClient,
    tenants: list[str],
    interval: int = 3600,
) -> None:
    """Background loop that checks deadlines and pushes events.

    Runs indefinitely until cancelled. All exceptions are caught and logged
    so the observer service never crashes from scheduler failures.

    Args:
        memory: Initialized MemoryClient instance.
        tenants: List of tenant IDs to monitor.
        interval: Seconds to sleep between cycles.
    """
    logger.info(
        "deadline_checker_started",
        tenant_count=len(tenants),
        interval_sec=interval,
    )

    while True:
        try:
            await _run_cycle(memory, tenants)
        except asyncio.CancelledError:
            logger.info("deadline_checker_cancelled")
            raise
        except Exception as exc:
            logger.warning(
                "deadline_checker_cycle_failed",
                error=str(exc),
                error_type=type(exc).__name__,
            )
        await asyncio.sleep(interval)


async def _run_cycle(memory: MemoryClient, tenants: list[str]) -> None:
    """Execute one full check cycle across all monitored tenants."""
    now = datetime.now(timezone.utc)

    for tenant_id in tenants:
        try:
            await _check_deadlines(memory, tenant_id, now)
            await _check_commitments(memory, tenant_id, now)
        except Exception as exc:
            logger.warning(
                "deadline_checker_tenant_failed",
                tenant_id=tenant_id,
                error=str(exc),
                error_type=type(exc).__name__,
            )

    logger.info("deadline_checker_cycle_complete", tenants_checked=len(tenants))


async def _check_deadlines(
    memory: MemoryClient,
    tenant_id: str,
    now: datetime,
) -> None:
    """Check for tasks with approaching or missed deadlines.

    Queries interaction records of type "task" for the tenant. Each task
    interaction is expected to have a "due_date" field in ISO 8601 format
    in its data payload.
    """
    # Query task interactions across all users for this tenant
    interactions = await memory.interaction_recall(
        user_id="__all__",
        tenant_id=tenant_id,
        interaction_type="task",
        limit=100,
    )

    if not interactions:
        return

    approaching_threshold = now + timedelta(days=DEADLINE_APPROACHING_DAYS)

    for interaction in interactions:
        data = interaction.get("data", {})
        due_date_str = data.get("due_date")
        if not due_date_str:
            continue

        due_date = _parse_date(due_date_str)
        if due_date is None:
            continue

        task_id = data.get("task_id", interaction.get("id", "unknown"))
        task_title = data.get("title", f"Task {task_id}")
        user_id = interaction.get("user_id", "__system__")

        if due_date < now:
            # Task is overdue
            await _push_deadline_event(
                memory=memory,
                user_id=user_id,
                tenant_id=tenant_id,
                event_type="deadline_missed",
                task_id=task_id,
                task_title=task_title,
                due_date=due_date_str,
                priority="high",
            )
        elif due_date <= approaching_threshold:
            # Task is due within threshold
            days_remaining = (due_date - now).days
            await _push_deadline_event(
                memory=memory,
                user_id=user_id,
                tenant_id=tenant_id,
                event_type="deadline_approaching",
                task_id=task_id,
                task_title=task_title,
                due_date=due_date_str,
                priority="medium",
                days_remaining=days_remaining,
            )


async def _check_commitments(
    memory: MemoryClient,
    tenant_id: str,
    now: datetime,
) -> None:
    """Check for commitments from session reflections that are now due.

    Queries interaction records of type "session_reflection" looking for
    entries that contain commitments with due dates that have arrived.
    """
    interactions = await memory.interaction_recall(
        user_id="__all__",
        tenant_id=tenant_id,
        interaction_type="session_reflection",
        limit=100,
    )

    if not interactions:
        return

    for interaction in interactions:
        data = interaction.get("data", {})
        commitments = data.get("commitments", [])
        user_id = interaction.get("user_id", "__system__")

        for commitment in commitments:
            if not isinstance(commitment, dict):
                continue

            due_date_str = commitment.get("due_date")
            if not due_date_str:
                continue

            due_date = _parse_date(due_date_str)
            if due_date is None:
                continue

            # Only push events for commitments that are now due or overdue
            if due_date > now:
                continue

            status = commitment.get("status", "pending")
            if status in ("completed", "dismissed"):
                continue

            commitment_text = commitment.get("text", commitment.get("description", ""))
            commitment_id = commitment.get("id", "unknown")

            if due_date < now:
                event_type = "commitment_overdue"
                priority = "high"
            else:
                event_type = "commitment_due"
                priority = "medium"

            await memory.event_queue_push(
                user_id=user_id,
                tenant_id=tenant_id,
                event_type=event_type,
                summary=f"Commitment due: {commitment_text}" if commitment_text else f"Commitment {commitment_id} is due",
                priority=priority,
                source_service="observer",
                metadata={
                    "commitment_id": commitment_id,
                    "due_date": due_date_str,
                    "source_interaction": interaction.get("id", ""),
                },
            )


async def _push_deadline_event(
    memory: MemoryClient,
    user_id: str,
    tenant_id: str,
    event_type: str,
    task_id: str,
    task_title: str,
    due_date: str,
    priority: str,
    days_remaining: int | None = None,
) -> None:
    """Push a deadline-related event to the user's event queue."""
    if event_type == "deadline_missed":
        summary = f"Overdue: {task_title} (was due {due_date})"
    else:
        days_str = f"{days_remaining} day{'s' if days_remaining != 1 else ''}" if days_remaining is not None else "soon"
        summary = f"Due {days_str}: {task_title} (deadline {due_date})"

    metadata: dict[str, Any] = {
        "task_id": task_id,
        "due_date": due_date,
    }
    if days_remaining is not None:
        metadata["days_remaining"] = days_remaining

    await memory.event_queue_push(
        user_id=user_id,
        tenant_id=tenant_id,
        event_type=event_type,
        summary=summary,
        priority=priority,
        source_service="observer",
        metadata=metadata,
    )


def _parse_date(date_str: str) -> datetime | None:
    """Parse an ISO 8601 date/datetime string to a timezone-aware datetime.

    Returns None if parsing fails (graceful degradation).
    """
    try:
        # Handle date-only format (YYYY-MM-DD)
        if len(date_str) == 10:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            return dt.replace(tzinfo=timezone.utc)
        # Handle full ISO datetime
        dt = datetime.fromisoformat(date_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None
