"""Bias detection — cross-tenant variance monitoring.

Compares model performance metrics across tenants to detect unfair
variance that could indicate model bias or misconfigured routing.
A tenant receiving significantly worse performance than peers may
indicate systemic issues.
"""

from __future__ import annotations

import statistics as stats_mod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import structlog

from observer.src.config import ObserverSettings
from observer.src.detection.aggregator import TenantMetrics

logger = structlog.get_logger(__name__)


@dataclass
class TenantBiasResult:
    """Bias analysis result for a single tenant."""

    tenant_id: str
    metric_name: str
    tenant_value: float = 0.0
    population_mean: float = 0.0
    population_std: float = 0.0
    z_score: float = 0.0
    variance_ratio: float = 0.0
    is_outlier: bool = False
    direction: str = ""  # "underperforming" or "overperforming"


@dataclass
class BiasReport:
    """Cross-tenant bias analysis report."""

    results: list[TenantBiasResult] = field(default_factory=list)
    total_tenants_analyzed: int = 0
    outlier_count: int = 0
    metrics_analyzed: list[str] = field(default_factory=list)
    variance_threshold: float = 0.15
    generated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class BiasDetector:
    """Detects cross-tenant performance variance that indicates bias.

    For each tracked metric (confidence, escalation rate, cost), computes
    the cross-tenant distribution and flags tenants whose performance
    deviates beyond the configured threshold.

    A high variance ratio means one tenant is getting systematically
    worse service than others, which could indicate:
    - Routing misconfiguration for that tenant
    - Model performance degradation on that tenant's data
    - Resource starvation under budget constraints
    """

    MONITORED_METRICS: list[str] = [
        "avg_confidence",
        "escalation_rate",
        "avg_cost_usd",
    ]

    def __init__(self, settings: ObserverSettings) -> None:
        self._settings = settings
        self._last_report: BiasReport | None = None

    def analyze(self, tenant_metrics: dict[str, TenantMetrics]) -> BiasReport:
        """Analyze cross-tenant variance for bias indicators.

        Args:
            tenant_metrics: Mapping of tenant_id to their aggregated metrics.

        Returns:
            BiasReport with outlier tenants identified.
        """
        if len(tenant_metrics) < 3:
            logger.info(
                "bias_check_skipped_insufficient_tenants",
                tenant_count=len(tenant_metrics),
            )
            return BiasReport(
                total_tenants_analyzed=len(tenant_metrics),
                metrics_analyzed=self.MONITORED_METRICS,
                variance_threshold=self._settings.bias_variance_threshold,
            )

        results: list[TenantBiasResult] = []

        for metric_name in self.MONITORED_METRICS:
            metric_results = self._analyze_metric(metric_name, tenant_metrics)
            results.extend(metric_results)

        outlier_count = sum(1 for r in results if r.is_outlier)

        report = BiasReport(
            results=results,
            total_tenants_analyzed=len(tenant_metrics),
            outlier_count=outlier_count,
            metrics_analyzed=list(self.MONITORED_METRICS),
            variance_threshold=self._settings.bias_variance_threshold,
        )

        self._last_report = report

        if outlier_count > 0:
            logger.warning(
                "bias_outliers_detected",
                outlier_count=outlier_count,
                total_tenants=len(tenant_metrics),
            )
        else:
            logger.info(
                "bias_check_clean",
                total_tenants=len(tenant_metrics),
                metrics_checked=len(self.MONITORED_METRICS),
            )

        return report

    def _analyze_metric(
        self,
        metric_name: str,
        tenant_metrics: dict[str, TenantMetrics],
    ) -> list[TenantBiasResult]:
        """Analyze a single metric across all tenants for variance."""
        results: list[TenantBiasResult] = []

        # Extract values for the metric from all tenants
        values: dict[str, float] = {}
        for tenant_id, metrics in tenant_metrics.items():
            value = getattr(metrics, metric_name, None)
            if value is not None and metrics.sample_count >= self._settings.detect_min_samples:
                values[tenant_id] = float(value)

        if len(values) < 3:
            return results

        # Compute population statistics
        all_values = list(values.values())
        pop_mean = stats_mod.mean(all_values)
        pop_std = stats_mod.stdev(all_values) if len(all_values) > 1 else 0.0

        # Check each tenant against the population
        threshold = self._settings.bias_variance_threshold

        for tenant_id, tenant_value in values.items():
            # Compute z-score if std > 0
            if pop_std > 0:
                z_score = (tenant_value - pop_mean) / pop_std
            else:
                z_score = 0.0

            # Compute variance ratio (how far from mean as fraction)
            if pop_mean > 0:
                variance_ratio = abs(tenant_value - pop_mean) / pop_mean
            else:
                variance_ratio = 0.0

            is_outlier = variance_ratio > threshold

            # Determine direction based on metric semantics
            direction = ""
            if is_outlier:
                if metric_name == "avg_confidence":
                    direction = "underperforming" if tenant_value < pop_mean else "overperforming"
                elif metric_name == "escalation_rate":
                    direction = "underperforming" if tenant_value > pop_mean else "overperforming"
                elif metric_name == "avg_cost_usd":
                    direction = "underperforming" if tenant_value > pop_mean else "overperforming"

            result = TenantBiasResult(
                tenant_id=tenant_id,
                metric_name=metric_name,
                tenant_value=tenant_value,
                population_mean=pop_mean,
                population_std=pop_std,
                z_score=z_score,
                variance_ratio=variance_ratio,
                is_outlier=is_outlier,
                direction=direction,
            )
            results.append(result)

        return results

    @property
    def last_report(self) -> BiasReport | None:
        """Get the most recent bias report."""
        return self._last_report

    def get_outlier_tenants(self) -> list[TenantBiasResult]:
        """Get tenants flagged as outliers from the last analysis."""
        if not self._last_report:
            return []
        return [r for r in self._last_report.results if r.is_outlier]

    def get_underperforming_tenants(self) -> list[TenantBiasResult]:
        """Get tenants that are underperforming relative to peers."""
        if not self._last_report:
            return []
        return [
            r for r in self._last_report.results
            if r.is_outlier and r.direction == "underperforming"
        ]

    def to_dict(self) -> dict[str, Any]:
        """Serialize the last report for storage or API response."""
        if not self._last_report:
            return {"status": "no_report", "results": []}

        report = self._last_report
        return {
            "generated_at": report.generated_at,
            "total_tenants_analyzed": report.total_tenants_analyzed,
            "outlier_count": report.outlier_count,
            "metrics_analyzed": report.metrics_analyzed,
            "variance_threshold": report.variance_threshold,
            "results": [
                {
                    "tenant_id": r.tenant_id,
                    "metric_name": r.metric_name,
                    "tenant_value": round(r.tenant_value, 4),
                    "population_mean": round(r.population_mean, 4),
                    "population_std": round(r.population_std, 4),
                    "z_score": round(r.z_score, 2),
                    "variance_ratio": round(r.variance_ratio, 4),
                    "is_outlier": r.is_outlier,
                    "direction": r.direction,
                }
                for r in report.results
            ],
        }
