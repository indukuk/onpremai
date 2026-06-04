"""Change proposal — generates concrete Change objects from diagnoses.

Turns a Diagnosis into an actionable config change with tier classification.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import structlog

from observer.src.config import ObserverSettings
from observer.src.detection.detector import DetectedIssue
from observer.src.diagnosis.engine import Diagnosis

logger = structlog.get_logger(__name__)


class ChangeType(str, enum.Enum):
    """Types of changes the observer can propose."""

    ROUTING = "routing"
    PROMPT = "prompt"
    THRESHOLD = "threshold"
    MODEL = "model"
    PATTERN = "pattern"


class ChangeStatus(str, enum.Enum):
    """Status of a proposed change."""

    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"
    APPLIED = "applied"
    CANARY_RUNNING = "canary_running"
    CANARY_PASSED = "canary_passed"
    CANARY_FAILED = "canary_failed"
    VALIDATED = "validated"
    ROLLED_BACK = "rolled_back"
    QUEUED = "queued"


class ApplyTier(str, enum.Enum):
    """Autonomy tiers for applying changes."""

    AUTO = "auto"          # Tier 1: auto-apply, no human needed
    CANARY = "canary"      # Tier 2: test first, then roll out
    HUMAN = "human"        # Tier 3: require human approval


@dataclass
class Change:
    """A concrete, actionable configuration change."""

    id: str = field(default_factory=lambda: f"chg_{uuid4().hex[:12]}")
    change_type: ChangeType = ChangeType.ROUTING
    apply_tier: ApplyTier = ApplyTier.AUTO
    status: ChangeStatus = ChangeStatus.PROPOSED
    task: str = ""
    model: str = ""
    description: str = ""
    config_diff: dict[str, Any] = field(default_factory=dict)
    previous_value: Any = None
    new_value: Any = None
    confidence: float = 0.0
    sample_count: int = 0
    diagnosis_id: str = ""
    issue_id: str = ""
    snapshot: dict[str, Any] = field(default_factory=dict)
    proposed_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    applied_at: str | None = None
    validated_at: str | None = None
    rolled_back_at: str | None = None
    metrics_before: dict[str, Any] = field(default_factory=dict)
    metrics_after: dict[str, Any] = field(default_factory=dict)


# Mapping of fix_type to change_type
FIX_TYPE_TO_CHANGE: dict[str, ChangeType] = {
    "routing": ChangeType.ROUTING,
    "prompt": ChangeType.PROMPT,
    "threshold": ChangeType.THRESHOLD,
    "model": ChangeType.MODEL,
    "pattern": ChangeType.PATTERN,
}

# Default tier classification by change type
DEFAULT_TIERS: dict[ChangeType, ApplyTier] = {
    ChangeType.ROUTING: ApplyTier.AUTO,
    ChangeType.THRESHOLD: ApplyTier.AUTO,
    ChangeType.PATTERN: ApplyTier.AUTO,
    ChangeType.PROMPT: ApplyTier.CANARY,
    ChangeType.MODEL: ApplyTier.CANARY,
}


class ChangeProposer:
    """Generates concrete Change objects from Diagnosis results.

    Applies tier classification logic based on change type,
    confidence levels, historical failures, and policy settings.
    """

    def __init__(self, settings: ObserverSettings) -> None:
        self._settings = settings
        self._failed_types: set[str] = set()
        self._daily_auto_count: int = 0
        self._daily_reset_date: str = ""
        self._active_canaries: int = 0

    def propose(
        self,
        diagnosis: Diagnosis,
        issue: DetectedIssue,
    ) -> Change | None:
        """Generate a Change from a Diagnosis.

        Args:
            diagnosis: The LLM diagnosis result.
            issue: The original detected issue.

        Returns:
            A Change object, or None if confidence too low to act.
        """
        # Minimum confidence to act at all
        if diagnosis.confidence < 0.6:
            logger.info(
                "diagnosis_confidence_too_low",
                diagnosis_id=diagnosis.id,
                confidence=diagnosis.confidence,
            )
            return None

        change_type = FIX_TYPE_TO_CHANGE.get(diagnosis.fix_type)
        if change_type is None:
            logger.warning(
                "unknown_fix_type",
                diagnosis_id=diagnosis.id,
                fix_type=diagnosis.fix_type,
            )
            return None

        # Determine tier
        apply_tier = self._classify_tier(change_type, diagnosis.confidence, issue.sample_count)

        # Build config diff based on change type
        config_diff = self._build_config_diff(change_type, diagnosis, issue)

        change = Change(
            change_type=change_type,
            apply_tier=apply_tier,
            task=issue.task,
            model=issue.model,
            description=diagnosis.fix_description,
            config_diff=config_diff,
            confidence=diagnosis.confidence,
            sample_count=issue.sample_count,
            diagnosis_id=diagnosis.id,
            issue_id=issue.id,
        )

        logger.info(
            "change_proposed",
            change_id=change.id,
            change_type=change_type.value,
            apply_tier=apply_tier.value,
            confidence=diagnosis.confidence,
            task=issue.task,
        )

        return change

    def _classify_tier(
        self,
        change_type: ChangeType,
        confidence: float,
        sample_count: int,
    ) -> ApplyTier:
        """Classify the autonomy tier for a change.

        Applies decision tree from DESIGN.md:
        - Check if circuit breaker is tripped (handled externally)
        - Check if same change type failed before
        - Check confidence and sample thresholds
        - Check daily auto-apply limit
        """
        # Check if this change type has failed before -> force HUMAN
        type_key = change_type.value
        if type_key in self._failed_types:
            return ApplyTier.HUMAN

        default_tier = DEFAULT_TIERS.get(change_type, ApplyTier.HUMAN)

        if default_tier == ApplyTier.AUTO:
            # Check auto-apply requirements
            if confidence < self._settings.auto_apply_min_confidence:
                return ApplyTier.CANARY
            if sample_count < self._settings.auto_apply_min_samples:
                return ApplyTier.CANARY
            if self._daily_auto_count >= self._settings.max_auto_applies_per_day:
                return ApplyTier.CANARY
            return ApplyTier.AUTO

        elif default_tier == ApplyTier.CANARY:
            # Check canary requirements
            if confidence < 0.70:
                return ApplyTier.HUMAN
            if self._active_canaries >= self._settings.max_concurrent_canaries:
                return ApplyTier.HUMAN  # Will be queued
            return ApplyTier.CANARY

        return ApplyTier.HUMAN

    def _build_config_diff(
        self,
        change_type: ChangeType,
        diagnosis: Diagnosis,
        issue: DetectedIssue,
    ) -> dict[str, Any]:
        """Build the configuration diff for a change."""
        if change_type == ChangeType.ROUTING:
            # Determine new tier based on issue type
            new_tier = "strong" if issue.current_value > 0.5 else "mid"
            return {
                "task_routing": {issue.task: new_tier},
                "reason": diagnosis.root_cause,
            }

        elif change_type == ChangeType.THRESHOLD:
            # Adjust threshold based on diagnosis
            current_threshold = issue.threshold_value
            adjustment = 0.05 if diagnosis.confidence > 0.85 else 0.03
            new_threshold = min(0.95, current_threshold + adjustment)
            return {
                "task": issue.task,
                "threshold": new_threshold,
                "previous_threshold": current_threshold,
            }

        elif change_type == ChangeType.PROMPT:
            return {
                "task": issue.task,
                "action": "rewrite",
                "reason": diagnosis.root_cause,
                "fix_description": diagnosis.fix_description,
            }

        elif change_type == ChangeType.MODEL:
            return {
                "task": issue.task or "",
                "model": issue.model or "",
                "action": "swap" if issue.model else "add",
                "reason": diagnosis.root_cause,
            }

        elif change_type == ChangeType.PATTERN:
            return {
                "task": issue.task,
                "action": "record",
                "pattern_description": diagnosis.fix_description,
            }

        return {}

    def record_failure(self, change_type: str) -> None:
        """Record that a change type has failed (canary or rollback).

        This prevents future auto-applies of the same type.
        """
        self._failed_types.add(change_type)
        logger.info("change_type_marked_failed", change_type=change_type)

    def increment_daily_auto_count(self) -> None:
        """Track daily auto-apply count."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self._daily_reset_date != today:
            self._daily_auto_count = 0
            self._daily_reset_date = today
        self._daily_auto_count += 1

    def set_active_canaries(self, count: int) -> None:
        """Update the active canary count."""
        self._active_canaries = count
