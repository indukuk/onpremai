"""Self-regulation — weekly evaluation of observer's own performance.

Counts changes applied, rolled back, and successful in the last 7 days.
Adjusts autonomy level based on success rate:
- > 90% success: relax autonomy (expand Tier 1 scope)
- < 70% success: tighten autonomy (reduce to Tier 2/3 only)
Stores autonomy level in memory-service for persistence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx
import structlog

from observer.src.changes.proposal import Change, ChangeStatus
from observer.src.config import ObserverSettings

logger = structlog.get_logger(__name__)


@dataclass
class AutonomyLevel:
    """Current autonomy configuration for the observer."""

    level: str = "standard"  # "restricted", "standard", "expanded"
    min_confidence: float = 0.80
    min_samples: int = 20
    max_auto_applies_per_day: int = 10
    allowed_auto_types: list[str] = field(
        default_factory=lambda: ["routing", "threshold", "pattern"]
    )
    last_adjusted: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    reason: str = "initial"


@dataclass
class SelfEvalResult:
    """Result of a weekly self-evaluation cycle."""

    eval_id: str = ""
    period_start: str = ""
    period_end: str = ""
    total_changes: int = 0
    applied_count: int = 0
    rolled_back_count: int = 0
    validated_count: int = 0
    success_rate: float = 0.0
    previous_autonomy: str = ""
    new_autonomy: str = ""
    adjustment_made: bool = False
    evaluated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class SelfRegulator:
    """Weekly self-evaluation and autonomy adjustment.

    Examines the observer's own track record and adjusts its operational
    parameters accordingly. This creates a feedback loop where good
    performance earns more autonomy and poor performance triggers
    restrictions.
    """

    # Thresholds for autonomy adjustment
    EXPAND_THRESHOLD: float = 0.90
    RESTRICT_THRESHOLD: float = 0.70

    def __init__(self, settings: ObserverSettings) -> None:
        self._settings = settings
        self._autonomy = AutonomyLevel(
            min_confidence=settings.auto_apply_min_confidence,
            min_samples=settings.auto_apply_min_samples,
            max_auto_applies_per_day=settings.max_auto_applies_per_day,
        )
        self._eval_history: list[SelfEvalResult] = []
        self._change_history: list[Change] = []
        self._memory_client: httpx.AsyncClient | None = None

    async def start(self) -> None:
        """Initialize the memory service client and restore state."""
        self._memory_client = httpx.AsyncClient(
            base_url=self._settings.memory_url,
            timeout=httpx.Timeout(15.0),
        )
        await self._restore_autonomy_level()

    async def close(self) -> None:
        """Shutdown the memory service client."""
        if self._memory_client:
            await self._memory_client.aclose()
            self._memory_client = None

    @property
    def autonomy(self) -> AutonomyLevel:
        """Current autonomy level."""
        return self._autonomy

    def record_change(self, change: Change) -> None:
        """Record a change outcome for future self-evaluation.

        Args:
            change: The change with its final status.
        """
        self._change_history.append(change)
        # Keep only last 30 days of history (at ~10/day max, that's 300 entries)
        max_history = self._settings.max_auto_applies_per_day * 30
        if len(self._change_history) > max_history:
            self._change_history = self._change_history[-max_history:]

    async def evaluate(self) -> SelfEvalResult:
        """Run weekly self-evaluation and adjust autonomy.

        Counts outcomes from the past 7 days and adjusts operational
        parameters based on success rate.

        Returns:
            SelfEvalResult with the evaluation outcome.
        """
        from datetime import timedelta
        from uuid import uuid4

        now = datetime.now(timezone.utc)
        week_ago = now - timedelta(days=7)
        week_ago_str = week_ago.isoformat()
        now_str = now.isoformat()

        # Filter changes from the past week
        recent_changes = [
            c for c in self._change_history
            if c.proposed_at >= week_ago_str
        ]

        # Count outcomes
        applied_count = sum(
            1 for c in recent_changes
            if c.status in (ChangeStatus.APPLIED, ChangeStatus.VALIDATED, ChangeStatus.CANARY_PASSED)
        )
        rolled_back_count = sum(
            1 for c in recent_changes
            if c.status in (ChangeStatus.ROLLED_BACK, ChangeStatus.CANARY_FAILED)
        )
        validated_count = sum(
            1 for c in recent_changes
            if c.status == ChangeStatus.VALIDATED
        )

        total_resolved = applied_count + rolled_back_count
        success_rate = validated_count / total_resolved if total_resolved > 0 else 1.0

        # Determine adjustment
        previous_autonomy = self._autonomy.level
        adjustment_made = False

        if total_resolved >= 5:  # Need minimum data to adjust
            if success_rate > self.EXPAND_THRESHOLD:
                adjustment_made = self._expand_autonomy()
            elif success_rate < self.RESTRICT_THRESHOLD:
                adjustment_made = self._restrict_autonomy()

        result = SelfEvalResult(
            eval_id=f"eval_{uuid4().hex[:8]}",
            period_start=week_ago_str,
            period_end=now_str,
            total_changes=len(recent_changes),
            applied_count=applied_count,
            rolled_back_count=rolled_back_count,
            validated_count=validated_count,
            success_rate=success_rate,
            previous_autonomy=previous_autonomy,
            new_autonomy=self._autonomy.level,
            adjustment_made=adjustment_made,
        )

        self._eval_history.append(result)
        if len(self._eval_history) > 52:
            self._eval_history = self._eval_history[-52:]

        # Persist updated autonomy level
        await self._persist_autonomy_level()

        logger.info(
            "self_eval_complete",
            eval_id=result.eval_id,
            total_changes=len(recent_changes),
            success_rate=round(success_rate, 3),
            previous_autonomy=previous_autonomy,
            new_autonomy=self._autonomy.level,
            adjustment_made=adjustment_made,
        )

        return result

    def _expand_autonomy(self) -> bool:
        """Relax autonomy constraints (earned through good performance)."""
        if self._autonomy.level == "expanded":
            return False

        previous = self._autonomy.level

        if previous == "restricted":
            # Restricted -> Standard
            self._autonomy.level = "standard"
            self._autonomy.min_confidence = self._settings.auto_apply_min_confidence
            self._autonomy.min_samples = self._settings.auto_apply_min_samples
            self._autonomy.max_auto_applies_per_day = self._settings.max_auto_applies_per_day
            self._autonomy.allowed_auto_types = ["routing", "threshold", "pattern"]
        elif previous == "standard":
            # Standard -> Expanded
            self._autonomy.level = "expanded"
            # Lower confidence threshold (more aggressive)
            self._autonomy.min_confidence = max(
                self._settings.self_reg_min_confidence_floor,
                self._autonomy.min_confidence - 0.05,
            )
            # Lower sample requirement
            self._autonomy.min_samples = max(
                self._settings.self_reg_min_samples_floor,
                self._autonomy.min_samples - 5,
            )
            # Increase daily limit
            self._autonomy.max_auto_applies_per_day = min(
                20, self._autonomy.max_auto_applies_per_day + 5
            )
            # Allow prompt changes in auto tier
            self._autonomy.allowed_auto_types = ["routing", "threshold", "pattern", "prompt"]

        self._autonomy.last_adjusted = datetime.now(timezone.utc).isoformat()
        self._autonomy.reason = f"expanded from {previous} (success rate > {self.EXPAND_THRESHOLD:.0%})"

        logger.info(
            "autonomy_expanded",
            from_level=previous,
            to_level=self._autonomy.level,
            min_confidence=self._autonomy.min_confidence,
            min_samples=self._autonomy.min_samples,
        )

        return True

    def _restrict_autonomy(self) -> bool:
        """Tighten autonomy constraints (poor performance)."""
        if self._autonomy.level == "restricted":
            return False

        previous = self._autonomy.level

        if previous == "expanded":
            # Expanded -> Standard
            self._autonomy.level = "standard"
            self._autonomy.min_confidence = self._settings.auto_apply_min_confidence
            self._autonomy.min_samples = self._settings.auto_apply_min_samples
            self._autonomy.max_auto_applies_per_day = self._settings.max_auto_applies_per_day
            self._autonomy.allowed_auto_types = ["routing", "threshold", "pattern"]
        elif previous == "standard":
            # Standard -> Restricted
            self._autonomy.level = "restricted"
            # Raise confidence threshold (more conservative)
            self._autonomy.min_confidence = min(
                self._settings.self_reg_min_confidence_ceiling,
                self._autonomy.min_confidence + 0.10,
            )
            # Raise sample requirement
            self._autonomy.min_samples = min(
                self._settings.self_reg_min_samples_ceiling,
                self._autonomy.min_samples + 20,
            )
            # Decrease daily limit
            self._autonomy.max_auto_applies_per_day = max(
                2, self._autonomy.max_auto_applies_per_day - 5
            )
            # Only allow threshold changes in auto tier
            self._autonomy.allowed_auto_types = ["threshold"]

        self._autonomy.last_adjusted = datetime.now(timezone.utc).isoformat()
        self._autonomy.reason = f"restricted from {previous} (success rate < {self.RESTRICT_THRESHOLD:.0%})"

        logger.info(
            "autonomy_restricted",
            from_level=previous,
            to_level=self._autonomy.level,
            min_confidence=self._autonomy.min_confidence,
            min_samples=self._autonomy.min_samples,
        )

        return True

    async def _persist_autonomy_level(self) -> None:
        """Store current autonomy level in memory service."""
        if not self._memory_client:
            return

        payload = {
            "type": "observer_autonomy",
            "data": {
                "level": self._autonomy.level,
                "min_confidence": self._autonomy.min_confidence,
                "min_samples": self._autonomy.min_samples,
                "max_auto_applies_per_day": self._autonomy.max_auto_applies_per_day,
                "allowed_auto_types": self._autonomy.allowed_auto_types,
                "last_adjusted": self._autonomy.last_adjusted,
                "reason": self._autonomy.reason,
            },
        }

        try:
            response = await self._memory_client.post(
                "/patterns",
                json=payload,
            )
            if response.status_code not in (200, 201):
                logger.warning(
                    "autonomy_persist_failed",
                    status=response.status_code,
                )
        except httpx.HTTPError as exc:
            logger.warning("autonomy_persist_error", error=str(exc))

    async def _restore_autonomy_level(self) -> None:
        """Restore autonomy level from memory service on startup."""
        if not self._memory_client:
            return

        try:
            response = await self._memory_client.get(
                "/patterns",
                params={"type": "observer_autonomy", "limit": 1},
            )
            if response.status_code == 200:
                data = response.json()
                items = data if isinstance(data, list) else data.get("items", [])
                if items:
                    stored = items[0].get("data", {})
                    self._autonomy.level = stored.get("level", self._autonomy.level)
                    self._autonomy.min_confidence = stored.get(
                        "min_confidence", self._autonomy.min_confidence
                    )
                    self._autonomy.min_samples = stored.get(
                        "min_samples", self._autonomy.min_samples
                    )
                    self._autonomy.max_auto_applies_per_day = stored.get(
                        "max_auto_applies_per_day",
                        self._autonomy.max_auto_applies_per_day,
                    )
                    self._autonomy.allowed_auto_types = stored.get(
                        "allowed_auto_types",
                        self._autonomy.allowed_auto_types,
                    )
                    self._autonomy.last_adjusted = stored.get(
                        "last_adjusted", self._autonomy.last_adjusted
                    )
                    self._autonomy.reason = stored.get("reason", self._autonomy.reason)
                    logger.info(
                        "autonomy_level_restored",
                        level=self._autonomy.level,
                    )
        except httpx.HTTPError as exc:
            logger.warning("autonomy_restore_error", error=str(exc))

    def get_eval_history(self) -> list[dict[str, Any]]:
        """Get self-evaluation history for reporting."""
        return [
            {
                "eval_id": e.eval_id,
                "period_start": e.period_start,
                "period_end": e.period_end,
                "total_changes": e.total_changes,
                "success_rate": round(e.success_rate, 3),
                "previous_autonomy": e.previous_autonomy,
                "new_autonomy": e.new_autonomy,
                "adjustment_made": e.adjustment_made,
                "evaluated_at": e.evaluated_at,
            }
            for e in self._eval_history
        ]

    def get_status(self) -> dict[str, Any]:
        """Get current self-regulation status."""
        return {
            "autonomy_level": self._autonomy.level,
            "min_confidence": self._autonomy.min_confidence,
            "min_samples": self._autonomy.min_samples,
            "max_auto_applies_per_day": self._autonomy.max_auto_applies_per_day,
            "allowed_auto_types": self._autonomy.allowed_auto_types,
            "last_adjusted": self._autonomy.last_adjusted,
            "reason": self._autonomy.reason,
            "eval_history_count": len(self._eval_history),
            "change_history_count": len(self._change_history),
        }
