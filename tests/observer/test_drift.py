"""Unit tests for observer drift detection.

Tests KS test detects drift on different distributions and no drift on same distribution.
"""

from __future__ import annotations

import random

import pytest

from observer.src.config import ObserverSettings
from observer.src.detection.log_ingestor import LogEntry
from observer.src.governance.drift import DriftDetector, DriftReport, DriftResult


def _make_log_entries(
    confidence_values: list[float],
    model: str = "claude-3-sonnet",
    task: str = "evaluate_control",
) -> list[LogEntry]:
    """Helper to create log entries with specific confidence values."""
    entries = []
    for i, conf in enumerate(confidence_values):
        entries.append(LogEntry(
            timestamp=f"2024-01-01T12:{i:02d}:00Z",
            trace_id=f"trace_{i:04d}",
            agent="agent-eval",
            task=task,
            tier_requested="mid",
            tier_used="mid",
            model_used=model,
            escalated=False,
            input_tokens=1000,
            output_tokens=500,
            latency_ms=1200,
            confidence=conf,
            success=True,
            error=None,
            tenant_id="tenant_001",
            tool_calls_count=0,
            parse_success=True,
            cost_usd=0.005,
        ))
    return entries


class TestDriftDetection:
    """Tests for KS-test-based drift detection."""

    def test_detects_drift_different_distributions(self, settings: ObserverSettings) -> None:
        """Clearly different distributions should be detected as drift."""
        detector = DriftDetector(settings)

        # Baseline: high confidence (0.80-0.95)
        random.seed(42)
        baseline_values = [random.uniform(0.80, 0.95) for _ in range(50)]
        baseline_entries = _make_log_entries(baseline_values)

        # Current: low confidence (0.40-0.60) - clearly different
        current_values = [random.uniform(0.40, 0.60) for _ in range(50)]
        current_entries = _make_log_entries(current_values)

        detector.ingest_baseline(baseline_entries)
        detector.ingest_current(current_entries)

        report = detector.detect()

        assert report.drifted_entities > 0
        # Check that at least one result shows drift
        drifted = [r for r in report.results if r.drift_detected]
        assert len(drifted) > 0
        # p-value should be very small for clearly different distributions
        for result in drifted:
            assert result.p_value < 0.05

    def test_no_drift_same_distribution(self, settings: ObserverSettings) -> None:
        """Samples from the same distribution should NOT detect drift."""
        detector = DriftDetector(settings)

        # Both baseline and current from same distribution (0.75-0.90)
        random.seed(123)
        baseline_values = [random.uniform(0.75, 0.90) for _ in range(50)]
        baseline_entries = _make_log_entries(baseline_values)

        random.seed(456)
        current_values = [random.uniform(0.75, 0.90) for _ in range(50)]
        current_entries = _make_log_entries(current_values)

        detector.ingest_baseline(baseline_entries)
        detector.ingest_current(current_entries)

        report = detector.detect()

        # No entity should show drift when distributions are the same
        assert report.drifted_entities == 0
        for result in report.results:
            assert not result.drift_detected
            assert result.p_value >= 0.05

    def test_drift_detected_per_model(self, settings: ObserverSettings) -> None:
        """Drift should be detected independently per model."""
        detector = DriftDetector(settings)

        random.seed(42)
        # Model A: stable (same distribution)
        baseline_a = _make_log_entries(
            [random.uniform(0.80, 0.90) for _ in range(30)],
            model="model-a",
        )
        current_a = _make_log_entries(
            [random.uniform(0.80, 0.90) for _ in range(30)],
            model="model-a",
        )

        # Model B: drifted (clearly different)
        baseline_b = _make_log_entries(
            [random.uniform(0.80, 0.90) for _ in range(30)],
            model="model-b",
        )
        current_b = _make_log_entries(
            [random.uniform(0.30, 0.50) for _ in range(30)],
            model="model-b",
        )

        detector.ingest_baseline(baseline_a + baseline_b)
        detector.ingest_current(current_a + current_b)

        report = detector.detect()

        # Model B should have drift, Model A should not
        results_by_entity = {r.entity_id: r for r in report.results if r.entity_type == "model"}
        assert "model-b" in results_by_entity
        assert results_by_entity["model-b"].drift_detected is True

    def test_drift_detected_per_task(self, settings: ObserverSettings) -> None:
        """Drift should be detected independently per task."""
        detector = DriftDetector(settings)

        random.seed(42)
        # Task A: stable
        baseline_task_a = _make_log_entries(
            [random.uniform(0.80, 0.90) for _ in range(30)],
            task="stable_task",
        )
        current_task_a = _make_log_entries(
            [random.uniform(0.80, 0.90) for _ in range(30)],
            task="stable_task",
        )

        # Task B: drifted
        baseline_task_b = _make_log_entries(
            [random.uniform(0.80, 0.90) for _ in range(30)],
            task="drifted_task",
        )
        current_task_b = _make_log_entries(
            [random.uniform(0.20, 0.40) for _ in range(30)],
            task="drifted_task",
        )

        detector.ingest_baseline(baseline_task_a + baseline_task_b)
        detector.ingest_current(current_task_a + current_task_b)

        report = detector.detect()

        results_by_entity = {r.entity_id: r for r in report.results if r.entity_type == "task"}
        assert "drifted_task" in results_by_entity
        assert results_by_entity["drifted_task"].drift_detected is True

    def test_skips_entities_with_insufficient_samples(self, settings: ObserverSettings) -> None:
        """Entities with fewer than min_samples should be skipped."""
        detector = DriftDetector(settings)

        # Only 5 samples (below detect_min_samples=10)
        baseline_entries = _make_log_entries([0.85] * 5)
        current_entries = _make_log_entries([0.40] * 5)

        detector.ingest_baseline(baseline_entries)
        detector.ingest_current(current_entries)

        report = detector.detect()

        assert report.total_entities_checked == 0
        assert len(report.results) == 0

    def test_skips_zero_confidence_entries(self, settings: ObserverSettings) -> None:
        """Entries with confidence <= 0 should be excluded from analysis."""
        detector = DriftDetector(settings)

        # Mix of valid and zero-confidence entries
        baseline_values = [0.85] * 15 + [0.0] * 5  # 15 valid, 5 zero
        current_values = [0.40] * 15 + [0.0] * 5  # 15 valid, 5 zero

        baseline_entries = _make_log_entries(baseline_values)
        current_entries = _make_log_entries(current_values)

        detector.ingest_baseline(baseline_entries)
        detector.ingest_current(current_entries)

        report = detector.detect()

        # Should still detect drift with the valid 15 samples
        assert report.total_entities_checked > 0
        drifted = [r for r in report.results if r.drift_detected]
        assert len(drifted) > 0

    def test_only_entities_in_both_windows_are_tested(self, settings: ObserverSettings) -> None:
        """Only entities present in both baseline and current should be tested."""
        detector = DriftDetector(settings)

        # Baseline has model A, current has model B (no overlap)
        baseline_entries = _make_log_entries(
            [0.85] * 20,
            model="model-only-in-baseline",
        )
        current_entries = _make_log_entries(
            [0.40] * 20,
            model="model-only-in-current",
        )

        detector.ingest_baseline(baseline_entries)
        detector.ingest_current(current_entries)

        report = detector.detect()

        # No entities overlap between baseline and current (by model key)
        model_results = [r for r in report.results if r.entity_type == "model"]
        assert len(model_results) == 0


class TestDriftReporting:
    """Tests for drift report structure and accessors."""

    def test_report_structure(self, settings: ObserverSettings) -> None:
        """DriftReport should contain correct structure."""
        detector = DriftDetector(settings)

        random.seed(42)
        baseline_entries = _make_log_entries([random.uniform(0.80, 0.95) for _ in range(30)])
        current_entries = _make_log_entries([random.uniform(0.30, 0.50) for _ in range(30)])

        detector.ingest_baseline(baseline_entries)
        detector.ingest_current(current_entries)

        report = detector.detect()

        assert isinstance(report, DriftReport)
        assert report.threshold_p_value == 0.05
        assert report.total_entities_checked > 0
        assert report.generated_at is not None

    def test_get_drifted_entities(self, settings: ObserverSettings) -> None:
        """get_drifted_entities should return only entities with drift_detected=True."""
        detector = DriftDetector(settings)

        random.seed(42)
        baseline_entries = _make_log_entries([random.uniform(0.80, 0.95) for _ in range(30)])
        current_entries = _make_log_entries([random.uniform(0.30, 0.50) for _ in range(30)])

        detector.ingest_baseline(baseline_entries)
        detector.ingest_current(current_entries)

        detector.detect()
        drifted = detector.get_drifted_entities()

        assert all(r.drift_detected for r in drifted)

    def test_to_dict_serialization(self, settings: ObserverSettings) -> None:
        """to_dict should produce serializable output."""
        detector = DriftDetector(settings)

        random.seed(42)
        baseline_entries = _make_log_entries([random.uniform(0.80, 0.95) for _ in range(30)])
        current_entries = _make_log_entries([random.uniform(0.30, 0.50) for _ in range(30)])

        detector.ingest_baseline(baseline_entries)
        detector.ingest_current(current_entries)

        detector.detect()
        data = detector.to_dict()

        assert "generated_at" in data
        assert "total_entities_checked" in data
        assert "drifted_entities" in data
        assert "results" in data
        assert isinstance(data["results"], list)

    def test_to_dict_no_report(self, settings: ObserverSettings) -> None:
        """to_dict with no report should return status no_report."""
        detector = DriftDetector(settings)
        data = detector.to_dict()
        assert data["status"] == "no_report"

    def test_last_report_initially_none(self, settings: ObserverSettings) -> None:
        """last_report should be None before any detection run."""
        detector = DriftDetector(settings)
        assert detector.last_report is None

    def test_result_contains_statistics(self, settings: ObserverSettings) -> None:
        """DriftResult should contain computed statistics."""
        detector = DriftDetector(settings)

        random.seed(42)
        baseline_entries = _make_log_entries([random.uniform(0.80, 0.95) for _ in range(30)])
        current_entries = _make_log_entries([random.uniform(0.30, 0.50) for _ in range(30)])

        detector.ingest_baseline(baseline_entries)
        detector.ingest_current(current_entries)

        report = detector.detect()

        for result in report.results:
            assert result.baseline_sample_count >= settings.detect_min_samples
            assert result.current_sample_count >= settings.detect_min_samples
            assert 0.0 <= result.ks_statistic <= 1.0
            assert 0.0 <= result.p_value <= 1.0
            assert result.baseline_mean > 0
            assert result.current_mean > 0
