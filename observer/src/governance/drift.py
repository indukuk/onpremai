"""Drift detection — Kolmogorov-Smirnov test on confidence distributions.

Detects statistical drift in model behavior by comparing recent confidence
distributions against a baseline window. Uses scipy.stats.ks_2samp for
non-parametric two-sample comparison.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import structlog
from scipy.stats import ks_2samp

from observer.src.config import ObserverSettings
from observer.src.detection.log_ingestor import LogEntry

logger = structlog.get_logger(__name__)


@dataclass
class DriftResult:
    """Result of a drift detection test for a single model/task."""

    entity_type: str  # "model" or "task"
    entity_id: str
    ks_statistic: float = 0.0
    p_value: float = 1.0
    drift_detected: bool = False
    baseline_sample_count: int = 0
    current_sample_count: int = 0
    baseline_mean: float = 0.0
    current_mean: float = 0.0
    baseline_std: float = 0.0
    current_std: float = 0.0
    detected_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass
class DriftReport:
    """Aggregated drift detection report across all models and tasks."""

    results: list[DriftResult] = field(default_factory=list)
    total_entities_checked: int = 0
    drifted_entities: int = 0
    threshold_p_value: float = 0.05
    generated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class DriftDetector:
    """Detects statistical drift in confidence distributions.

    Compares a recent window of confidence scores against a baseline
    window using the two-sample Kolmogorov-Smirnov test. If p-value
    falls below threshold, drift is flagged.

    This is a non-parametric test that detects any change in the
    distribution shape, not just mean shifts.
    """

    def __init__(self, settings: ObserverSettings) -> None:
        self._settings = settings
        self._baseline_data: dict[str, list[float]] = {}
        self._current_data: dict[str, list[float]] = {}
        self._last_report: DriftReport | None = None

    def ingest_baseline(self, entries: list[LogEntry]) -> None:
        """Ingest log entries into the baseline distribution.

        Call this with historical data representing the known-good period.

        Args:
            entries: Log entries from the baseline window.
        """
        self._baseline_data.clear()

        for entry in entries:
            if entry.confidence <= 0:
                continue

            # Group by model
            model_key = f"model:{entry.model_used}"
            self._baseline_data.setdefault(model_key, []).append(entry.confidence)

            # Group by task
            task_key = f"task:{entry.task}"
            self._baseline_data.setdefault(task_key, []).append(entry.confidence)

        logger.info(
            "drift_baseline_ingested",
            entities=len(self._baseline_data),
            total_samples=sum(len(v) for v in self._baseline_data.values()),
        )

    def ingest_current(self, entries: list[LogEntry]) -> None:
        """Ingest log entries into the current window distribution.

        Call this with recent data to compare against baseline.

        Args:
            entries: Log entries from the current evaluation window.
        """
        self._current_data.clear()

        for entry in entries:
            if entry.confidence <= 0:
                continue

            model_key = f"model:{entry.model_used}"
            self._current_data.setdefault(model_key, []).append(entry.confidence)

            task_key = f"task:{entry.task}"
            self._current_data.setdefault(task_key, []).append(entry.confidence)

        logger.info(
            "drift_current_ingested",
            entities=len(self._current_data),
            total_samples=sum(len(v) for v in self._current_data.values()),
        )

    def detect(self) -> DriftReport:
        """Run KS test across all entities with both baseline and current data.

        Returns:
            DriftReport with results for each entity tested.
        """
        results: list[DriftResult] = []
        threshold = self._settings.drift_threshold_ks_pvalue

        # Find entities present in both windows
        all_keys = set(self._baseline_data.keys()) & set(self._current_data.keys())

        for key in sorted(all_keys):
            baseline_samples = self._baseline_data[key]
            current_samples = self._current_data[key]

            # Need minimum samples for meaningful test
            min_samples = self._settings.detect_min_samples
            if len(baseline_samples) < min_samples or len(current_samples) < min_samples:
                continue

            result = self._run_ks_test(key, baseline_samples, current_samples, threshold)
            results.append(result)

        drifted_count = sum(1 for r in results if r.drift_detected)

        report = DriftReport(
            results=results,
            total_entities_checked=len(results),
            drifted_entities=drifted_count,
            threshold_p_value=threshold,
        )

        self._last_report = report

        logger.info(
            "drift_detection_complete",
            entities_checked=len(results),
            drifted=drifted_count,
            threshold=threshold,
        )

        return report

    def _run_ks_test(
        self,
        key: str,
        baseline: list[float],
        current: list[float],
        threshold: float,
    ) -> DriftResult:
        """Run KS test for a single entity."""
        # Parse entity type and ID from key
        parts = key.split(":", 1)
        entity_type = parts[0] if len(parts) > 1 else "unknown"
        entity_id = parts[1] if len(parts) > 1 else key

        # Compute statistics
        import statistics as stats_mod

        baseline_mean = stats_mod.mean(baseline)
        current_mean = stats_mod.mean(current)
        baseline_std = stats_mod.stdev(baseline) if len(baseline) > 1 else 0.0
        current_std = stats_mod.stdev(current) if len(current) > 1 else 0.0

        # Run two-sample KS test
        ks_stat, p_value = ks_2samp(baseline, current)

        drift_detected = p_value < threshold

        if drift_detected:
            logger.warning(
                "drift_detected",
                entity_type=entity_type,
                entity_id=entity_id,
                ks_statistic=round(ks_stat, 4),
                p_value=round(p_value, 6),
                baseline_mean=round(baseline_mean, 4),
                current_mean=round(current_mean, 4),
            )

        return DriftResult(
            entity_type=entity_type,
            entity_id=entity_id,
            ks_statistic=float(ks_stat),
            p_value=float(p_value),
            drift_detected=drift_detected,
            baseline_sample_count=len(baseline),
            current_sample_count=len(current),
            baseline_mean=baseline_mean,
            current_mean=current_mean,
            baseline_std=baseline_std,
            current_std=current_std,
        )

    @property
    def last_report(self) -> DriftReport | None:
        """Get the most recent drift report."""
        return self._last_report

    def get_drifted_entities(self) -> list[DriftResult]:
        """Get list of entities with detected drift from the last run."""
        if not self._last_report:
            return []
        return [r for r in self._last_report.results if r.drift_detected]

    def to_dict(self) -> dict[str, Any]:
        """Serialize the last report for storage or API response."""
        if not self._last_report:
            return {"status": "no_report", "results": []}

        report = self._last_report
        return {
            "generated_at": report.generated_at,
            "total_entities_checked": report.total_entities_checked,
            "drifted_entities": report.drifted_entities,
            "threshold_p_value": report.threshold_p_value,
            "results": [
                {
                    "entity_type": r.entity_type,
                    "entity_id": r.entity_id,
                    "ks_statistic": round(r.ks_statistic, 4),
                    "p_value": round(r.p_value, 6),
                    "drift_detected": r.drift_detected,
                    "baseline_samples": r.baseline_sample_count,
                    "current_samples": r.current_sample_count,
                    "baseline_mean": round(r.baseline_mean, 4),
                    "current_mean": round(r.current_mean, 4),
                }
                for r in report.results
            ],
        }
