"""Tests for llm-gateway canary traffic splitting.

Tests canary experiment management, traffic routing, metrics recording,
and experiment lifecycle (start/promote/rollback).
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "llm-gateway"))

from src.models import CanaryConfig, CanaryMetrics, CanaryStatus, RoutingConfig
from src.routing.canary import CanaryManager, _CanaryExperiment


class TestCanaryManagerTrafficSplit:
    """Tests for traffic splitting logic."""

    @pytest.fixture
    def manager_with_experiments(self, routing_config: RoutingConfig) -> CanaryManager:
        """Manager initialized with config containing canary experiments."""
        manager = CanaryManager()
        manager.update_from_config(routing_config)
        return manager

    def test_canary_traffic_split_respects_percentage(
        self, manager_with_experiments: CanaryManager
    ) -> None:
        """Over many calls, canary rate roughly matches traffic_pct."""
        canary_count = 0
        total = 1000
        for _ in range(total):
            use_canary, variant = manager_with_experiments.should_use_canary(
                agent="unknown",
                task="evaluate_control",
            )
            if use_canary:
                canary_count += 1

        # 20% traffic -> expect roughly 200 canary calls
        # Allow wide margin for randomness
        assert 100 < canary_count < 350

    def test_no_experiment_returns_control(
        self, manager_with_experiments: CanaryManager
    ) -> None:
        """Task without experiment always returns control."""
        use_canary, variant = manager_with_experiments.should_use_canary(
            agent="unknown",
            task="nonexistent_task",
        )
        assert use_canary is False
        assert variant == "control"

    def test_agent_task_key_match(
        self, manager_with_experiments: CanaryManager
    ) -> None:
        """Agent/task key matches before task-only key."""
        # "agent-eval/quick_check" has 50% traffic
        canary_count = 0
        total = 200
        for _ in range(total):
            use_canary, _ = manager_with_experiments.should_use_canary(
                agent="agent-eval",
                task="quick_check",
            )
            if use_canary:
                canary_count += 1

        # 50% traffic -> expect roughly 100
        assert 60 < canary_count < 140

    def test_100_percent_always_canary(self) -> None:
        """100% traffic always routes to canary."""
        manager = CanaryManager()
        manager.set_canary("always_canary", model="test-model", traffic_pct=100)

        for _ in range(50):
            use_canary, variant = manager.should_use_canary("any", "always_canary")
            assert use_canary is True
            assert variant == "canary"

    @patch("random.randint", return_value=1)
    def test_deterministic_canary_at_boundary(self, mock_randint: object) -> None:
        """When random roll <= traffic_pct, request goes to canary."""
        manager = CanaryManager()
        manager.set_canary("test_task", model="m1", traffic_pct=20)

        use_canary, variant = manager.should_use_canary("agent", "test_task")
        assert use_canary is True
        assert variant == "canary"

    @patch("random.randint", return_value=21)
    def test_deterministic_control_at_boundary(self, mock_randint: object) -> None:
        """When random roll > traffic_pct, request stays with control."""
        manager = CanaryManager()
        manager.set_canary("test_task", model="m1", traffic_pct=20)

        use_canary, variant = manager.should_use_canary("agent", "test_task")
        assert use_canary is False
        assert variant == "control"


class TestCanaryManagerModelId:
    """Tests for get_canary_model_id."""

    def test_get_canary_model_id_exists(self, routing_config: RoutingConfig) -> None:
        """Returns model ID for active experiment."""
        manager = CanaryManager()
        manager.update_from_config(routing_config)
        model_id = manager.get_canary_model_id("unknown", "evaluate_control")
        assert model_id == "sonnet-3.5"

    def test_get_canary_model_id_agent_task_key(self, routing_config: RoutingConfig) -> None:
        """Agent/task key returns correct model."""
        manager = CanaryManager()
        manager.update_from_config(routing_config)
        model_id = manager.get_canary_model_id("agent-eval", "quick_check")
        assert model_id == "gpt-4o-mini"

    def test_get_canary_model_id_not_found(self) -> None:
        """Returns None when no experiment for task."""
        manager = CanaryManager()
        model_id = manager.get_canary_model_id("agent", "no_experiment_here")
        assert model_id is None


class TestCanaryManagerRecording:
    """Tests for recording experiment results."""

    def test_record_result_canary(self, routing_config: RoutingConfig) -> None:
        """Records canary variant results correctly."""
        manager = CanaryManager()
        manager.update_from_config(routing_config)

        manager.record_result(
            agent="unknown",
            task="evaluate_control",
            variant="canary",
            confidence=0.85,
            latency_ms=500,
            error=False,
            escalated=False,
            cost_usd=0.05,
        )

        status = manager.get_status("evaluate_control")
        assert status is not None
        assert status.canary.sample_count == 1
        assert status.canary.avg_confidence == 0.85
        assert status.canary.avg_latency_ms == 500.0

    def test_record_result_control(self, routing_config: RoutingConfig) -> None:
        """Records control variant results correctly."""
        manager = CanaryManager()
        manager.update_from_config(routing_config)

        manager.record_result(
            agent="unknown",
            task="evaluate_control",
            variant="control",
            confidence=0.90,
            latency_ms=400,
            error=False,
            escalated=False,
            cost_usd=0.08,
        )

        status = manager.get_status("evaluate_control")
        assert status is not None
        assert status.control.sample_count == 1
        assert status.control.avg_confidence == 0.90

    def test_record_ignores_unknown_experiment(self) -> None:
        """Recording for non-existent experiment is a no-op."""
        manager = CanaryManager()
        # Should not raise
        manager.record_result(
            agent="x",
            task="nonexistent",
            variant="canary",
            confidence=0.5,
            latency_ms=100,
            error=False,
            escalated=False,
            cost_usd=0.01,
        )

    def test_metrics_aggregate_correctly(self) -> None:
        """Multiple samples aggregate correctly."""
        manager = CanaryManager()
        manager.set_canary("task1", model="m1", traffic_pct=50)

        for i in range(5):
            manager.record_result(
                agent="agent",
                task="task1",
                variant="canary",
                confidence=0.7 + i * 0.05,
                latency_ms=100 + i * 50,
                error=(i == 3),  # 1 error
                escalated=(i == 4),  # 1 escalation
                cost_usd=0.01 * (i + 1),
            )

        status = manager.get_status("task1")
        assert status is not None
        assert status.canary.sample_count == 5
        assert status.canary.error_rate == pytest.approx(0.2)  # 1/5
        assert status.canary.escalation_rate == pytest.approx(0.2)  # 1/5
        # avg confidence: (0.7+0.75+0.8+0.85+0.9)/5 = 0.8
        assert status.canary.avg_confidence == pytest.approx(0.8)
        # avg latency: (100+150+200+250+300)/5 = 200
        assert status.canary.avg_latency_ms == pytest.approx(200.0)


class TestCanaryManagerLifecycle:
    """Tests for experiment lifecycle: set, promote, rollback."""

    def test_set_canary_creates_experiment(self) -> None:
        """set_canary creates a new active experiment."""
        manager = CanaryManager()
        status = manager.set_canary("new_task", model="test-model", traffic_pct=30)
        assert status.active is True
        assert status.model == "test-model"
        assert status.traffic_pct == 30

    def test_set_canary_overwrites_existing(self) -> None:
        """set_canary on existing experiment replaces it."""
        manager = CanaryManager()
        manager.set_canary("task1", model="model-a", traffic_pct=20)
        status = manager.set_canary("task1", model="model-b", traffic_pct=50)
        assert status.model == "model-b"
        assert status.traffic_pct == 50

    def test_promote_canary_removes_experiment(self) -> None:
        """Promoting removes the experiment (model becomes primary via config)."""
        manager = CanaryManager()
        manager.set_canary("task1", model="new-model", traffic_pct=30)
        success = manager.promote_canary("task1")
        assert success is True
        # Experiment removed
        status = manager.get_status("task1")
        assert status is None

    def test_promote_nonexistent_returns_false(self) -> None:
        """Promoting non-existent experiment returns False."""
        manager = CanaryManager()
        assert manager.promote_canary("no_such_task") is False

    def test_rollback_canary_removes_experiment(self) -> None:
        """Rolling back removes the experiment, reverting to control only."""
        manager = CanaryManager()
        manager.set_canary("task1", model="bad-model", traffic_pct=30)
        success = manager.rollback_canary("task1")
        assert success is True
        status = manager.get_status("task1")
        assert status is None

    def test_rollback_nonexistent_returns_false(self) -> None:
        """Rolling back non-existent experiment returns False."""
        manager = CanaryManager()
        assert manager.rollback_canary("no_such_task") is False


class TestCanaryManagerConfigSync:
    """Tests for syncing experiments from routing config."""

    def test_update_from_config_creates_experiments(self, routing_config: RoutingConfig) -> None:
        """Experiments are created from config canary section."""
        manager = CanaryManager()
        manager.update_from_config(routing_config)
        status = manager.get_status("evaluate_control")
        assert status is not None
        assert status.active is True

    def test_update_from_config_removes_stale(self, routing_config: RoutingConfig) -> None:
        """Experiments not in new config are removed."""
        manager = CanaryManager()
        manager.set_canary("will_be_removed", model="x", traffic_pct=10)
        manager.update_from_config(routing_config)
        status = manager.get_status("will_be_removed")
        assert status is None

    def test_update_from_config_preserves_existing(self, routing_config: RoutingConfig) -> None:
        """Existing experiments in config are updated, not recreated."""
        manager = CanaryManager()
        manager.update_from_config(routing_config)
        # Record some data
        manager.record_result(
            agent="unknown",
            task="evaluate_control",
            variant="canary",
            confidence=0.9,
            latency_ms=100,
            error=False,
            escalated=False,
            cost_usd=0.01,
        )
        # Update again with same config
        manager.update_from_config(routing_config)
        status = manager.get_status("evaluate_control")
        # Data should be preserved since experiment was updated, not recreated
        assert status is not None
        assert status.canary.sample_count == 1


class TestCanaryGetStatus:
    """Tests for get_status method."""

    def test_get_status_exact_key(self) -> None:
        """Exact key match returns status."""
        manager = CanaryManager()
        manager.set_canary("my_task", model="m", traffic_pct=20)
        status = manager.get_status("my_task")
        assert status is not None
        assert status.task == "my_task"

    def test_get_status_partial_key_match(self) -> None:
        """Partial key match (task substring in key) returns status."""
        manager = CanaryManager()
        manager.set_canary("agent-eval/quick_check", model="m", traffic_pct=50)
        status = manager.get_status("quick_check")
        assert status is not None
        assert status.task == "agent-eval/quick_check"

    def test_get_status_not_found(self) -> None:
        """Returns None if no matching experiment."""
        manager = CanaryManager()
        assert manager.get_status("nonexistent") is None


class TestCanaryMetricsComputation:
    """Tests for metrics computation in _CanaryExperiment."""

    def test_empty_samples_returns_zero_metrics(self) -> None:
        """No samples returns all-zero metrics."""
        config = CanaryConfig(model="m", traffic_pct=20, min_samples=30)
        experiment = _CanaryExperiment(task_key="test", config=config)
        status = experiment.get_status()
        assert status.canary.sample_count == 0
        assert status.canary.avg_confidence == 0.0
        assert status.control.sample_count == 0

    def test_p95_latency_calculation(self) -> None:
        """P95 latency is computed correctly."""
        config = CanaryConfig(model="m", traffic_pct=50, min_samples=5)
        experiment = _CanaryExperiment(task_key="test", config=config)

        # Record 20 samples with increasing latency
        for i in range(20):
            experiment.record(
                variant="canary",
                confidence=0.8,
                latency_ms=100 + i * 10,  # 100, 110, ..., 290
                error=False,
                escalated=False,
                cost_usd=0.01,
            )

        status = experiment.get_status()
        # p95 index = int(20 * 0.95) = 19 (capped at count-1=19)
        # sorted latencies: 100, 110, ..., 290
        # p95 = latency at index 19 = 290
        assert status.canary.p95_latency_ms == 290.0

    def test_error_and_escalation_rates(self) -> None:
        """Error and escalation rates computed as fractions."""
        config = CanaryConfig(model="m", traffic_pct=50, min_samples=5)
        experiment = _CanaryExperiment(task_key="test", config=config)

        experiment.record("control", 0.8, 100, error=True, escalated=False, cost_usd=0.01)
        experiment.record("control", 0.8, 100, error=False, escalated=True, cost_usd=0.01)
        experiment.record("control", 0.8, 100, error=False, escalated=False, cost_usd=0.01)
        experiment.record("control", 0.8, 100, error=True, escalated=True, cost_usd=0.01)

        status = experiment.get_status()
        assert status.control.sample_count == 4
        assert status.control.error_rate == pytest.approx(0.5)  # 2/4
        assert status.control.escalation_rate == pytest.approx(0.5)  # 2/4

    def test_avg_cost_computation(self) -> None:
        """Average cost is computed correctly."""
        config = CanaryConfig(model="m", traffic_pct=50, min_samples=5)
        experiment = _CanaryExperiment(task_key="test", config=config)

        experiment.record("canary", 0.8, 100, error=False, escalated=False, cost_usd=0.02)
        experiment.record("canary", 0.8, 100, error=False, escalated=False, cost_usd=0.06)
        experiment.record("canary", 0.8, 100, error=False, escalated=False, cost_usd=0.04)

        status = experiment.get_status()
        # avg = (0.02 + 0.06 + 0.04) / 3 = 0.04
        assert status.canary.avg_cost_usd == pytest.approx(0.04)
