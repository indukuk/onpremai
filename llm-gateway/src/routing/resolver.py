from __future__ import annotations

from typing import Any

import structlog

from src.models import ModelConfig, RoutingConfig, Tier

logger = structlog.get_logger(__name__)


class RouteResolution:
    """Result of routing resolution."""

    def __init__(
        self,
        tier: str,
        model_config: ModelConfig | None = None,
        source: str = "default",
    ) -> None:
        self.tier = tier
        self.model_config = model_config
        self.source = source  # "tenant", "agent", "task", "default"

    def __repr__(self) -> str:
        model_id = self.model_config.id if self.model_config else "none"
        return f"RouteResolution(tier={self.tier}, model={model_id}, source={self.source})"


class RouteResolver:
    """3-level routing hierarchy resolver.

    Resolution order (most specific wins):
    1. tenant_routing[tenant_id][task] -> specific model or tier
    2. agent_routing[agent][task] -> specific model or tier
    3. task_routing[task] -> default tier
    4. fallback to 'mid' tier
    """

    def __init__(self, config: RoutingConfig) -> None:
        self._config = config

    def update_config(self, config: RoutingConfig) -> None:
        """Atomically swap routing config."""
        self._config = config

    def resolve(
        self,
        agent: str,
        task: str,
        tenant_id: str,
    ) -> RouteResolution:
        """Resolve a request to a specific tier and optionally a model.

        Args:
            agent: The agent making the request (e.g., 'agent-eval')
            task: The task name (e.g., 'evaluate_control')
            tenant_id: The tenant identifier

        Returns:
            RouteResolution with tier and optional model_config
        """
        # Level 1: Tenant-specific override (most specific)
        resolution = self._resolve_tenant(tenant_id, task)
        if resolution is not None:
            return resolution

        # Level 2: Agent-specific override
        resolution = self._resolve_agent(agent, task)
        if resolution is not None:
            return resolution

        # Level 3: Task default routing
        resolution = self._resolve_task(task)
        if resolution is not None:
            return resolution

        # Level 4: Default to mid tier
        logger.debug("route_using_default", agent=agent, task=task, tenant_id=tenant_id)
        return RouteResolution(tier=Tier.MID.value, source="default")

    def _resolve_tenant(self, tenant_id: str, task: str) -> RouteResolution | None:
        """Check tenant_routing for a match."""
        tenant_routes = self._config.tenant_routing.get(tenant_id)
        if tenant_routes is None:
            return None

        task_route = tenant_routes.get(task)
        if task_route is None:
            return None

        return self._interpret_route_value(task_route, source="tenant")

    def _resolve_agent(self, agent: str, task: str) -> RouteResolution | None:
        """Check agent_routing for a match."""
        agent_routes = self._config.agent_routing.get(agent)
        if agent_routes is None:
            return None

        task_route = agent_routes.get(task)
        if task_route is None:
            return None

        return self._interpret_route_value(task_route, source="agent")

    def _resolve_task(self, task: str) -> RouteResolution | None:
        """Check task_routing for a match."""
        tier_name = self._config.task_routing.get(task)
        if tier_name is None:
            return None

        return RouteResolution(tier=tier_name, source="task")

    def _interpret_route_value(
        self,
        value: Any,
        source: str,
    ) -> RouteResolution:
        """Interpret a routing value which can be a tier name (str) or a dict with model key."""
        if isinstance(value, str):
            # Value is a tier name (e.g., "fast", "mid", "strong")
            return RouteResolution(tier=value, source=source)

        if isinstance(value, dict):
            model_id = value.get("model")
            if model_id:
                # Find the model config by ID across all tiers
                model_config = self._find_model_by_id(model_id)
                tier = self._find_tier_for_model(model_id)
                return RouteResolution(
                    tier=tier,
                    model_config=model_config,
                    source=source,
                )
            # If dict but no model key, check for tier key
            tier = value.get("tier", Tier.MID.value)
            return RouteResolution(tier=tier, source=source)

        # Unknown format, default to mid
        return RouteResolution(tier=Tier.MID.value, source=source)

    def _find_model_by_id(self, model_id: str) -> ModelConfig | None:
        """Find a model config by its ID across all tiers."""
        for tier_config in self._config.tiers.values():
            for model in tier_config.models:
                if model.id == model_id:
                    return model
        logger.warning("model_not_found_in_tiers", model_id=model_id)
        return None

    def _find_tier_for_model(self, model_id: str) -> str:
        """Find which tier a model belongs to."""
        for tier_name, tier_config in self._config.tiers.items():
            for model in tier_config.models:
                if model.id == model_id:
                    return tier_name
        return Tier.MID.value

    def get_models_for_tier(self, tier: str) -> list[ModelConfig]:
        """Get all healthy, enabled models in a tier, ordered by priority."""
        tier_config = self._config.tiers.get(tier)
        if tier_config is None:
            return []
        return [m for m in tier_config.models if m.healthy and m.enabled]

    def get_next_tier(self, current_tier: str) -> str | None:
        """Get the next tier in the escalation path."""
        path = self._config.escalation.path
        try:
            idx = path.index(current_tier)
            if idx + 1 < len(path):
                return path[idx + 1]
        except ValueError:
            pass
        return None
