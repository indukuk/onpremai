from __future__ import annotations

import structlog

from src.models import CostConfig, Tier

logger = structlog.get_logger(__name__)


class DegradationLevel:
    """Constants for degradation levels.

    Level 0: Full service (all tiers available)
    Level 1: Strong tier gone -> cap at mid
    Level 2: Mid tier gone -> fast only
    Level 3: All LLM gone -> deterministic-only (rules engine)
    Level 4: Monthly cap hit -> queue indefinitely
    """

    FULL_SERVICE = 0
    NO_STRONG = 1
    FAST_ONLY = 2
    DETERMINISTIC_ONLY = 3
    QUEUED = 4


class DegradationManager:
    """Manages per-tenant degradation levels based on budget consumption.

    Implements the credit exhaustion cascade:
    - Level 0: Full service (all tiers)
    - Level 1: Strong gone -> cap at mid (complex reasoning downgrades)
    - Level 2: Mid gone -> fast only (rules + cheap LLM for high-priority items)
    - Level 3: All LLM gone -> deterministic-only (rules still resolve 60-70%)
    - Level 4: Monthly cap -> queue indefinitely, process when budget resets
    """

    def __init__(self, cost_config: CostConfig) -> None:
        self._cost_config = cost_config
        self._tenant_levels: dict[str, int] = {}

    def update_config(self, cost_config: CostConfig) -> None:
        """Update cost configuration."""
        self._cost_config = cost_config

    def compute_level(self, daily_spend: float, daily_limit: float) -> int:
        """Compute degradation level based on spend ratio.

        Uses threshold-based escalation:
        - < 70% of limit: Level 0 (full service)
        - 70-85% of limit: Level 1 (no strong tier)
        - 85-95% of limit: Level 2 (fast only)
        - 95-100% of limit: Level 3 (deterministic only)
        - >= 100% of limit: Level 4 (queue indefinitely)
        """
        if daily_limit <= 0:
            return DegradationLevel.FULL_SERVICE

        ratio = daily_spend / daily_limit

        if ratio >= 1.0:
            return DegradationLevel.QUEUED
        if ratio >= 0.95:
            return DegradationLevel.DETERMINISTIC_ONLY
        if ratio >= 0.85:
            return DegradationLevel.FAST_ONLY
        if ratio >= 0.70:
            return DegradationLevel.NO_STRONG
        return DegradationLevel.FULL_SERVICE

    def get_level(self, tenant_id: str) -> int:
        """Get current degradation level for a tenant."""
        return self._tenant_levels.get(tenant_id, DegradationLevel.FULL_SERVICE)

    def set_level(self, tenant_id: str, level: int) -> None:
        """Explicitly set degradation level for a tenant."""
        previous = self._tenant_levels.get(tenant_id, DegradationLevel.FULL_SERVICE)
        self._tenant_levels[tenant_id] = level
        if level != previous:
            logger.warning(
                "degradation_level_changed",
                tenant_id=tenant_id,
                previous_level=previous,
                new_level=level,
            )

    def update_for_spend(self, tenant_id: str, daily_spend: float) -> int:
        """Recompute and update degradation level based on current spend.

        Returns:
            The new degradation level.
        """
        daily_limit = self._cost_config.max_per_tenant_per_day_usd
        level = self.compute_level(daily_spend, daily_limit)
        self.set_level(tenant_id, level)
        return level

    def get_allowed_tiers(self, tenant_id: str) -> list[str]:
        """Get list of tiers a tenant can access at current degradation level."""
        level = self.get_level(tenant_id)
        return self._tiers_for_level(level)

    def is_tier_allowed(self, tenant_id: str, tier: str) -> bool:
        """Check if a specific tier is allowed for this tenant."""
        allowed = self.get_allowed_tiers(tenant_id)
        return tier in allowed

    def should_queue(self, tenant_id: str) -> bool:
        """Check if requests for this tenant should be queued."""
        return self.get_level(tenant_id) >= DegradationLevel.QUEUED

    def should_reject_llm(self, tenant_id: str) -> bool:
        """Check if LLM calls should be rejected (deterministic-only mode)."""
        return self.get_level(tenant_id) >= DegradationLevel.DETERMINISTIC_ONLY

    def cap_tier(self, tenant_id: str, requested_tier: str) -> str:
        """Cap the requested tier based on degradation level.

        Returns the highest allowed tier that doesn't exceed the limit.
        """
        level = self.get_level(tenant_id)
        allowed = self._tiers_for_level(level)

        if not allowed:
            return requested_tier  # no restriction at level 0

        # Tier priority: strong > mid > fast
        tier_priority = [Tier.STRONG.value, Tier.MID.value, Tier.FAST.value]

        # Find the position of requested tier
        if requested_tier not in tier_priority:
            return requested_tier

        req_idx = tier_priority.index(requested_tier)

        # Find the highest allowed tier
        for idx in range(req_idx, len(tier_priority)):
            if tier_priority[idx] in allowed:
                return tier_priority[idx]

        # If none found, return the best available
        return allowed[0] if allowed else requested_tier

    def _tiers_for_level(self, level: int) -> list[str]:
        """Get allowed tiers for a degradation level."""
        if level == DegradationLevel.FULL_SERVICE:
            return [Tier.FAST.value, Tier.MID.value, Tier.STRONG.value]
        if level == DegradationLevel.NO_STRONG:
            return [Tier.FAST.value, Tier.MID.value]
        if level == DegradationLevel.FAST_ONLY:
            return [Tier.FAST.value]
        # Levels 3 and 4 have no allowed LLM tiers
        return []

    def reset_tenant(self, tenant_id: str) -> None:
        """Reset a tenant back to full service (e.g., on budget reset)."""
        if tenant_id in self._tenant_levels:
            del self._tenant_levels[tenant_id]
            logger.info("degradation_level_reset", tenant_id=tenant_id)
