"""Unit tests for observer issue detection.

Tests all 8 issue types and verifies no false positives on normal metrics.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from observer.src.config import ObserverSettings
from observer.src.detection.aggregator import AggregatedMetrics, MetricAggregator, ModelMetrics, TaskMetrics
from observer.src.detection.detector import DetectedIssue, IssueDetector, IssueSeverity, IssueType


class TestHighEscalationDetection:
    """Tests for HIGH_ESCALATION detection (>40% threshold)."""

    def test_detects_high_escalation(self, settings: ObserverSettings) -> None:
        """Escalation rate above 40% should trigger HIGH_ESCALATION issue."""
        aggregator = MetricAggregator()
        detector = IssueDetector(settings, aggregator)

        metrics = AggregatedMetrics(
            by_task={
                "evaluate_control": TaskMetrics(
                    task="evaluate_control",
                    sample_count=50,
                    escalation_rate=0.60,  # above 0.40 threshold
                    avg_confidence=0.85,
                    parse_failure_rate=0.05,
                    avg_cost_usd=0.005,
                    p95_latency_ms=2500.0,
                ),
            },
            by_model={},
        )

        issues = detector.detect(metrics)
        escalation_issues = [i for i in issues if i.issue_type == IssueType.HIGH_ESCALATION]

        assert len(escalation_issues) == 1
        assert escalation_issues[0].severity == IssueSeverity.HIGH
        assert escalation_issues[0].current_value == 0.60
        assert escalation_issues[0].task == "evaluate_control"

    def test_no_escalation_at_boundary(self, settings: ObserverSettings) -> None:
        """Escalation rate exactly at 40% should NOT trigger (must exceed threshold)."""
        aggregator = MetricAggregator()
        detector = IssueDetector(settings, aggregator)

        metrics = AggregatedMetrics(
            by_task={
                "evaluate_control": TaskMetrics(
                    task="evaluate_control",
                    sample_count=50,
                    escalation_rate=0.40,  # exactly at threshold
                    avg_confidence=0.85,
                    parse_failure_rate=0.05,
                    avg_cost_usd=0.005,
                    p95_latency_ms=2500.0,
                ),
            },
            by_model={},
        )

        issues = detector.detect(metrics)
        escalation_issues = [i for i in issues if i.issue_type == IssueType.HIGH_ESCALATION]
        assert len(escalation_issues) == 0


class TestLowConfidenceDetection:
    """Tests for LOW_CONFIDENCE detection (<0.70 threshold)."""

    def test_detects_low_confidence(self, settings: ObserverSettings) -> None:
        """Average confidence below 0.70 should trigger LOW_CONFIDENCE issue."""
        aggregator = MetricAggregator()
        detector = IssueDetector(settings, aggregator)

        metrics = AggregatedMetrics(
            by_task={
                "summarize_evidence": TaskMetrics(
                    task="summarize_evidence",
                    sample_count=20,
                    avg_confidence=0.55,  # below 0.70
                    escalation_rate=0.10,
                    parse_failure_rate=0.05,
                    avg_cost_usd=0.005,
                    p95_latency_ms=2500.0,
                ),
            },
            by_model={},
        )

        issues = detector.detect(metrics)
        confidence_issues = [i for i in issues if i.issue_type == IssueType.LOW_CONFIDENCE]

        assert len(confidence_issues) == 1
        assert confidence_issues[0].severity == IssueSeverity.MEDIUM
        assert confidence_issues[0].current_value == 0.55

    def test_no_low_confidence_at_threshold(self, settings: ObserverSettings) -> None:
        """Confidence exactly at 0.70 should NOT trigger."""
        aggregator = MetricAggregator()
        detector = IssueDetector(settings, aggregator)

        metrics = AggregatedMetrics(
            by_task={
                "task_a": TaskMetrics(
                    task="task_a",
                    sample_count=20,
                    avg_confidence=0.70,  # at threshold
                    escalation_rate=0.10,
                    parse_failure_rate=0.05,
                    avg_cost_usd=0.005,
                    p95_latency_ms=2500.0,
                ),
            },
            by_model={},
        )

        issues = detector.detect(metrics)
        confidence_issues = [i for i in issues if i.issue_type == IssueType.LOW_CONFIDENCE]
        assert len(confidence_issues) == 0


class TestParseFailureDetection:
    """Tests for PARSE_FAILURES detection (>15% threshold)."""

    def test_detects_parse_failures(self, settings: ObserverSettings) -> None:
        """Parse failure rate above 15% should trigger PARSE_FAILURES issue."""
        aggregator = MetricAggregator()
        detector = IssueDetector(settings, aggregator)

        metrics = AggregatedMetrics(
            by_task={
                "task_x": TaskMetrics(
                    task="task_x",
                    sample_count=30,
                    parse_failure_rate=0.25,  # above 0.15
                    avg_confidence=0.85,
                    escalation_rate=0.10,
                    avg_cost_usd=0.005,
                    p95_latency_ms=2500.0,
                ),
            },
            by_model={},
        )

        issues = detector.detect(metrics)
        parse_issues = [i for i in issues if i.issue_type == IssueType.PARSE_FAILURES]

        assert len(parse_issues) == 1
        assert parse_issues[0].severity == IssueSeverity.HIGH
        assert parse_issues[0].current_value == 0.25

    def test_no_parse_failure_below_threshold(self, settings: ObserverSettings) -> None:
        """Parse failure rate at 15% should NOT trigger."""
        aggregator = MetricAggregator()
        detector = IssueDetector(settings, aggregator)

        metrics = AggregatedMetrics(
            by_task={
                "task_x": TaskMetrics(
                    task="task_x",
                    sample_count=30,
                    parse_failure_rate=0.15,  # at threshold
                    avg_confidence=0.85,
                    escalation_rate=0.10,
                    avg_cost_usd=0.005,
                    p95_latency_ms=2500.0,
                ),
            },
            by_model={},
        )

        issues = detector.detect(metrics)
        parse_issues = [i for i in issues if i.issue_type == IssueType.PARSE_FAILURES]
        assert len(parse_issues) == 0


class TestCostSpikeDetection:
    """Tests for COST_SPIKE detection (>2x baseline)."""

    def test_detects_cost_spike(self, settings: ObserverSettings) -> None:
        """Cost more than 2x baseline should trigger COST_SPIKE."""
        aggregator = MetricAggregator()
        # Set baseline with known avg_cost
        baseline_metrics = AggregatedMetrics(
            by_task={
                "task_costly": TaskMetrics(
                    task="task_costly",
                    sample_count=50,
                    avg_cost_usd=0.01,
                    p95_latency_ms=2000.0,
                    avg_confidence=0.85,
                    escalation_rate=0.10,
                    parse_failure_rate=0.05,
                ),
            },
            by_model={},
        )
        aggregator.update_baseline(baseline_metrics)

        detector = IssueDetector(settings, aggregator)

        metrics = AggregatedMetrics(
            by_task={
                "task_costly": TaskMetrics(
                    task="task_costly",
                    sample_count=30,
                    avg_cost_usd=0.03,  # 3x baseline (above 2x)
                    p95_latency_ms=2000.0,
                    avg_confidence=0.85,
                    escalation_rate=0.10,
                    parse_failure_rate=0.05,
                ),
            },
            by_model={},
        )

        issues = detector.detect(metrics)
        cost_issues = [i for i in issues if i.issue_type == IssueType.COST_SPIKE]

        assert len(cost_issues) == 1
        assert cost_issues[0].current_value == pytest.approx(3.0)

    def test_no_cost_spike_without_baseline(self, settings: ObserverSettings) -> None:
        """No baseline means no cost spike detection."""
        aggregator = MetricAggregator()
        detector = IssueDetector(settings, aggregator)

        metrics = AggregatedMetrics(
            by_task={
                "task_costly": TaskMetrics(
                    task="task_costly",
                    sample_count=30,
                    avg_cost_usd=0.10,
                    p95_latency_ms=2000.0,
                    avg_confidence=0.85,
                    escalation_rate=0.10,
                    parse_failure_rate=0.05,
                ),
            },
            by_model={},
        )

        issues = detector.detect(metrics)
        cost_issues = [i for i in issues if i.issue_type == IssueType.COST_SPIKE]
        assert len(cost_issues) == 0


class TestModelErrorDetection:
    """Tests for MODEL_ERRORS detection (>5% threshold)."""

    def test_detects_model_errors(self, settings: ObserverSettings) -> None:
        """Model error rate above 5% should trigger MODEL_ERRORS with CRITICAL severity."""
        aggregator = MetricAggregator()
        detector = IssueDetector(settings, aggregator)

        metrics = AggregatedMetrics(
            by_task={},
            by_model={
                "claude-3-opus": ModelMetrics(
                    model="claude-3-opus",
                    sample_count=40,
                    error_rate=0.12,  # above 0.05
                    avg_latency_ms=8000.0,
                    p95_latency_ms=15000.0,
                ),
            },
        )

        issues = detector.detect(metrics)
        error_issues = [i for i in issues if i.issue_type == IssueType.MODEL_ERRORS]

        assert len(error_issues) == 1
        assert error_issues[0].severity == IssueSeverity.CRITICAL
        assert error_issues[0].model == "claude-3-opus"
        assert error_issues[0].current_value == 0.12

    def test_no_model_errors_below_threshold(self, settings: ObserverSettings) -> None:
        """Error rate at 5% should NOT trigger."""
        aggregator = MetricAggregator()
        detector = IssueDetector(settings, aggregator)

        metrics = AggregatedMetrics(
            by_task={},
            by_model={
                "claude-3-sonnet": ModelMetrics(
                    model="claude-3-sonnet",
                    sample_count=100,
                    error_rate=0.05,  # at threshold
                ),
            },
        )

        issues = detector.detect(metrics)
        error_issues = [i for i in issues if i.issue_type == IssueType.MODEL_ERRORS]
        assert len(error_issues) == 0


class TestLatencySpikeDetection:
    """Tests for LATENCY_SPIKE detection (>2x baseline P95)."""

    def test_detects_latency_spike(self, settings: ObserverSettings) -> None:
        """P95 latency more than 2x baseline triggers LATENCY_SPIKE."""
        aggregator = MetricAggregator()
        baseline_metrics = AggregatedMetrics(
            by_task={
                "task_slow": TaskMetrics(
                    task="task_slow",
                    sample_count=50,
                    p95_latency_ms=2000.0,
                    avg_cost_usd=0.01,
                    avg_confidence=0.85,
                    escalation_rate=0.10,
                    parse_failure_rate=0.05,
                ),
            },
            by_model={},
        )
        aggregator.update_baseline(baseline_metrics)

        detector = IssueDetector(settings, aggregator)

        metrics = AggregatedMetrics(
            by_task={
                "task_slow": TaskMetrics(
                    task="task_slow",
                    sample_count=30,
                    p95_latency_ms=5000.0,  # 2.5x baseline
                    avg_cost_usd=0.01,
                    avg_confidence=0.85,
                    escalation_rate=0.10,
                    parse_failure_rate=0.05,
                ),
            },
            by_model={},
        )

        issues = detector.detect(metrics)
        latency_issues = [i for i in issues if i.issue_type == IssueType.LATENCY_SPIKE]

        assert len(latency_issues) == 1
        assert latency_issues[0].current_value == pytest.approx(2.5)

    def test_no_latency_spike_within_threshold(self, settings: ObserverSettings) -> None:
        """P95 latency at 2x baseline should NOT trigger (must exceed)."""
        aggregator = MetricAggregator()
        baseline_metrics = AggregatedMetrics(
            by_task={
                "task_ok": TaskMetrics(
                    task="task_ok",
                    sample_count=50,
                    p95_latency_ms=2000.0,
                    avg_cost_usd=0.01,
                    avg_confidence=0.85,
                    escalation_rate=0.10,
                    parse_failure_rate=0.05,
                ),
            },
            by_model={},
        )
        aggregator.update_baseline(baseline_metrics)

        detector = IssueDetector(settings, aggregator)

        metrics = AggregatedMetrics(
            by_task={
                "task_ok": TaskMetrics(
                    task="task_ok",
                    sample_count=30,
                    p95_latency_ms=4000.0,  # exactly 2x
                    avg_cost_usd=0.01,
                    avg_confidence=0.85,
                    escalation_rate=0.10,
                    parse_failure_rate=0.05,
                ),
            },
            by_model={},
        )

        issues = detector.detect(metrics)
        latency_issues = [i for i in issues if i.issue_type == IssueType.LATENCY_SPIKE]
        assert len(latency_issues) == 0


class TestNoFalsePositives:
    """Verify no issues are detected on healthy metrics."""

    def test_normal_metrics_produce_no_issues(
        self,
        settings: ObserverSettings,
        normal_task_metrics: TaskMetrics,
        normal_model_metrics: ModelMetrics,
    ) -> None:
        """Healthy metrics should not trigger any detection rules."""
        aggregator = MetricAggregator()
        detector = IssueDetector(settings, aggregator)

        metrics = AggregatedMetrics(
            by_task={normal_task_metrics.task: normal_task_metrics},
            by_model={normal_model_metrics.model: normal_model_metrics},
        )

        issues = detector.detect(metrics)
        assert len(issues) == 0

    def test_skips_tasks_below_min_samples(self, settings: ObserverSettings) -> None:
        """Tasks with fewer than min_samples should be skipped entirely."""
        aggregator = MetricAggregator()
        detector = IssueDetector(settings, aggregator)

        metrics = AggregatedMetrics(
            by_task={
                "low_traffic_task": TaskMetrics(
                    task="low_traffic_task",
                    sample_count=5,  # below detect_min_samples=10
                    escalation_rate=0.90,  # would trigger if checked
                    avg_confidence=0.30,
                    parse_failure_rate=0.50,
                ),
            },
            by_model={},
        )

        issues = detector.detect(metrics)
        assert len(issues) == 0

    def test_skips_models_below_min_samples(self, settings: ObserverSettings) -> None:
        """Models with fewer than min_samples should be skipped."""
        aggregator = MetricAggregator()
        detector = IssueDetector(settings, aggregator)

        metrics = AggregatedMetrics(
            by_task={},
            by_model={
                "rare-model": ModelMetrics(
                    model="rare-model",
                    sample_count=3,  # below detect_min_samples=10
                    error_rate=0.50,  # would trigger if checked
                ),
            },
        )

        issues = detector.detect(metrics)
        assert len(issues) == 0


class TestMultipleIssues:
    """Tests for detecting multiple concurrent issues."""

    def test_detects_multiple_issues_same_task(
        self,
        settings: ObserverSettings,
        problematic_task_metrics: TaskMetrics,
    ) -> None:
        """A single task with multiple problems should produce multiple issues."""
        aggregator = MetricAggregator()
        detector = IssueDetector(settings, aggregator)

        metrics = AggregatedMetrics(
            by_task={problematic_task_metrics.task: problematic_task_metrics},
            by_model={},
        )

        issues = detector.detect(metrics)
        issue_types = {i.issue_type for i in issues}

        # Problematic task has: high_escalation (0.60 > 0.40), low_confidence (0.55 < 0.70),
        # parse_failures (0.25 > 0.15)
        assert IssueType.HIGH_ESCALATION in issue_types
        assert IssueType.LOW_CONFIDENCE in issue_types
        assert IssueType.PARSE_FAILURES in issue_types

    def test_issues_sorted_by_severity(self, settings: ObserverSettings) -> None:
        """Issues should be returned sorted by severity (CRITICAL first)."""
        aggregator = MetricAggregator()
        detector = IssueDetector(settings, aggregator)

        metrics = AggregatedMetrics(
            by_task={
                "task_a": TaskMetrics(
                    task="task_a",
                    sample_count=20,
                    avg_confidence=0.55,  # LOW_CONFIDENCE -> MEDIUM
                    escalation_rate=0.10,
                    parse_failure_rate=0.05,
                    avg_cost_usd=0.005,
                    p95_latency_ms=2500.0,
                ),
            },
            by_model={
                "model_b": ModelMetrics(
                    model="model_b",
                    sample_count=20,
                    error_rate=0.15,  # MODEL_ERRORS -> CRITICAL
                ),
            },
        )

        issues = detector.detect(metrics)
        assert len(issues) == 2
        assert issues[0].severity == IssueSeverity.CRITICAL
        assert issues[1].severity == IssueSeverity.MEDIUM
