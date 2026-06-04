"""Change applier — dispatches changes to auto/canary/human handlers.

Implements the 3-tier apply engine:
- Tier 1 (AUTO): Direct config changes via gateway admin API
- Tier 2 (CANARY): Deploy to X% of traffic, monitor, promote/rollback
- Tier 3 (HUMAN): Store recommendation, notify, wait for approval
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx
import structlog

from observer.src.changes.proposal import ApplyTier, Change, ChangeStatus
from observer.src.config import ObserverSettings

logger = structlog.get_logger(__name__)


class ChangeApplier:
    """Applies changes through the appropriate tier mechanism.

    Handles snapshotting pre-change state, applying via the gateway admin API,
    and scheduling post-apply validation.
    """

    def __init__(self, settings: ObserverSettings) -> None:
        self._settings = settings
        self._http_client: httpx.AsyncClient | None = None
        self._pending_validations: list[dict[str, Any]] = []
        self._human_queue: list[Change] = []

    async def start(self) -> None:
        """Initialize the HTTP client for gateway admin API."""
        self._http_client = httpx.AsyncClient(
            base_url=self._settings.llm_gateway_admin_url,
            timeout=httpx.Timeout(30.0),
        )

    async def close(self) -> None:
        """Shutdown the HTTP client."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None

    async def apply(self, change: Change, circuit_breaker_open: bool = False) -> Change:
        """Apply a change using the appropriate tier mechanism.

        Args:
            change: The change to apply.
            circuit_breaker_open: If True, force all changes to HUMAN tier.

        Returns:
            The updated Change object with new status.
        """
        # Circuit breaker override
        if circuit_breaker_open and change.apply_tier != ApplyTier.HUMAN:
            logger.info(
                "circuit_breaker_forcing_human",
                change_id=change.id,
                original_tier=change.apply_tier.value,
            )
            change.apply_tier = ApplyTier.HUMAN

        if change.apply_tier == ApplyTier.AUTO:
            return await self._apply_auto(change)
        elif change.apply_tier == ApplyTier.CANARY:
            return await self._apply_canary(change)
        else:
            return self._queue_for_human(change)

    async def _apply_auto(self, change: Change) -> Change:
        """Tier 1: Auto-apply directly via gateway admin API."""
        # Save snapshot before applying
        snapshot = await self._take_snapshot(change)
        change.snapshot = snapshot

        # Apply the change
        success = await self._execute_change(change)

        if success:
            change.status = ChangeStatus.APPLIED
            change.applied_at = datetime.now(timezone.utc).isoformat()
            # Schedule validation
            self._pending_validations.append({
                "change_id": change.id,
                "scheduled_at": datetime.now(timezone.utc).isoformat(),
                "delay_minutes": self._settings.validation_delay_minutes,
            })
            logger.info(
                "change_auto_applied",
                change_id=change.id,
                task=change.task,
                description=change.description,
            )
        else:
            change.status = ChangeStatus.ROLLED_BACK
            logger.error("change_auto_apply_failed", change_id=change.id)

        return change

    async def _apply_canary(self, change: Change) -> Change:
        """Tier 2: Deploy as canary with traffic split."""
        if not self._http_client:
            change.status = ChangeStatus.PROPOSED
            return change

        try:
            payload = {
                "traffic_pct": self._settings.canary_traffic_pct,
                "min_samples": self._settings.canary_min_samples,
                "change_id": change.id,
            }

            # Add change-specific config to canary payload
            if change.config_diff:
                payload["config"] = change.config_diff

            task_name = change.task or "default"
            response = await self._http_client.post(
                f"/admin/canary/{task_name}/set",
                json=payload,
            )

            if response.status_code == 200:
                change.status = ChangeStatus.CANARY_RUNNING
                change.applied_at = datetime.now(timezone.utc).isoformat()
                logger.info(
                    "canary_deployed",
                    change_id=change.id,
                    task=change.task,
                    traffic_pct=self._settings.canary_traffic_pct,
                )
            else:
                change.status = ChangeStatus.PROPOSED
                logger.error(
                    "canary_deploy_failed",
                    change_id=change.id,
                    status=response.status_code,
                    body=response.text[:200],
                )
        except httpx.HTTPError as exc:
            change.status = ChangeStatus.PROPOSED
            logger.error("canary_deploy_error", change_id=change.id, error=str(exc))

        return change

    def _queue_for_human(self, change: Change) -> Change:
        """Tier 3: Queue change for human approval."""
        change.status = ChangeStatus.PROPOSED
        self._human_queue.append(change)
        logger.info(
            "change_queued_for_human",
            change_id=change.id,
            change_type=change.change_type.value,
            confidence=change.confidence,
        )
        return change

    async def _take_snapshot(self, change: Change) -> dict[str, Any]:
        """Save pre-change state for potential rollback."""
        if not self._http_client:
            return {}

        snapshot: dict[str, Any] = {
            "taken_at": datetime.now(timezone.utc).isoformat(),
            "change_id": change.id,
        }

        try:
            task_name = change.task or "default"
            response = await self._http_client.get(
                f"/admin/metrics/{task_name}",
            )
            if response.status_code == 200:
                snapshot["metrics"] = response.json()

            # Get current routing config
            response = await self._http_client.get("/admin/routing")
            if response.status_code == 200:
                snapshot["routing"] = response.json()

        except httpx.HTTPError as exc:
            logger.warning("snapshot_fetch_error", error=str(exc))

        return snapshot

    async def _execute_change(self, change: Change) -> bool:
        """Execute a change via the gateway admin API."""
        if not self._http_client:
            return False

        try:
            if change.change_type.value == "routing":
                response = await self._http_client.post(
                    "/admin/routing",
                    json=change.config_diff,
                )
            elif change.change_type.value == "threshold":
                response = await self._http_client.post(
                    "/admin/threshold",
                    json=change.config_diff,
                )
            elif change.change_type.value == "pattern":
                # Patterns go to memory service, not gateway
                return await self._apply_pattern_change(change)
            else:
                logger.warning(
                    "unsupported_auto_apply_type",
                    change_type=change.change_type.value,
                )
                return False

            return response.status_code == 200

        except httpx.HTTPError as exc:
            logger.error("change_execute_error", change_id=change.id, error=str(exc))
            return False

    async def _apply_pattern_change(self, change: Change) -> bool:
        """Apply a pattern change to the memory service."""
        try:
            async with httpx.AsyncClient(
                base_url=self._settings.memory_url,
                timeout=httpx.Timeout(15.0),
            ) as client:
                response = await client.post(
                    "/patterns",
                    json=change.config_diff,
                )
                return response.status_code in (200, 201)
        except httpx.HTTPError as exc:
            logger.error("pattern_change_error", change_id=change.id, error=str(exc))
            return False

    def get_pending_validations(self) -> list[dict[str, Any]]:
        """Get list of changes pending validation."""
        return list(self._pending_validations)

    def clear_validation(self, change_id: str) -> None:
        """Remove a completed validation from pending list."""
        self._pending_validations = [
            v for v in self._pending_validations if v["change_id"] != change_id
        ]

    def get_human_queue(self) -> list[Change]:
        """Get pending human approval queue."""
        return list(self._human_queue)

    def approve_change(self, change_id: str) -> Change | None:
        """Approve a human-tier change."""
        for i, change in enumerate(self._human_queue):
            if change.id == change_id:
                change.status = ChangeStatus.APPROVED
                self._human_queue.pop(i)
                return change
        return None

    def reject_change(self, change_id: str) -> Change | None:
        """Reject a human-tier change."""
        for i, change in enumerate(self._human_queue):
            if change.id == change_id:
                change.status = ChangeStatus.REJECTED
                self._human_queue.pop(i)
                return change
        return None
