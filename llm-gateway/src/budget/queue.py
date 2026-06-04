from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections import deque
from typing import Any

import structlog

from src.models import CompletionRequest

logger = structlog.get_logger(__name__)


class QueuedRequest:
    """A request that has been queued due to budget exhaustion."""

    def __init__(
        self,
        request_id: str,
        tenant_id: str,
        request: CompletionRequest,
        queued_at: float,
    ) -> None:
        self.request_id = request_id
        self.tenant_id = tenant_id
        self.request = request
        self.queued_at = queued_at

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for Redis persistence."""
        return {
            "request_id": self.request_id,
            "tenant_id": self.tenant_id,
            "request": self.request.model_dump(),
            "queued_at": self.queued_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> QueuedRequest:
        """Deserialize from dict."""
        return cls(
            request_id=data["request_id"],
            tenant_id=data["tenant_id"],
            request=CompletionRequest.model_validate(data["request"]),
            queued_at=data["queued_at"],
        )


class RequestQueue:
    """Persistent request queue for budget-exhausted tenants.

    Queued requests never expire. They are processed automatically
    when the tenant's budget resets (daily). Uses Redis list for
    persistence, falls back to in-memory deque.
    """

    def __init__(self, redis_url: str = "redis://localhost:6379/0") -> None:
        self._redis_url = redis_url
        self._redis: Any = None
        self._memory_queues: dict[str, deque[QueuedRequest]] = {}

    async def connect(self) -> None:
        """Connect to Redis for persistent queue storage."""
        try:
            import redis.asyncio as aioredis

            self._redis = aioredis.from_url(
                self._redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
            await self._redis.ping()
            logger.info("request_queue_redis_connected")
        except Exception as exc:
            logger.warning(
                "request_queue_redis_unavailable_using_memory",
                error=str(exc),
            )
            self._redis = None

    async def close(self) -> None:
        """Close Redis connection."""
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None

    async def enqueue(self, request: CompletionRequest) -> str:
        """Add a request to the tenant's queue.

        Returns:
            The queue request ID for tracking.
        """
        request_id = str(uuid.uuid4())
        queued = QueuedRequest(
            request_id=request_id,
            tenant_id=request.tenant_id,
            request=request,
            queued_at=time.time(),
        )

        if self._redis is not None:
            await self._enqueue_redis(queued)
        else:
            self._enqueue_memory(queued)

        logger.info(
            "request_queued",
            request_id=request_id,
            tenant_id=request.tenant_id,
            task=request.task,
        )
        return request_id

    async def dequeue(self, tenant_id: str) -> QueuedRequest | None:
        """Pop the next queued request for a tenant (FIFO).

        Returns:
            The oldest queued request, or None if queue is empty.
        """
        if self._redis is not None:
            return await self._dequeue_redis(tenant_id)
        return self._dequeue_memory(tenant_id)

    async def peek(self, tenant_id: str, limit: int = 10) -> list[QueuedRequest]:
        """View queued requests without removing them."""
        if self._redis is not None:
            return await self._peek_redis(tenant_id, limit)
        return self._peek_memory(tenant_id, limit)

    async def queue_length(self, tenant_id: str) -> int:
        """Get the number of queued requests for a tenant."""
        if self._redis is not None:
            return await self._queue_length_redis(tenant_id)
        queue = self._memory_queues.get(tenant_id)
        return len(queue) if queue else 0

    # --- Redis implementations ---

    async def _enqueue_redis(self, queued: QueuedRequest) -> None:
        """Push request to Redis list."""
        key = self._queue_key(queued.tenant_id)
        data = json.dumps(queued.to_dict())
        await self._redis.rpush(key, data)

    async def _dequeue_redis(self, tenant_id: str) -> QueuedRequest | None:
        """Pop from Redis list (FIFO)."""
        key = self._queue_key(tenant_id)
        data = await self._redis.lpop(key)
        if data is None:
            return None
        return QueuedRequest.from_dict(json.loads(data))

    async def _peek_redis(self, tenant_id: str, limit: int) -> list[QueuedRequest]:
        """View items in Redis list without removing."""
        key = self._queue_key(tenant_id)
        items = await self._redis.lrange(key, 0, limit - 1)
        return [QueuedRequest.from_dict(json.loads(item)) for item in items]

    async def _queue_length_redis(self, tenant_id: str) -> int:
        """Get length of Redis list."""
        key = self._queue_key(tenant_id)
        return await self._redis.llen(key)

    # --- In-memory implementations ---

    def _enqueue_memory(self, queued: QueuedRequest) -> None:
        """Push to in-memory deque."""
        if queued.tenant_id not in self._memory_queues:
            self._memory_queues[queued.tenant_id] = deque()
        self._memory_queues[queued.tenant_id].append(queued)

    def _dequeue_memory(self, tenant_id: str) -> QueuedRequest | None:
        """Pop from in-memory deque."""
        queue = self._memory_queues.get(tenant_id)
        if not queue:
            return None
        return queue.popleft()

    def _peek_memory(self, tenant_id: str, limit: int) -> list[QueuedRequest]:
        """View items in memory deque."""
        queue = self._memory_queues.get(tenant_id)
        if not queue:
            return []
        return list(queue)[:limit]

    # --- Key helpers ---

    def _queue_key(self, tenant_id: str) -> str:
        """Redis key for tenant queue."""
        return f"queue:requests:{tenant_id}"
