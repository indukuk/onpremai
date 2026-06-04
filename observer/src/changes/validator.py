"""Post-apply validator — compares metrics before and after a change.

Determines whether a change improved metrics or should be rolled back.
Implements validation criteria from REQUIREMENTS.md R6.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Any

import httpx
import structlog

from observer.src.changes.proposal import Change, ChangeStatus
from observer.src.config import ObserverSettings

logger = structlog.get_logger(__name__)


class ValidationResult(str, enum.Enum):
    """Result of post-apply validation."""

    PASSED = "passed"
    FAILED = "failed"
    INSUFFICIENT_DATA = "insufficient_data"


@dataclass
class ValidationReport:
    """Detailed report of a validation check."""

    change_id: str
    result: ValidationResult
    escalation_delta: float = 0.0
    confidence_delta: float = 0.0
    failure_delta: float = 0.0
    latency_ratio: float = 1.0
    breached_criteria: list[str] | None = None
    metrics_before: dict[str, Any] | None = None
    metrics_after: dict[str, Any] | None = None


class ChangeValidator:
    """Validates whether applied changes improved system metrics.

    Compares pre-change snapshot metrics with current metrics.
    Triggers rollback if any threshold is breached.

    Validation criteria (from R6):
    - Escalation rate increased >10% absolute -> rollback
    - Average confidence decreased >10% absolute -> rollback
    - Failure rate increased >5% absolute -> rollback
    - P95 latency increased >50% relative -> rollback
    """

    # Thresholds for rollback
    MAX_ESCALATION_INCREASE: float = 0.10  # 10% absolute
    MAX_CONFIDENCE_DECREASE: float = 0.10  # 10% absolute
    MAX_FAILURE_INCREASE: float = 0.05     # 5% absolute
    MAX_LATENCY_INCREASE_RATIO: float = 1.5  # 50% relative

    def __init__(self, settings: ObserverSettings) -> None:
        self._settings = settings
        self._http_client: httpx.AsyncClient | None = None

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

    async def validate(self, change: Change) -> ValidationReport:
        """Validate a previously applied change.

        Fetches current metrics and compares with the pre-change snapshot.

        Args:
            change: The change to validate (must have snapshot with metrics).

        Returns:
            ValidationReport indicating pass/fail with details.
        """
        # Get pre-change metrics from snapshot
        metrics_before = change.snapshot.get("metrics", {})
        if not metrics_before:
            logger.warning("validation_no_snapshot", change_id=change.id)
            return ValidationReport(
                change_id=change.id,
                result=ValidationResult.INSUFFICIENT_DATA,
            )

        # Fetch current metrics
        metrics_after = await self._fetch_current_metrics(change.task)
        if not metrics_after:
            return ValidationReport(
                change_id=change.id,
                result=ValidationResult.INSUFFICIENT_DATA,
            )

        # Compare metrics
        report = self._compare_metrics(change.id, metrics_before, metrics_after)

        # Update change with validation results
        change.metrics_before = metrics_before
        change.metrics_after = metrics_after

        logger.info(
            "validation_complete",
            change_id=change.id,
            result=report.result.value,
            breached=report.breached_criteria,
        )

        return report

    async def _fetch_current_metrics(self, task: str) -> dict[str, Any]:
        """Fetch current metrics from the gateway admin API."""
        if not self._http_client:
            return {}

        try:
            task_name = task or "default"
            response = await self._http_client.get(
                f"/admin/metrics/{task_name}",
                params={"window": "1h"},
            )
            if response.status_code == 200:
                return response.json()
            logger.warning(
                "validation_metrics_fetch_failed",
                status=response.status_code,
                task=task,
            )
        except httpx.HTTPError as exc:
            logger.error("validation_metrics_fetch_error", error=str(exc))

        return {}

    def _compare_metrics(
        self,
        change_id: str,
        before: dict[str, Any],
        after: dict[str, Any],
    ) -> ValidationReport:
        """Compare before/after metrics against rollback thresholds."""
        breached: list[str] = []

        # Extract values with safe defaults
        before_escalation = float(before.get("escalation_rate", 0.0))
        after_escalation = float(after.get("escalation_rate", 0.0))
        escalation_delta = after_escalation - before_escalation

        before_confidence = float(before.get("avg_confidence", 1.0))
        after_confidence = float(after.get("avg_confidence", 1.0))
        confidence_delta = before_confidence - after_confidence  # positive = worse

        before_failure = float(before.get("failure_rate", 0.0))
        after_failure = float(after.get("failure_rate", 0.0))
        failure_delta = after_failure - before_failure

        before_latency = float(before.get("p95_latency_ms", 1.0))
        after_latency = float(after.get("p95_latency_ms", 1.0))
        latency_ratio = after_latency / before_latency if before_latency > 0 else 1.0

        # Check thresholds
        if escalation_delta > self.MAX_ESCALATION_INCREASE:
            breached.append(
                f"escalation_rate increased by {escalation_delta:.2%} "
                f"(threshold: {self.MAX_ESCALATION_INCREASE:.0%})"
            )

        if confidence_delta > self.MAX_CONFIDENCE_DECREASE:
            breached.append(
                f"avg_confidence decreased by {confidence_delta:.2%} "
                f"(threshold: {self.MAX_CONFIDENCE_DECREASE:.0%})"
            )

        if failure_delta > self.MAX_FAILURE_INCREASE:
            breached.append(
                f"failure_rate increased by {failure_delta:.2%} "
                f"(threshold: {self.MAX_FAILURE_INCREASE:.0%})"
            )

        if latency_ratio > self.MAX_LATENCY_INCREASE_RATIO:
            breached.append(
                f"p95_latency increased by {(latency_ratio - 1):.0%} "
                f"(threshold: {(self.MAX_LATENCY_INCREASE_RATIO - 1):.0%})"
            )

        result = ValidationResult.FAILED if breached else ValidationResult.PASSED

        return ValidationReport(
            change_id=change_id,
            result=result,
            escalation_delta=escalation_delta,
            confidence_delta=confidence_delta,
            failure_delta=failure_delta,
            latency_ratio=latency_ratio,
            breached_criteria=breached if breached else None,
            metrics_before=before,
            metrics_after=after,
        )
