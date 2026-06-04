from __future__ import annotations

import time
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class BudgetTracker:
    """Per-tenant cost accumulator backed by Redis.

    Tracks daily spend per tenant using Redis INCR operations.
    Keys expire at end of day UTC to auto-reset counters.

    Falls back to in-memory tracking when Redis is unavailable.
    """

    def __init__(self, redis_url: str = "redis://localhost:6379/0") -> None:
        self._redis_url = redis_url
        self._redis: Any = None
        self._fallback: dict[str, _TenantBudgetState] = {}

    async def connect(self) -> None:
        """Connect to Redis. Falls back to in-memory on failure."""
        try:
            import redis.asyncio as aioredis

            self._redis = aioredis.from_url(
                self._redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
            await self._redis.ping()
            logger.info("budget_tracker_redis_connected", url=self._redis_url)
        except Exception as exc:
            logger.warning(
                "budget_tracker_redis_unavailable_using_memory",
                error=str(exc),
            )
            self._redis = None

    async def close(self) -> None:
        """Close Redis connection."""
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None

    async def record_cost(self, tenant_id: str, cost_usd: float) -> float:
        """Record cost for a tenant. Returns new daily total.

        Args:
            tenant_id: The tenant being charged.
            cost_usd: Cost in USD to add.

        Returns:
            Updated daily total spend for this tenant.
        """
        if self._redis is not None:
            return await self._record_cost_redis(tenant_id, cost_usd)
        return self._record_cost_memory(tenant_id, cost_usd)

    async def get_daily_spend(self, tenant_id: str) -> float:
        """Get current daily spend for a tenant."""
        if self._redis is not None:
            return await self._get_daily_spend_redis(tenant_id)
        return self._get_daily_spend_memory(tenant_id)

    async def get_request_count(self, tenant_id: str) -> int:
        """Get today's request count for a tenant."""
        if self._redis is not None:
            return await self._get_request_count_redis(tenant_id)
        state = self._fallback.get(tenant_id)
        if state is None or not state.is_today():
            return 0
        return state.request_count

    async def increment_requests(self, tenant_id: str) -> int:
        """Increment and return the request count for today."""
        if self._redis is not None:
            return await self._increment_requests_redis(tenant_id)
        return self._increment_requests_memory(tenant_id)

    async def check_budget(self, tenant_id: str, daily_limit_usd: float) -> bool:
        """Check if tenant is within budget.

        Returns:
            True if tenant can make requests, False if budget exhausted.
        """
        daily_spend = await self.get_daily_spend(tenant_id)
        return daily_spend < daily_limit_usd

    # --- Redis implementations ---

    async def _record_cost_redis(self, tenant_id: str, cost_usd: float) -> float:
        """Record cost in Redis using INCRBYFLOAT."""
        key = self._daily_cost_key(tenant_id)
        new_total = await self._redis.incrbyfloat(key, cost_usd)
        # Set expiry to end of day (max 24h)
        ttl = await self._redis.ttl(key)
        if ttl < 0:
            await self._redis.expire(key, self._seconds_until_midnight())
        return float(new_total)

    async def _get_daily_spend_redis(self, tenant_id: str) -> float:
        """Get daily spend from Redis."""
        key = self._daily_cost_key(tenant_id)
        value = await self._redis.get(key)
        if value is None:
            return 0.0
        return float(value)

    async def _get_request_count_redis(self, tenant_id: str) -> int:
        """Get request count from Redis."""
        key = self._daily_requests_key(tenant_id)
        value = await self._redis.get(key)
        if value is None:
            return 0
        return int(value)

    async def _increment_requests_redis(self, tenant_id: str) -> int:
        """Increment request count in Redis."""
        key = self._daily_requests_key(tenant_id)
        new_count = await self._redis.incr(key)
        ttl = await self._redis.ttl(key)
        if ttl < 0:
            await self._redis.expire(key, self._seconds_until_midnight())
        return int(new_count)

    # --- In-memory fallback implementations ---

    def _record_cost_memory(self, tenant_id: str, cost_usd: float) -> float:
        """Record cost in memory fallback."""
        state = self._get_or_create_state(tenant_id)
        state.daily_spend += cost_usd
        return state.daily_spend

    def _get_daily_spend_memory(self, tenant_id: str) -> float:
        """Get daily spend from memory."""
        state = self._fallback.get(tenant_id)
        if state is None or not state.is_today():
            return 0.0
        return state.daily_spend

    def _increment_requests_memory(self, tenant_id: str) -> int:
        """Increment request count in memory."""
        state = self._get_or_create_state(tenant_id)
        state.request_count += 1
        return state.request_count

    def _get_or_create_state(self, tenant_id: str) -> _TenantBudgetState:
        """Get or create in-memory state, resetting if new day."""
        state = self._fallback.get(tenant_id)
        if state is None or not state.is_today():
            state = _TenantBudgetState()
            self._fallback[tenant_id] = state
        return state

    # --- Key helpers ---

    def _daily_cost_key(self, tenant_id: str) -> str:
        """Redis key for daily cost: budget:cost:{tenant}:{date}."""
        date_str = time.strftime("%Y%m%d", time.gmtime())
        return f"budget:cost:{tenant_id}:{date_str}"

    def _daily_requests_key(self, tenant_id: str) -> str:
        """Redis key for daily request count."""
        date_str = time.strftime("%Y%m%d", time.gmtime())
        return f"budget:requests:{tenant_id}:{date_str}"

    def _seconds_until_midnight(self) -> int:
        """Seconds until next UTC midnight."""
        now = time.time()
        midnight = (int(now) // 86400 + 1) * 86400
        return max(midnight - int(now), 60)


class _TenantBudgetState:
    """In-memory budget state for one tenant (one day)."""

    __slots__ = ("daily_spend", "request_count", "date_str")

    def __init__(self) -> None:
        self.daily_spend: float = 0.0
        self.request_count: int = 0
        self.date_str: str = time.strftime("%Y%m%d", time.gmtime())

    def is_today(self) -> bool:
        """Check if this state is for today."""
        return self.date_str == time.strftime("%Y%m%d", time.gmtime())
