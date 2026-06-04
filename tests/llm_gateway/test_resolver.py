"""Tests for llm-gateway routing resolver.

Tests the 3-level routing hierarchy:
1. Tenant-specific override (most specific)
2. Agent-specific override
3. Task default routing
4. Fallback to mid tier
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "llm-gateway"))

from src.models import (
    ModelConfig,
    RoutingConfig,
    Tier,
    TierConfig,
)
from src.routing.resolver import RouteResolution, RouteResolver


class TestRouteResolution:
    """Tests for RouteResolution data class."""

    def test_repr_with_model(self, routing_config: RoutingConfig) -> None:
        model = routing_config.tiers[Tier.STRONG.value].models[0]
        resolution = RouteResolution(tier="strong", model_config=model, source="tenant")
        assert "strong" in repr(resolution)
        assert "opus-4" in repr(resolution)
        assert "source=tenant" in repr(resolution)

    def test_repr_without_model(self) -> None:
        resolution = RouteResolution(tier="mid", source="default")
        assert "mid" in repr(resolution)
        assert "none" in repr(resolution)


class TestRouteResolver:
    """Tests for the 3-level routing hierarchy."""

    # --- Level 1: Tenant override (highest priority) ---

    def test_tenant_override_with_model_dict(self, routing_config: RoutingConfig) -> None:
        """Tenant routing with {model: X} overrides everything else."""
        resolver = RouteResolver(routing_config)
        result = resolver.resolve(
            agent="agent-eval",
            task="evaluate_control",
            tenant_id="tenant-premium",
        )
        assert result.source == "tenant"
        assert result.model_config is not None
        assert result.model_config.id == "opus-4"
        assert result.tier == "strong"

    def test_tenant_override_with_tier_string(self, routing_config: RoutingConfig) -> None:
        """Tenant routing with a tier string value."""
        resolver = RouteResolver(routing_config)
        result = resolver.resolve(
            agent="agent-eval",
            task="summarize",
            tenant_id="tenant-premium",
        )
        assert result.source == "tenant"
        assert result.tier == "strong"
        assert result.model_config is None

    def test_tenant_override_basic_tier(self, routing_config: RoutingConfig) -> None:
        """Basic tenant gets mid tier for evaluate_control (not strong)."""
        resolver = RouteResolver(routing_config)
        result = resolver.resolve(
            agent="agent-eval",
            task="evaluate_control",
            tenant_id="tenant-basic",
        )
        assert result.source == "tenant"
        assert result.tier == "mid"

    def test_tenant_override_task_not_configured(self, routing_config: RoutingConfig) -> None:
        """Tenant exists but task is not in their routing -> falls through."""
        resolver = RouteResolver(routing_config)
        result = resolver.resolve(
            agent="agent-eval",
            task="translate",
            tenant_id="tenant-premium",
        )
        # Should fall through to agent or task routing
        assert result.source != "tenant"

    # --- Level 2: Agent override ---

    def test_agent_override_tier_string(self, routing_config: RoutingConfig) -> None:
        """Agent routing with a tier string value."""
        resolver = RouteResolver(routing_config)
        result = resolver.resolve(
            agent="agent-eval",
            task="quick_check",
            tenant_id="tenant-unknown",
        )
        assert result.source == "agent"
        assert result.tier == "fast"

    def test_agent_override_model_dict(self, routing_config: RoutingConfig) -> None:
        """Agent routing with a model dict value."""
        resolver = RouteResolver(routing_config)
        result = resolver.resolve(
            agent="compliance-assistant",
            task="chat",
            tenant_id="tenant-unknown",
        )
        assert result.source == "agent"
        assert result.model_config is not None
        assert result.model_config.id == "sonnet-3.5"

    def test_agent_not_configured_falls_through(self, routing_config: RoutingConfig) -> None:
        """Unknown agent -> falls to task routing."""
        resolver = RouteResolver(routing_config)
        result = resolver.resolve(
            agent="unknown-agent",
            task="evaluate_control",
            tenant_id="tenant-unknown",
        )
        assert result.source == "task"
        assert result.tier == "strong"

    def test_agent_configured_but_task_not(self, routing_config: RoutingConfig) -> None:
        """Agent exists but task is not in their routing -> falls through."""
        resolver = RouteResolver(routing_config)
        result = resolver.resolve(
            agent="agent-eval",
            task="translate",
            tenant_id="tenant-unknown",
        )
        # Falls through to task routing
        assert result.source == "task"
        assert result.tier == "mid"

    # --- Level 3: Task default ---

    def test_task_routing_default(self, routing_config: RoutingConfig) -> None:
        """Task routing maps to a tier."""
        resolver = RouteResolver(routing_config)
        result = resolver.resolve(
            agent="unknown-agent",
            task="summarize",
            tenant_id="tenant-unknown",
        )
        assert result.source == "task"
        assert result.tier == "fast"

    def test_task_routing_translate(self, routing_config: RoutingConfig) -> None:
        """Task routing for translate -> mid tier."""
        resolver = RouteResolver(routing_config)
        result = resolver.resolve(
            agent="unknown-agent",
            task="translate",
            tenant_id="tenant-unknown",
        )
        assert result.source == "task"
        assert result.tier == "mid"

    # --- Level 4: Default fallback ---

    def test_default_fallback_to_mid(self, routing_config: RoutingConfig) -> None:
        """Unknown task with no routing -> defaults to mid."""
        resolver = RouteResolver(routing_config)
        result = resolver.resolve(
            agent="unknown-agent",
            task="unknown_task",
            tenant_id="tenant-unknown",
        )
        assert result.source == "default"
        assert result.tier == "mid"

    # --- Hierarchy priority ---

    def test_tenant_overrides_agent(self, routing_config: RoutingConfig) -> None:
        """Tenant override takes priority over agent override."""
        resolver = RouteResolver(routing_config)
        # tenant-basic has evaluate_control -> mid
        # agent-eval has evaluate_control -> strong
        result = resolver.resolve(
            agent="agent-eval",
            task="evaluate_control",
            tenant_id="tenant-basic",
        )
        assert result.source == "tenant"
        assert result.tier == "mid"  # tenant wins

    def test_agent_overrides_task(self, routing_config: RoutingConfig) -> None:
        """Agent override takes priority over task default."""
        resolver = RouteResolver(routing_config)
        # agent-eval/quick_check -> fast (agent level)
        # quick_check -> not in task_routing
        result = resolver.resolve(
            agent="agent-eval",
            task="quick_check",
            tenant_id="tenant-unknown",
        )
        assert result.source == "agent"
        assert result.tier == "fast"

    # --- Config update ---

    def test_update_config_atomically(self, routing_config: RoutingConfig) -> None:
        """Config swap is atomic and takes immediate effect."""
        resolver = RouteResolver(routing_config)

        # Before update
        result = resolver.resolve("unknown", "summarize", "unknown")
        assert result.tier == "fast"

        # Update config: change summarize to strong
        new_config = routing_config.model_copy(
            update={"task_routing": {"summarize": "strong"}}
        )
        resolver.update_config(new_config)

        # After update
        result = resolver.resolve("unknown", "summarize", "unknown")
        assert result.tier == "strong"

    # --- get_models_for_tier ---

    def test_get_models_for_tier_filters_unhealthy(self, routing_config: RoutingConfig) -> None:
        """Only healthy and enabled models are returned."""
        resolver = RouteResolver(routing_config)
        strong_models = resolver.get_models_for_tier("strong")
        # o1-preview is unhealthy, should be excluded
        assert len(strong_models) == 1
        assert strong_models[0].id == "opus-4"

    def test_get_models_for_tier_all_healthy(self, routing_config: RoutingConfig) -> None:
        """Fast tier has all healthy models."""
        resolver = RouteResolver(routing_config)
        fast_models = resolver.get_models_for_tier("fast")
        assert len(fast_models) == 2

    def test_get_models_for_tier_unknown(self, routing_config: RoutingConfig) -> None:
        """Unknown tier returns empty list."""
        resolver = RouteResolver(routing_config)
        models = resolver.get_models_for_tier("unknown-tier")
        assert models == []

    def test_get_models_for_tier_filters_disabled(self) -> None:
        """Disabled models are excluded even if healthy."""
        config = RoutingConfig(
            tiers={
                "fast": TierConfig(
                    models=[
                        ModelConfig(id="m1", provider="openai", model="gpt-4o-mini", healthy=True, enabled=False),
                        ModelConfig(id="m2", provider="openai", model="gpt-4o", healthy=True, enabled=True),
                    ]
                )
            }
        )
        resolver = RouteResolver(config)
        models = resolver.get_models_for_tier("fast")
        assert len(models) == 1
        assert models[0].id == "m2"

    # --- get_next_tier ---

    def test_get_next_tier_fast_to_mid(self, routing_config: RoutingConfig) -> None:
        """Escalation from fast goes to mid."""
        resolver = RouteResolver(routing_config)
        assert resolver.get_next_tier("fast") == "mid"

    def test_get_next_tier_mid_to_strong(self, routing_config: RoutingConfig) -> None:
        """Escalation from mid goes to strong."""
        resolver = RouteResolver(routing_config)
        assert resolver.get_next_tier("mid") == "strong"

    def test_get_next_tier_strong_returns_none(self, routing_config: RoutingConfig) -> None:
        """No escalation beyond strong."""
        resolver = RouteResolver(routing_config)
        assert resolver.get_next_tier("strong") is None

    def test_get_next_tier_unknown_returns_none(self, routing_config: RoutingConfig) -> None:
        """Unknown tier has no next."""
        resolver = RouteResolver(routing_config)
        assert resolver.get_next_tier("unknown") is None

    # --- Edge cases ---

    def test_interpret_route_value_unknown_format(self, routing_config: RoutingConfig) -> None:
        """Route value that is neither str nor dict defaults to mid."""
        # Inject a numeric value into tenant routing
        routing_config.tenant_routing["tenant-weird"] = {"some_task": 42}
        resolver = RouteResolver(routing_config)
        result = resolver.resolve(
            agent="any",
            task="some_task",
            tenant_id="tenant-weird",
        )
        assert result.source == "tenant"
        assert result.tier == "mid"

    def test_interpret_route_value_dict_with_tier_key(self, routing_config: RoutingConfig) -> None:
        """Dict with 'tier' key but no 'model' key uses the tier."""
        routing_config.tenant_routing["tenant-x"] = {"some_task": {"tier": "fast"}}
        resolver = RouteResolver(routing_config)
        result = resolver.resolve(
            agent="any",
            task="some_task",
            tenant_id="tenant-x",
        )
        assert result.source == "tenant"
        assert result.tier == "fast"

    def test_model_not_found_returns_none_model_config(self) -> None:
        """If model ID does not exist in any tier, model_config is None."""
        config = RoutingConfig(
            tiers={"fast": TierConfig(models=[])},
            tenant_routing={"t1": {"task1": {"model": "nonexistent"}}},
        )
        resolver = RouteResolver(config)
        result = resolver.resolve("agent", "task1", "t1")
        assert result.source == "tenant"
        assert result.model_config is None
        # Tier lookup for nonexistent model defaults to mid
        assert result.tier == "mid"

    def test_empty_config_defaults_to_mid(self) -> None:
        """Completely empty config falls back to mid for everything."""
        config = RoutingConfig()
        resolver = RouteResolver(config)
        result = resolver.resolve("any", "any_task", "any_tenant")
        assert result.source == "default"
        assert result.tier == "mid"
