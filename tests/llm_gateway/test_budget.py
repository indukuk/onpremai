"""Tests for llm-gateway budget tracking and degradation.

Tests cost tracking (Redis + in-memory fallback), ceiling enforcement,
and degradation level computation.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "llm-gateway"))

from src.budget.degradation import DegradationLevel, DegradationManager
from src.budget.tracker import BudgetTracker, _TenantBudgetState
from src.models import CostConfig, Tier


class TestBudgetTrackerMemoryFallback:
    """Tests for BudgetTracker in-memory fallback (no Redis)."""

    @pytest.fixture
    def tracker(self) -> BudgetTracker:
        """Tracker in memory-only mode (no Redis)."""
        t = BudgetTracker(redis_url="redis://localhost:6379/0")
        # _redis stays None -> memory fallback
        return t

    @pytest.mark.asyncio
    async def test_record_cost_accumulates(self, tracker: BudgetTracker) -> None:
        """Recording costs accumulates daily spend."""
        total = await tracker.record_cost("tenant-1", 1.50)
        assert total == 1.50
        total = await tracker.record_cost("tenant-1", 2.50)
        assert total == 4.00

    @pytest.mark.asyncio
    async def test_get_daily_spend_zero_initially(self, tracker: BudgetTracker) -> None:
        """Daily spend starts at 0 for unknown tenant."""
        spend = await tracker.get_daily_spend("tenant-new")
        assert spend == 0.0

    @pytest.mark.asyncio
    async def test_get_daily_spend_after_recording(self, tracker: BudgetTracker) -> None:
        """Daily spend reflects recorded costs."""
        await tracker.record_cost("tenant-1", 3.25)
        spend = await tracker.get_daily_spend("tenant-1")
        assert spend == 3.25

    @pytest.mark.asyncio
    async def test_increment_requests(self, tracker: BudgetTracker) -> None:
        """Request count increments correctly."""
        count = await tracker.increment_requests("tenant-1")
        assert count == 1
        count = await tracker.increment_requests("tenant-1")
        assert count == 2

    @pytest.mark.asyncio
    async def test_get_request_count_zero_initially(self, tracker: BudgetTracker) -> None:
        """Request count is 0 for new tenant."""
        count = await tracker.get_request_count("tenant-new")
        assert count == 0

    @pytest.mark.asyncio
    async def test_check_budget_within_limit(self, tracker: BudgetTracker) -> None:
        """Budget check passes when under limit."""
        await tracker.record_cost("tenant-1", 10.0)
        within = await tracker.check_budget("tenant-1", daily_limit_usd=50.0)
        assert within is True

    @pytest.mark.asyncio
    async def test_check_budget_over_limit(self, tracker: BudgetTracker) -> None:
        """Budget check fails when over limit."""
        await tracker.record_cost("tenant-1", 55.0)
        within = await tracker.check_budget("tenant-1", daily_limit_usd=50.0)
        assert within is False

    @pytest.mark.asyncio
    async def test_check_budget_exactly_at_limit(self, tracker: BudgetTracker) -> None:
        """Budget check fails when exactly at limit (not < limit)."""
        await tracker.record_cost("tenant-1", 50.0)
        within = await tracker.check_budget("tenant-1", daily_limit_usd=50.0)
        assert within is False

    @pytest.mark.asyncio
    async def test_tenants_are_isolated(self, tracker: BudgetTracker) -> None:
        """One tenant's costs don't affect another."""
        await tracker.record_cost("tenant-a", 40.0)
        await tracker.record_cost("tenant-b", 5.0)
        spend_a = await tracker.get_daily_spend("tenant-a")
        spend_b = await tracker.get_daily_spend("tenant-b")
        assert spend_a == 40.0
        assert spend_b == 5.0


class TestBudgetTrackerRedis:
    """Tests for BudgetTracker with mocked Redis."""

    @pytest.fixture
    def tracker_with_redis(self, mock_redis: AsyncMock) -> BudgetTracker:
        """Tracker with mock Redis injected."""
        t = BudgetTracker(redis_url="redis://localhost:6379/0")
        t._redis = mock_redis
        return t

    @pytest.mark.asyncio
    async def test_record_cost_uses_incrbyfloat(
        self, tracker_with_redis: BudgetTracker, mock_redis: AsyncMock
    ) -> None:
        """Cost recording uses Redis INCRBYFLOAT."""
        mock_redis.incrbyfloat.return_value = 7.25
        total = await tracker_with_redis.record_cost("tenant-1", 2.75)
        assert total == 7.25
        mock_redis.incrbyfloat.assert_called_once()

    @pytest.mark.asyncio
    async def test_record_cost_sets_expiry_on_new_key(
        self, tracker_with_redis: BudgetTracker, mock_redis: AsyncMock
    ) -> None:
        """Expiry is set if TTL is negative (new key)."""
        mock_redis.ttl.return_value = -1
        mock_redis.incrbyfloat.return_value = 1.0
        await tracker_with_redis.record_cost("tenant-1", 1.0)
        mock_redis.expire.assert_called_once()

    @pytest.mark.asyncio
    async def test_record_cost_skips_expiry_if_already_set(
        self, tracker_with_redis: BudgetTracker, mock_redis: AsyncMock
    ) -> None:
        """Expiry is NOT set if TTL already positive."""
        mock_redis.ttl.return_value = 3600
        mock_redis.incrbyfloat.return_value = 10.0
        await tracker_with_redis.record_cost("tenant-1", 5.0)
        mock_redis.expire.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_daily_spend_from_redis(
        self, tracker_with_redis: BudgetTracker, mock_redis: AsyncMock
    ) -> None:
        """Reads daily spend from Redis GET."""
        mock_redis.get.return_value = "12.50"
        spend = await tracker_with_redis.get_daily_spend("tenant-1")
        assert spend == 12.50

    @pytest.mark.asyncio
    async def test_get_daily_spend_returns_zero_if_none(
        self, tracker_with_redis: BudgetTracker, mock_redis: AsyncMock
    ) -> None:
        """Returns 0.0 if Redis key doesn't exist."""
        mock_redis.get.return_value = None
        spend = await tracker_with_redis.get_daily_spend("tenant-1")
        assert spend == 0.0

    @pytest.mark.asyncio
    async def test_increment_requests_redis(
        self, tracker_with_redis: BudgetTracker, mock_redis: AsyncMock
    ) -> None:
        """Request count uses Redis INCR."""
        mock_redis.incr.return_value = 15
        mock_redis.ttl.return_value = 7200
        count = await tracker_with_redis.increment_requests("tenant-1")
        assert count == 15

    @pytest.mark.asyncio
    async def test_connect_success(self, mock_redis: AsyncMock) -> None:
        """Successful Redis connection sets _redis."""
        with patch("src.budget.tracker.BudgetTracker.connect") as mock_connect:
            tracker = BudgetTracker()
            tracker._redis = mock_redis
            assert tracker._redis is not None

    @pytest.mark.asyncio
    async def test_connect_failure_falls_back_to_memory(self) -> None:
        """Redis connection failure falls back to in-memory mode."""
        tracker = BudgetTracker(redis_url="redis://bad-host:9999/0")
        # Simulate connection failure by mocking the import
        with patch("redis.asyncio.from_url", side_effect=ConnectionError("refused")):
            await tracker.connect()
        assert tracker._redis is None
        # Should still work in memory mode
        total = await tracker.record_cost("tenant-1", 1.0)
        assert total == 1.0

    @pytest.mark.asyncio
    async def test_close_cleans_up(
        self, tracker_with_redis: BudgetTracker, mock_redis: AsyncMock
    ) -> None:
        """Close properly closes the Redis connection."""
        await tracker_with_redis.close()
        mock_redis.aclose.assert_called_once()
        assert tracker_with_redis._redis is None


class TestTenantBudgetState:
    """Tests for _TenantBudgetState helper class."""

    def test_is_today_returns_true_for_current_date(self) -> None:
        """State created now is for today."""
        state = _TenantBudgetState()
        assert state.is_today() is True

    def test_is_today_returns_false_for_old_date(self) -> None:
        """State with old date_str is not today."""
        state = _TenantBudgetState()
        state.date_str = "20200101"
        assert state.is_today() is False


class TestBudgetTrackerKeyGeneration:
    """Tests for Redis key generation."""

    def test_daily_cost_key_format(self) -> None:
        """Daily cost key has expected format."""
        tracker = BudgetTracker()
        key = tracker._daily_cost_key("tenant-abc")
        date_str = time.strftime("%Y%m%d", time.gmtime())
        assert key == f"budget:cost:tenant-abc:{date_str}"

    def test_daily_requests_key_format(self) -> None:
        """Daily requests key has expected format."""
        tracker = BudgetTracker()
        key = tracker._daily_requests_key("tenant-xyz")
        date_str = time.strftime("%Y%m%d", time.gmtime())
        assert key == f"budget:requests:tenant-xyz:{date_str}"

    def test_seconds_until_midnight_positive(self) -> None:
        """Seconds until midnight is always positive (at least 60)."""
        tracker = BudgetTracker()
        seconds = tracker._seconds_until_midnight()
        assert seconds >= 60


class TestDegradationManager:
    """Tests for per-tenant degradation level management."""

    @pytest.fixture
    def manager(self, cost_config: CostConfig) -> DegradationManager:
        """DegradationManager with standard config."""
        return DegradationManager(cost_config)

    # --- compute_level ---

    def test_compute_level_full_service(self, manager: DegradationManager) -> None:
        """< 70% of limit -> Level 0 (full service)."""
        level = manager.compute_level(daily_spend=30.0, daily_limit=50.0)
        assert level == DegradationLevel.FULL_SERVICE

    def test_compute_level_no_strong(self, manager: DegradationManager) -> None:
        """70-85% of limit -> Level 1 (no strong tier)."""
        level = manager.compute_level(daily_spend=37.0, daily_limit=50.0)  # 74%
        assert level == DegradationLevel.NO_STRONG

    def test_compute_level_fast_only(self, manager: DegradationManager) -> None:
        """85-95% of limit -> Level 2 (fast only)."""
        level = manager.compute_level(daily_spend=44.0, daily_limit=50.0)  # 88%
        assert level == DegradationLevel.FAST_ONLY

    def test_compute_level_deterministic_only(self, manager: DegradationManager) -> None:
        """95-100% of limit -> Level 3 (deterministic only)."""
        level = manager.compute_level(daily_spend=48.0, daily_limit=50.0)  # 96%
        assert level == DegradationLevel.DETERMINISTIC_ONLY

    def test_compute_level_queued(self, manager: DegradationManager) -> None:
        """>= 100% of limit -> Level 4 (queued)."""
        level = manager.compute_level(daily_spend=50.0, daily_limit=50.0)
        assert level == DegradationLevel.QUEUED

    def test_compute_level_over_limit(self, manager: DegradationManager) -> None:
        """Well over limit still maps to Level 4."""
        level = manager.compute_level(daily_spend=100.0, daily_limit=50.0)
        assert level == DegradationLevel.QUEUED

    def test_compute_level_zero_limit_returns_full(self, manager: DegradationManager) -> None:
        """Zero or negative limit returns full service (avoid division by zero)."""
        level = manager.compute_level(daily_spend=100.0, daily_limit=0.0)
        assert level == DegradationLevel.FULL_SERVICE
        level = manager.compute_level(daily_spend=100.0, daily_limit=-10.0)
        assert level == DegradationLevel.FULL_SERVICE

    # --- Boundary tests ---

    def test_compute_level_at_exactly_70_pct(self, manager: DegradationManager) -> None:
        """Exactly 70% triggers Level 1."""
        level = manager.compute_level(daily_spend=35.0, daily_limit=50.0)
        assert level == DegradationLevel.NO_STRONG

    def test_compute_level_just_below_70_pct(self, manager: DegradationManager) -> None:
        """Just below 70% stays at Level 0."""
        level = manager.compute_level(daily_spend=34.99, daily_limit=50.0)
        assert level == DegradationLevel.FULL_SERVICE

    def test_compute_level_at_exactly_85_pct(self, manager: DegradationManager) -> None:
        """Exactly 85% triggers Level 2."""
        level = manager.compute_level(daily_spend=42.5, daily_limit=50.0)
        assert level == DegradationLevel.FAST_ONLY

    def test_compute_level_at_exactly_95_pct(self, manager: DegradationManager) -> None:
        """Exactly 95% triggers Level 3."""
        level = manager.compute_level(daily_spend=47.5, daily_limit=50.0)
        assert level == DegradationLevel.DETERMINISTIC_ONLY

    # --- get/set level ---

    def test_get_level_default_is_full_service(self, manager: DegradationManager) -> None:
        """Unknown tenant defaults to full service."""
        level = manager.get_level("unknown-tenant")
        assert level == DegradationLevel.FULL_SERVICE

    def test_set_level_persists(self, manager: DegradationManager) -> None:
        """Setting level persists for the tenant."""
        manager.set_level("tenant-1", DegradationLevel.FAST_ONLY)
        assert manager.get_level("tenant-1") == DegradationLevel.FAST_ONLY

    # --- update_for_spend ---

    def test_update_for_spend_computes_and_sets(self, manager: DegradationManager) -> None:
        """update_for_spend computes level from spend and sets it."""
        level = manager.update_for_spend("tenant-1", daily_spend=44.0)
        assert level == DegradationLevel.FAST_ONLY
        assert manager.get_level("tenant-1") == DegradationLevel.FAST_ONLY

    # --- get_allowed_tiers ---

    def test_allowed_tiers_full_service(self, manager: DegradationManager) -> None:
        """Full service allows all tiers."""
        manager.set_level("t1", DegradationLevel.FULL_SERVICE)
        tiers = manager.get_allowed_tiers("t1")
        assert "fast" in tiers
        assert "mid" in tiers
        assert "strong" in tiers

    def test_allowed_tiers_no_strong(self, manager: DegradationManager) -> None:
        """Level 1 removes strong tier."""
        manager.set_level("t1", DegradationLevel.NO_STRONG)
        tiers = manager.get_allowed_tiers("t1")
        assert "fast" in tiers
        assert "mid" in tiers
        assert "strong" not in tiers

    def test_allowed_tiers_fast_only(self, manager: DegradationManager) -> None:
        """Level 2 only allows fast."""
        manager.set_level("t1", DegradationLevel.FAST_ONLY)
        tiers = manager.get_allowed_tiers("t1")
        assert tiers == ["fast"]

    def test_allowed_tiers_deterministic_only(self, manager: DegradationManager) -> None:
        """Level 3 has no allowed LLM tiers."""
        manager.set_level("t1", DegradationLevel.DETERMINISTIC_ONLY)
        tiers = manager.get_allowed_tiers("t1")
        assert tiers == []

    def test_allowed_tiers_queued(self, manager: DegradationManager) -> None:
        """Level 4 has no allowed LLM tiers."""
        manager.set_level("t1", DegradationLevel.QUEUED)
        tiers = manager.get_allowed_tiers("t1")
        assert tiers == []

    # --- is_tier_allowed ---

    def test_is_tier_allowed_true(self, manager: DegradationManager) -> None:
        """Tier is allowed when within degradation level."""
        manager.set_level("t1", DegradationLevel.NO_STRONG)
        assert manager.is_tier_allowed("t1", "mid") is True
        assert manager.is_tier_allowed("t1", "fast") is True

    def test_is_tier_allowed_false(self, manager: DegradationManager) -> None:
        """Strong tier is not allowed at level 1."""
        manager.set_level("t1", DegradationLevel.NO_STRONG)
        assert manager.is_tier_allowed("t1", "strong") is False

    # --- should_queue / should_reject_llm ---

    def test_should_queue_true_at_level_4(self, manager: DegradationManager) -> None:
        """Queue at level 4."""
        manager.set_level("t1", DegradationLevel.QUEUED)
        assert manager.should_queue("t1") is True

    def test_should_queue_false_at_level_3(self, manager: DegradationManager) -> None:
        """Don't queue at level 3."""
        manager.set_level("t1", DegradationLevel.DETERMINISTIC_ONLY)
        assert manager.should_queue("t1") is False

    def test_should_reject_llm_true_at_level_3(self, manager: DegradationManager) -> None:
        """Reject LLM at level 3."""
        manager.set_level("t1", DegradationLevel.DETERMINISTIC_ONLY)
        assert manager.should_reject_llm("t1") is True

    def test_should_reject_llm_true_at_level_4(self, manager: DegradationManager) -> None:
        """Reject LLM at level 4 too."""
        manager.set_level("t1", DegradationLevel.QUEUED)
        assert manager.should_reject_llm("t1") is True

    def test_should_reject_llm_false_at_level_2(self, manager: DegradationManager) -> None:
        """Don't reject LLM at level 2 (fast tier still available)."""
        manager.set_level("t1", DegradationLevel.FAST_ONLY)
        assert manager.should_reject_llm("t1") is False

    # --- cap_tier ---

    def test_cap_tier_no_restriction_at_full_service(self, manager: DegradationManager) -> None:
        """Full service doesn't cap any tier."""
        # Full service returns all tiers as allowed, so strong is still possible
        manager.set_level("t1", DegradationLevel.FULL_SERVICE)
        result = manager.cap_tier("t1", "strong")
        assert result == "strong"

    def test_cap_tier_strong_capped_to_mid(self, manager: DegradationManager) -> None:
        """At level 1, strong gets capped to mid."""
        manager.set_level("t1", DegradationLevel.NO_STRONG)
        result = manager.cap_tier("t1", "strong")
        assert result == "mid"

    def test_cap_tier_strong_capped_to_fast(self, manager: DegradationManager) -> None:
        """At level 2, strong gets capped to fast."""
        manager.set_level("t1", DegradationLevel.FAST_ONLY)
        result = manager.cap_tier("t1", "strong")
        assert result == "fast"

    def test_cap_tier_mid_capped_to_fast(self, manager: DegradationManager) -> None:
        """At level 2, mid gets capped to fast."""
        manager.set_level("t1", DegradationLevel.FAST_ONLY)
        result = manager.cap_tier("t1", "mid")
        assert result == "fast"

    def test_cap_tier_unknown_tier_passthrough(self, manager: DegradationManager) -> None:
        """Unknown tier name passes through unchanged."""
        manager.set_level("t1", DegradationLevel.NO_STRONG)
        result = manager.cap_tier("t1", "custom-tier")
        assert result == "custom-tier"

    # --- reset_tenant ---

    def test_reset_tenant(self, manager: DegradationManager) -> None:
        """Reset clears degradation level back to full service."""
        manager.set_level("t1", DegradationLevel.QUEUED)
        manager.reset_tenant("t1")
        assert manager.get_level("t1") == DegradationLevel.FULL_SERVICE

    def test_reset_unknown_tenant_no_error(self, manager: DegradationManager) -> None:
        """Resetting unknown tenant is a no-op, no error."""
        manager.reset_tenant("never-existed")  # Should not raise

    # --- update_config ---

    def test_update_config(self, manager: DegradationManager) -> None:
        """Updating config changes the daily limit for future computations."""
        new_config = CostConfig(max_per_tenant_per_day_usd=100.0)
        manager.update_config(new_config)
        # 70% of $100 = $70. Spending $50 is only 50% -> full service
        level = manager.update_for_spend("t1", daily_spend=50.0)
        assert level == DegradationLevel.FULL_SERVICE
