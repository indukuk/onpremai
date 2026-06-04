"""Rollback engine — reverts changes to pre-change state.

Restores configuration from saved snapshots when validation fails.
Records rollbacks for circuit breaker tracking.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx
import structlog

from observer.src.changes.proposal import Change, ChangeStatus
from observer.src.config import ObserverSettings

logger = structlog.get_logger(__name__)


class RollbackEngine:
    """Reverts applied changes using saved snapshots.

    When validation fails, this engine restores the previous configuration
    by calling the gateway admin API with the snapshot's original values.
    """

    def __init__(self, settings: ObserverSettings) -> None:
        self._settings = settings
        self._http_client: httpx.AsyncClient | None = None
        self._rollback_history: list[dict[str, Any]] = []

    async def start(self) -> None:
        """Initialize the HTTP client."""
        self._http_client = httpx.AsyncClient(
            base_url=self._settings.llm_gateway_admin_url,
            timeout=httpx.Timeout(30.0),
        )

    async def close(self) -> None:
        """Shutdown the HTTP client."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None

    async def rollback(self, change: Change) -> bool:
        """Rollback a change using its saved snapshot.

        Args:
            change: The change to rollback (must have snapshot).

        Returns:
            True if rollback succeeded, False otherwise.
        """
        if not change.snapshot:
            logger.error("rollback_no_snapshot", change_id=change.id)
            return False

        success = await self._restore_snapshot(change)

        if success:
            change.status = ChangeStatus.ROLLED_BACK
            change.rolled_back_at = datetime.now(timezone.utc).isoformat()
            self._rollback_history.append({
                "change_id": change.id,
                "rolled_back_at": change.rolled_back_at,
                "change_type": change.change_type.value,
                "task": change.task,
            })
            logger.info(
                "change_rolled_back",
                change_id=change.id,
                task=change.task,
                change_type=change.change_type.value,
            )
        else:
            logger.error(
                "rollback_failed",
                change_id=change.id,
                task=change.task,
            )

        return success

    async def rollback_canary(self, change: Change) -> bool:
        """Rollback a canary experiment.

        Args:
            change: The canary change to rollback.

        Returns:
            True if canary rollback succeeded.
        """
        if not self._http_client:
            return False

        try:
            task_name = change.task or "default"
            response = await self._http_client.post(
                f"/admin/canary/{task_name}/rollback",
            )

            if response.status_code == 200:
                change.status = ChangeStatus.CANARY_FAILED
                change.rolled_back_at = datetime.now(timezone.utc).isoformat()
                self._rollback_history.append({
                    "change_id": change.id,
                    "rolled_back_at": change.rolled_back_at,
                    "change_type": change.change_type.value,
                    "task": change.task,
                    "was_canary": True,
                })
                logger.info("canary_rolled_back", change_id=change.id, task=change.task)
                return True

            logger.error(
                "canary_rollback_failed",
                change_id=change.id,
                status=response.status_code,
            )
        except httpx.HTTPError as exc:
            logger.error("canary_rollback_error", change_id=change.id, error=str(exc))

        return False

    async def _restore_snapshot(self, change: Change) -> bool:
        """Restore the gateway configuration from a snapshot."""
        if not self._http_client:
            return False

        routing_snapshot = change.snapshot.get("routing")
        if not routing_snapshot:
            logger.warning("snapshot_missing_routing", change_id=change.id)
            return False

        try:
            # Restore routing config
            response = await self._http_client.post(
                "/admin/routing",
                json=routing_snapshot,
            )

            if response.status_code == 200:
                return True

            logger.error(
                "snapshot_restore_failed",
                change_id=change.id,
                status=response.status_code,
                body=response.text[:200],
            )
        except httpx.HTTPError as exc:
            logger.error("snapshot_restore_error", change_id=change.id, error=str(exc))

        return False

    def get_recent_rollbacks(self, window_hours: int = 6) -> list[dict[str, Any]]:
        """Get rollbacks within the specified time window.

        Used by the circuit breaker to count recent rollbacks.
        """
        now = datetime.now(timezone.utc)
        recent: list[dict[str, Any]] = []

        for rb in self._rollback_history:
            rb_time = datetime.fromisoformat(rb["rolled_back_at"])
            if rb_time.tzinfo is None:
                rb_time = rb_time.replace(tzinfo=timezone.utc)
            hours_ago = (now - rb_time).total_seconds() / 3600
            if hours_ago <= window_hours:
                recent.append(rb)

        return recent

    def get_rollback_count(self) -> int:
        """Get total rollback count."""
        return len(self._rollback_history)
