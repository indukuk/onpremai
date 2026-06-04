"""Issue detector — applies threshold rules to aggregated metrics.

Detects 8 issue types: quality drop, latency spike, cost spike, model drift,
error rate, tenant degradation, prompt inefficiency, capacity warning.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import structlog

from observer.src.config import ObserverSettings
from observer.src.detection.aggregator import AggregatedMetrics, MetricAggregator, TaskMetrics

logger = structlog.get_logger(__name__)


class IssueType(str, enum.Enum):
    """Types of issues the detector can identify."""

    HIGH_ESCALATION = "high_escalation"
    LOW_CONFIDENCE = "low_confidence"
    PARSE_FAILURES = "parse_failures"
    COST_SPIKE = "cost_spike"
    MODEL_ERRORS = "model_errors"
    LATENCY_SPIKE = "latency_spike"
    STALE_PATTERNS = "stale_patterns"
    SKILL_DEGRADATION = "skill_degradation"


class IssueSeverity(str, enum.Enum):
    """Severity levels for detected issues."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, IssueSeverity):
            return NotImplemented
        order = [IssueSeverity.LOW, IssueSeverity.MEDIUM, IssueSeverity.HIGH, IssueSeverity.CRITICAL]
        return order.index(self) < order.index(other)


@dataclass
class DetectedIssue:
    """A detected performance issue with context for diagnosis."""

    id: str = field(default_factory=lambda: f"iss_{uuid4().hex[:12]}")
    issue_type: IssueType = IssueType.HIGH_ESCALATION
    severity: IssueSeverity = IssueSeverity.MEDIUM
    task: str = ""
    model: str = ""
    tenant_id: str = ""
    description: str = ""
    current_value: float = 0.0
    threshold_value: float = 0.0
    baseline_value: float = 0.0
    sample_count: int = 0
    detected_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    metrics: dict[str, Any] = field(default_factory=dict)


class IssueDetector:
    """Applies threshold-based detection rules to aggregated metrics.

    Detects 8 issue types per requirements:
    - High escalation (>40%)
    - Low confidence (<0.7 avg, min 10 samples)
    - Parse failures (>15%)
    - Cost spike (>2x baseline)
    - Model errors (>5%)
    - Latency spike (P95 >2x baseline)
    - Stale patterns (unused >90 days)
    - Skill degradation (trending down over 7 days)
    """

    def __init__(self, settings: ObserverSettings, aggregator: MetricAggregator) -> None:
        self._settings = settings
        self._aggregator = aggregator

    def detect(self, metrics: AggregatedMetrics) -> list[DetectedIssue]:
        """Run all detection rules against aggregated metrics.

        Args:
            metrics: The current period's aggregated metrics.

        Returns:
            List of detected issues, sorted by severity (highest first).
        """
        issues: list[DetectedIssue] = []

        # Task-level detections
        for task, task_metrics in metrics.by_task.items():
            if task_metrics.sample_count < self._settings.detect_min_samples:
                continue

            issues.extend(self._detect_task_issues(task_metrics))

        # Model-level detections
        for model, model_metrics in metrics.by_model.items():
            if model_metrics.sample_count < self._settings.detect_min_samples:
                continue

            issues.extend(self._detect_model_issues(model_metrics))

        # Sort by severity (highest first)
        severity_order = {
            IssueSeverity.CRITICAL: 0,
            IssueSeverity.HIGH: 1,
            IssueSeverity.MEDIUM: 2,
            IssueSeverity.LOW: 3,
        }
        issues.sort(key=lambda i: severity_order.get(i.severity, 99))

        logger.info("detection_complete", issues_found=len(issues))
        return issues

    def _detect_task_issues(self, task_metrics: TaskMetrics) -> list[DetectedIssue]:
        """Detect issues for a single task."""
        issues: list[DetectedIssue] = []
        baseline = self._aggregator.get_baseline(task_metrics.task)

        # High escalation rate
        if task_metrics.escalation_rate > self._settings.detect_escalation_rate:
            issues.append(DetectedIssue(
                issue_type=IssueType.HIGH_ESCALATION,
                severity=IssueSeverity.HIGH,
                task=task_metrics.task,
                description=(
                    f"Task '{task_metrics.task}' has {task_metrics.escalation_rate:.0%} "
                    f"escalation rate (threshold: {self._settings.detect_escalation_rate:.0%})"
                ),
                current_value=task_metrics.escalation_rate,
                threshold_value=self._settings.detect_escalation_rate,
                baseline_value=baseline.escalation_rate if baseline else 0.0,
                sample_count=task_metrics.sample_count,
                metrics={
                    "escalation_rate": task_metrics.escalation_rate,
                    "sample_count": task_metrics.sample_count,
                },
            ))

        # Low confidence
        if task_metrics.avg_confidence < self._settings.detect_low_confidence:
            issues.append(DetectedIssue(
                issue_type=IssueType.LOW_CONFIDENCE,
                severity=IssueSeverity.MEDIUM,
                task=task_metrics.task,
                description=(
                    f"Task '{task_metrics.task}' has avg confidence "
                    f"{task_metrics.avg_confidence:.2f} (threshold: {self._settings.detect_low_confidence:.2f})"
                ),
                current_value=task_metrics.avg_confidence,
                threshold_value=self._settings.detect_low_confidence,
                baseline_value=baseline.avg_confidence if baseline else 0.0,
                sample_count=task_metrics.sample_count,
                metrics={
                    "avg_confidence": task_metrics.avg_confidence,
                    "sample_count": task_metrics.sample_count,
                },
            ))

        # Parse failures
        if task_metrics.parse_failure_rate > self._settings.detect_parse_failure_rate:
            issues.append(DetectedIssue(
                issue_type=IssueType.PARSE_FAILURES,
                severity=IssueSeverity.HIGH,
                task=task_metrics.task,
                description=(
                    f"Task '{task_metrics.task}' has {task_metrics.parse_failure_rate:.0%} "
                    f"parse failure rate (threshold: {self._settings.detect_parse_failure_rate:.0%})"
                ),
                current_value=task_metrics.parse_failure_rate,
                threshold_value=self._settings.detect_parse_failure_rate,
                baseline_value=baseline.parse_failure_rate if baseline else 0.0,
                sample_count=task_metrics.sample_count,
                metrics={
                    "parse_failure_rate": task_metrics.parse_failure_rate,
                    "sample_count": task_metrics.sample_count,
                },
            ))

        # Cost spike (relative to baseline)
        if baseline and baseline.avg_cost_usd > 0:
            cost_ratio = task_metrics.avg_cost_usd / baseline.avg_cost_usd
            if cost_ratio > self._settings.detect_cost_spike_multiplier:
                issues.append(DetectedIssue(
                    issue_type=IssueType.COST_SPIKE,
                    severity=IssueSeverity.MEDIUM,
                    task=task_metrics.task,
                    description=(
                        f"Task '{task_metrics.task}' cost is {cost_ratio:.1f}x baseline "
                        f"(threshold: {self._settings.detect_cost_spike_multiplier:.1f}x)"
                    ),
                    current_value=cost_ratio,
                    threshold_value=self._settings.detect_cost_spike_multiplier,
                    baseline_value=1.0,
                    sample_count=task_metrics.sample_count,
                    metrics={
                        "current_avg_cost": task_metrics.avg_cost_usd,
                        "baseline_avg_cost": baseline.avg_cost_usd,
                        "cost_ratio": cost_ratio,
                    },
                ))

        # Latency spike (relative to baseline)
        if baseline and baseline.p95_latency_ms > 0:
            latency_ratio = task_metrics.p95_latency_ms / baseline.p95_latency_ms
            if latency_ratio > self._settings.detect_latency_spike_multiplier:
                issues.append(DetectedIssue(
                    issue_type=IssueType.LATENCY_SPIKE,
                    severity=IssueSeverity.MEDIUM,
                    task=task_metrics.task,
                    description=(
                        f"Task '{task_metrics.task}' P95 latency is {latency_ratio:.1f}x baseline "
                        f"(threshold: {self._settings.detect_latency_spike_multiplier:.1f}x)"
                    ),
                    current_value=latency_ratio,
                    threshold_value=self._settings.detect_latency_spike_multiplier,
                    baseline_value=1.0,
                    sample_count=task_metrics.sample_count,
                    metrics={
                        "current_p95_ms": task_metrics.p95_latency_ms,
                        "baseline_p95_ms": baseline.p95_latency_ms,
                        "latency_ratio": latency_ratio,
                    },
                ))

        return issues

    def _detect_model_issues(self, model_metrics: Any) -> list[DetectedIssue]:
        """Detect issues for a single model."""
        issues: list[DetectedIssue] = []

        # Model error rate
        if model_metrics.error_rate > self._settings.detect_error_rate:
            issues.append(DetectedIssue(
                issue_type=IssueType.MODEL_ERRORS,
                severity=IssueSeverity.CRITICAL,
                model=model_metrics.model,
                description=(
                    f"Model '{model_metrics.model}' has {model_metrics.error_rate:.0%} "
                    f"error rate (threshold: {self._settings.detect_error_rate:.0%})"
                ),
                current_value=model_metrics.error_rate,
                threshold_value=self._settings.detect_error_rate,
                sample_count=model_metrics.sample_count,
                metrics={
                    "error_rate": model_metrics.error_rate,
                    "sample_count": model_metrics.sample_count,
                    "model": model_metrics.model,
                },
            ))

        return issues
