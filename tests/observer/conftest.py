"""Shared fixtures for observer unit tests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from observer.src.changes.proposal import ApplyTier, Change, ChangeStatus, ChangeType
from observer.src.config import ObserverSettings
from observer.src.detection.aggregator import AggregatedMetrics, MetricAggregator, ModelMetrics, TaskMetrics
from observer.src.detection.log_ingestor import LogEntry


@pytest.fixture
def settings() -> ObserverSettings:
    """Default observer settings for tests."""
    return ObserverSettings(
        llm_gateway_admin_url="http://localhost:4001",
        memory_url="http://localhost:5000",
        detect_escalation_rate=0.40,
        detect_low_confidence=0.70,
        detect_parse_failure_rate=0.15,
        detect_cost_spike_multiplier=2.0,
        detect_error_rate=0.05,
        detect_latency_spike_multiplier=2.0,
        detect_stale_pattern_days=90,
        detect_min_samples=10,
        circuit_breaker_max_rollbacks=3,
        circuit_breaker_window_hours=6,
        circuit_breaker_cooldown_hours=12,
        auto_apply_min_confidence=0.80,
        auto_apply_min_samples=20,
        max_auto_applies_per_day=10,
        canary_traffic_pct=20,
        canary_min_samples=30,
        max_concurrent_canaries=3,
        drift_threshold_ks_pvalue=0.05,
        self_reg_min_confidence_floor=0.60,
        self_reg_min_confidence_ceiling=0.95,
        self_reg_min_samples_floor=10,
        self_reg_min_samples_ceiling=100,
        validation_delay_minutes=60,
    )


@pytest.fixture
def aggregator() -> MetricAggregator:
    """Metric aggregator instance."""
    return MetricAggregator()


@pytest.fixture
def normal_task_metrics() -> TaskMetrics:
    """Task metrics representing healthy state - no issues should be detected."""
    return TaskMetrics(
        task="evaluate_control",
        sample_count=50,
        avg_confidence=0.85,
        escalation_rate=0.10,
        failure_rate=0.02,
        parse_failure_rate=0.05,
        avg_latency_ms=1200.0,
        p95_latency_ms=2500.0,
        avg_cost_usd=0.005,
        total_cost_usd=0.25,
        error_rate=0.01,
    )


@pytest.fixture
def problematic_task_metrics() -> TaskMetrics:
    """Task metrics with multiple issues above thresholds."""
    return TaskMetrics(
        task="summarize_evidence",
        sample_count=30,
        avg_confidence=0.55,  # below 0.70
        escalation_rate=0.60,  # above 0.40
        failure_rate=0.15,
        parse_failure_rate=0.25,  # above 0.15
        avg_latency_ms=5000.0,
        p95_latency_ms=12000.0,
        avg_cost_usd=0.050,
        total_cost_usd=1.50,
        error_rate=0.08,
    )


@pytest.fixture
def normal_model_metrics() -> ModelMetrics:
    """Model metrics representing healthy state."""
    return ModelMetrics(
        model="claude-3-sonnet",
        sample_count=100,
        error_rate=0.02,
        avg_latency_ms=1500.0,
        p95_latency_ms=3000.0,
        avg_cost_usd=0.01,
        total_cost_usd=1.0,
        availability=0.98,
    )


@pytest.fixture
def problematic_model_metrics() -> ModelMetrics:
    """Model metrics with high error rate."""
    return ModelMetrics(
        model="claude-3-opus",
        sample_count=40,
        error_rate=0.12,  # above 0.05
        avg_latency_ms=8000.0,
        p95_latency_ms=15000.0,
        avg_cost_usd=0.05,
        total_cost_usd=2.0,
        availability=0.88,
    )


@pytest.fixture
def sample_log_entries() -> list[LogEntry]:
    """Sample log entries for testing."""
    return [
        LogEntry(
            timestamp="2024-01-01T12:00:00Z",
            trace_id="trace_001",
            agent="agent-eval",
            task="evaluate_control",
            tier_requested="mid",
            tier_used="mid",
            model_used="claude-3-sonnet",
            escalated=False,
            input_tokens=1000,
            output_tokens=500,
            latency_ms=1200,
            confidence=0.85,
            success=True,
            error=None,
            tenant_id="tenant_001",
            tool_calls_count=0,
            parse_success=True,
            cost_usd=0.005,
        ),
        LogEntry(
            timestamp="2024-01-01T12:01:00Z",
            trace_id="trace_002",
            agent="compliance-assistant",
            task="summarize_evidence",
            tier_requested="fast",
            tier_used="fast",
            model_used="claude-3-haiku",
            escalated=False,
            input_tokens=800,
            output_tokens=300,
            latency_ms=800,
            confidence=0.90,
            success=True,
            error=None,
            tenant_id="tenant_001",
            tool_calls_count=1,
            parse_success=True,
            cost_usd=0.002,
        ),
    ]


@pytest.fixture
def auto_change() -> Change:
    """A tier-1 auto-apply change."""
    return Change(
        id="chg_test_auto_001",
        change_type=ChangeType.ROUTING,
        apply_tier=ApplyTier.AUTO,
        status=ChangeStatus.PROPOSED,
        task="evaluate_control",
        description="Route evaluate_control to strong tier",
        config_diff={"task_routing": {"evaluate_control": "strong"}, "reason": "high escalation"},
        confidence=0.90,
        sample_count=50,
    )


@pytest.fixture
def canary_change() -> Change:
    """A tier-2 canary change."""
    return Change(
        id="chg_test_canary_001",
        change_type=ChangeType.PROMPT,
        apply_tier=ApplyTier.CANARY,
        status=ChangeStatus.PROPOSED,
        task="summarize_evidence",
        description="Rewrite prompt for summarize_evidence",
        config_diff={"task": "summarize_evidence", "action": "rewrite"},
        confidence=0.80,
        sample_count=30,
    )


@pytest.fixture
def human_change() -> Change:
    """A tier-3 human-approval change."""
    return Change(
        id="chg_test_human_001",
        change_type=ChangeType.MODEL,
        apply_tier=ApplyTier.HUMAN,
        status=ChangeStatus.PROPOSED,
        task="evaluate_control",
        model="claude-3-opus",
        description="Swap model for evaluate_control",
        config_diff={"task": "evaluate_control", "model": "claude-3-opus", "action": "swap"},
        confidence=0.70,
        sample_count=40,
    )


@pytest.fixture
def mock_http_client() -> AsyncMock:
    """Mock httpx.AsyncClient for gateway admin API."""
    client = AsyncMock()
    # Default success response
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {
        "escalation_rate": 0.10,
        "avg_confidence": 0.85,
        "failure_rate": 0.02,
        "p95_latency_ms": 2500,
    }
    response.text = ""
    client.get.return_value = response
    client.post.return_value = response
    return client


@pytest.fixture
def mock_memory_client() -> AsyncMock:
    """Mock httpx.AsyncClient for memory service."""
    client = AsyncMock()
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"items": []}
    client.get.return_value = response
    client.post.return_value = response
    return client
