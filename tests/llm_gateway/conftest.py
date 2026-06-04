"""Shared fixtures for llm-gateway tests."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# Add llm-gateway/src to path so imports work
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "llm-gateway"))

from src.models import (
    CanaryConfig,
    CompletionRequest,
    CostConfig,
    EscalationConfig,
    Message,
    MessageRole,
    ModelConfig,
    NormalizedResponse,
    ResponseFormat,
    RoutingConfig,
    Tier,
    TierConfig,
    Tool,
    ToolCall,
    ToolCallFunction,
    ToolFunction,
    Usage,
)


@pytest.fixture
def routing_config() -> RoutingConfig:
    """Create a complete routing config for tests."""
    return RoutingConfig(
        tiers={
            Tier.FAST.value: TierConfig(
                models=[
                    ModelConfig(
                        id="haiku-3.5",
                        provider="anthropic",
                        model="claude-3-5-haiku-20241022",
                        endpoint="https://api.anthropic.com",
                        healthy=True,
                        enabled=True,
                    ),
                    ModelConfig(
                        id="gpt-4o-mini",
                        provider="openai",
                        model="gpt-4o-mini",
                        endpoint="https://api.openai.com",
                        healthy=True,
                        enabled=True,
                    ),
                ]
            ),
            Tier.MID.value: TierConfig(
                models=[
                    ModelConfig(
                        id="sonnet-3.5",
                        provider="anthropic",
                        model="claude-3-5-sonnet-20241022",
                        endpoint="https://api.anthropic.com",
                        healthy=True,
                        enabled=True,
                    ),
                ]
            ),
            Tier.STRONG.value: TierConfig(
                models=[
                    ModelConfig(
                        id="opus-4",
                        provider="anthropic",
                        model="claude-opus-4-20250514",
                        endpoint="https://api.anthropic.com",
                        healthy=True,
                        enabled=True,
                    ),
                    ModelConfig(
                        id="o1-preview",
                        provider="openai",
                        model="o1-preview",
                        endpoint="https://api.openai.com",
                        healthy=False,
                        enabled=True,
                    ),
                ]
            ),
        },
        task_routing={
            "evaluate_control": Tier.STRONG.value,
            "summarize": Tier.FAST.value,
            "translate": Tier.MID.value,
        },
        agent_routing={
            "agent-eval": {
                "evaluate_control": Tier.STRONG.value,
                "quick_check": Tier.FAST.value,
            },
            "compliance-assistant": {
                "chat": {"model": "sonnet-3.5"},
            },
        },
        tenant_routing={
            "tenant-premium": {
                "evaluate_control": {"model": "opus-4"},
                "summarize": Tier.STRONG.value,
            },
            "tenant-basic": {
                "evaluate_control": Tier.MID.value,
            },
        },
        canary={
            "evaluate_control": CanaryConfig(
                model="sonnet-3.5",
                traffic_pct=20,
                min_samples=30,
            ),
            "agent-eval/quick_check": CanaryConfig(
                model="gpt-4o-mini",
                traffic_pct=50,
                min_samples=10,
            ),
        },
        escalation=EscalationConfig(
            enabled=True,
            max_escalations=2,
            path=["fast", "mid", "strong"],
        ),
        cost=CostConfig(
            max_per_request_usd=1.00,
            max_per_tenant_per_day_usd=50.00,
        ),
    )


@pytest.fixture
def cost_config() -> CostConfig:
    """Cost config with $50/day limit."""
    return CostConfig(
        max_per_request_usd=1.00,
        max_per_tenant_per_day_usd=50.00,
    )


@pytest.fixture
def escalation_config() -> EscalationConfig:
    """Standard escalation config."""
    return EscalationConfig(
        enabled=True,
        max_escalations=2,
        path=["fast", "mid", "strong"],
    )


@pytest.fixture
def sample_request() -> CompletionRequest:
    """A sample completion request."""
    return CompletionRequest(
        messages=[
            Message(role=MessageRole.USER, content="Evaluate this control."),
        ],
        task="evaluate_control",
        agent="agent-eval",
        tenant_id="tenant-001",
        trace_id="trace-abc-123",
        confidence_threshold=0.7,
        max_tokens=4096,
        temperature=0.0,
    )


@pytest.fixture
def sample_response() -> NormalizedResponse:
    """A sample normalized response with JSON content containing confidence."""
    return NormalizedResponse(
        content='{"result": "compliant", "confidence": 0.92, "reasoning": "All criteria met."}',
        tool_calls=None,
        usage=Usage(input_tokens=500, output_tokens=200),
        finish_reason="stop",
    )


@pytest.fixture
def mock_redis() -> AsyncMock:
    """Mock Redis client for budget tracker tests."""
    redis = AsyncMock()
    redis.ping = AsyncMock(return_value=True)
    redis.incrbyfloat = AsyncMock(return_value=5.50)
    redis.get = AsyncMock(return_value="5.50")
    redis.ttl = AsyncMock(return_value=3600)
    redis.expire = AsyncMock(return_value=True)
    redis.incr = AsyncMock(return_value=10)
    redis.rpush = AsyncMock(return_value=1)
    redis.lpop = AsyncMock(return_value=None)
    redis.lrange = AsyncMock(return_value=[])
    redis.llen = AsyncMock(return_value=0)
    redis.aclose = AsyncMock()
    return redis


@pytest.fixture
def sample_tools() -> list[Tool]:
    """Sample tool definitions in OpenAI format."""
    return [
        Tool(
            type="function",
            function=ToolFunction(
                name="search_evidence",
                description="Search for compliance evidence files",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query",
                        },
                        "framework": {
                            "type": "string",
                            "description": "Compliance framework (e.g., SOC2, ISO27001)",
                        },
                    },
                    "required": ["query"],
                },
            ),
        ),
        Tool(
            type="function",
            function=ToolFunction(
                name="get_control_status",
                description="Get the current status of a control",
                parameters={
                    "type": "object",
                    "properties": {
                        "control_id": {
                            "type": "string",
                            "description": "The control identifier",
                        },
                    },
                    "required": ["control_id"],
                },
            ),
        ),
    ]
