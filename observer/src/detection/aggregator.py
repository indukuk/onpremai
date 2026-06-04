"""Metric aggregator — computes per-task, per-model, per-tenant metrics.

Aggregates raw log entries into time-windowed metric buckets for
issue detection and trend analysis.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any

import structlog

from observer.src.detection.log_ingestor import LogEntry

logger = structlog.get_logger(__name__)


@dataclass
class TaskMetrics:
    """Aggregated metrics for a single task."""

    task: str
    sample_count: int = 0
    avg_confidence: float = 0.0
    escalation_rate: float = 0.0
    failure_rate: float = 0.0
    parse_failure_rate: float = 0.0
    avg_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    avg_cost_usd: float = 0.0
    total_cost_usd: float = 0.0
    error_rate: float = 0.0


@dataclass
class ModelMetrics:
    """Aggregated metrics for a single model."""

    model: str
    sample_count: int = 0
    error_rate: float = 0.0
    avg_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    avg_cost_usd: float = 0.0
    total_cost_usd: float = 0.0
    availability: float = 1.0


@dataclass
class TenantMetrics:
    """Aggregated metrics for a single tenant."""

    tenant_id: str
    sample_count: int = 0
    total_cost_usd: float = 0.0
    avg_cost_usd: float = 0.0
    escalation_rate: float = 0.0
    avg_confidence: float = 0.0


@dataclass
class AggregatedMetrics:
    """Container for all aggregated metrics from a time window."""

    by_task: dict[str, TaskMetrics] = field(default_factory=dict)
    by_model: dict[str, ModelMetrics] = field(default_factory=dict)
    by_tenant: dict[str, TenantMetrics] = field(default_factory=dict)
    total_entries: int = 0
    window_minutes: int = 60


class MetricAggregator:
    """Computes aggregated metrics from raw log entries.

    Supports aggregation by task, model, and tenant dimensions.
    Computes percentiles, rates, and averages for issue detection.
    """

    def __init__(self) -> None:
        self._baseline: dict[str, TaskMetrics] = {}

    def aggregate(self, entries: list[LogEntry], window_minutes: int = 60) -> AggregatedMetrics:
        """Aggregate log entries into metrics by task, model, and tenant.

        Args:
            entries: Raw log entries to aggregate.
            window_minutes: The time window these entries cover.

        Returns:
            AggregatedMetrics with per-task, per-model, per-tenant breakdowns.
        """
        result = AggregatedMetrics(total_entries=len(entries), window_minutes=window_minutes)

        if not entries:
            return result

        # Group entries by dimensions
        by_task: dict[str, list[LogEntry]] = {}
        by_model: dict[str, list[LogEntry]] = {}
        by_tenant: dict[str, list[LogEntry]] = {}

        for entry in entries:
            by_task.setdefault(entry.task, []).append(entry)
            by_model.setdefault(entry.model_used, []).append(entry)
            by_tenant.setdefault(entry.tenant_id, []).append(entry)

        # Compute task metrics
        for task, task_entries in by_task.items():
            result.by_task[task] = self._compute_task_metrics(task, task_entries)

        # Compute model metrics
        for model, model_entries in by_model.items():
            result.by_model[model] = self._compute_model_metrics(model, model_entries)

        # Compute tenant metrics
        for tenant, tenant_entries in by_tenant.items():
            result.by_tenant[tenant] = self._compute_tenant_metrics(tenant, tenant_entries)

        logger.info(
            "metrics_aggregated",
            total_entries=len(entries),
            tasks=len(result.by_task),
            models=len(result.by_model),
            tenants=len(result.by_tenant),
        )

        return result

    def update_baseline(self, metrics: AggregatedMetrics) -> None:
        """Update baseline metrics for trend comparison.

        Called periodically to establish what 'normal' looks like.
        """
        self._baseline = dict(metrics.by_task)

    def get_baseline(self, task: str) -> TaskMetrics | None:
        """Get baseline metrics for a task."""
        return self._baseline.get(task)

    def _compute_task_metrics(self, task: str, entries: list[LogEntry]) -> TaskMetrics:
        """Compute aggregated metrics for a task."""
        count = len(entries)
        confidences = [e.confidence for e in entries if e.confidence > 0]
        latencies = [e.latency_ms for e in entries]
        costs = [e.cost_usd for e in entries]
        escalated_count = sum(1 for e in entries if e.escalated)
        failed_count = sum(1 for e in entries if not e.success)
        parse_failed_count = sum(1 for e in entries if not e.parse_success)
        error_count = sum(1 for e in entries if e.error)

        return TaskMetrics(
            task=task,
            sample_count=count,
            avg_confidence=statistics.mean(confidences) if confidences else 0.0,
            escalation_rate=escalated_count / count if count > 0 else 0.0,
            failure_rate=failed_count / count if count > 0 else 0.0,
            parse_failure_rate=parse_failed_count / count if count > 0 else 0.0,
            avg_latency_ms=statistics.mean(latencies) if latencies else 0.0,
            p95_latency_ms=self._percentile(latencies, 0.95),
            avg_cost_usd=statistics.mean(costs) if costs else 0.0,
            total_cost_usd=sum(costs),
            error_rate=error_count / count if count > 0 else 0.0,
        )

    def _compute_model_metrics(self, model: str, entries: list[LogEntry]) -> ModelMetrics:
        """Compute aggregated metrics for a model."""
        count = len(entries)
        latencies = [e.latency_ms for e in entries]
        costs = [e.cost_usd for e in entries]
        error_count = sum(1 for e in entries if e.error)
        success_count = sum(1 for e in entries if e.success)

        return ModelMetrics(
            model=model,
            sample_count=count,
            error_rate=error_count / count if count > 0 else 0.0,
            avg_latency_ms=statistics.mean(latencies) if latencies else 0.0,
            p95_latency_ms=self._percentile(latencies, 0.95),
            avg_cost_usd=statistics.mean(costs) if costs else 0.0,
            total_cost_usd=sum(costs),
            availability=success_count / count if count > 0 else 1.0,
        )

    def _compute_tenant_metrics(self, tenant_id: str, entries: list[LogEntry]) -> TenantMetrics:
        """Compute aggregated metrics for a tenant."""
        count = len(entries)
        costs = [e.cost_usd for e in entries]
        escalated_count = sum(1 for e in entries if e.escalated)
        confidences = [e.confidence for e in entries if e.confidence > 0]

        return TenantMetrics(
            tenant_id=tenant_id,
            sample_count=count,
            total_cost_usd=sum(costs),
            avg_cost_usd=statistics.mean(costs) if costs else 0.0,
            escalation_rate=escalated_count / count if count > 0 else 0.0,
            avg_confidence=statistics.mean(confidences) if confidences else 0.0,
        )

    @staticmethod
    def _percentile(values: list[int | float], pct: float) -> float:
        """Compute a percentile value from a list."""
        if not values:
            return 0.0
        sorted_values = sorted(values)
        idx = int(len(sorted_values) * pct)
        idx = min(idx, len(sorted_values) - 1)
        return float(sorted_values[idx])

    def compute_trend(
        self,
        current: TaskMetrics,
        baseline: TaskMetrics | None,
    ) -> dict[str, float]:
        """Compute trend deltas between current and baseline metrics.

        Returns:
            Dict of metric names to delta values (positive = worse).
        """
        if baseline is None or baseline.sample_count == 0:
            return {}

        trends: dict[str, float] = {}

        if baseline.avg_confidence > 0:
            trends["confidence_delta"] = current.avg_confidence - baseline.avg_confidence

        trends["escalation_delta"] = current.escalation_rate - baseline.escalation_rate
        trends["failure_delta"] = current.failure_rate - baseline.failure_rate

        if baseline.p95_latency_ms > 0:
            trends["latency_ratio"] = current.p95_latency_ms / baseline.p95_latency_ms

        if baseline.avg_cost_usd > 0:
            trends["cost_ratio"] = current.avg_cost_usd / baseline.avg_cost_usd

        return trends
