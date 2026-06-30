from __future__ import annotations

import json
import time
from typing import Any

import structlog
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

router = APIRouter(prefix="/v1/event", tags=["events"])

logger = structlog.get_logger(__name__)

MAX_EVENTS_PER_USER = 50


class EventPushBody(BaseModel):
    user_id: str
    tenant_id: str
    event_type: str
    summary: str
    priority: str = "medium"
    source_service: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class EventDrainBody(BaseModel):
    user_id: str
    tenant_id: str


def _redis_key(tenant_id: str, user_id: str) -> str:
    return f"event_queue:{tenant_id}:{user_id}"


@router.post("/push")
async def push_event(body: EventPushBody, request: Request) -> dict[str, str]:
    """Append an event to the user's queue. Evicts oldest low-priority if at cap."""
    redis = request.app.state.redis
    key = _redis_key(body.tenant_id, body.user_id)

    event = {
        "event_type": body.event_type,
        "summary": body.summary,
        "priority": body.priority,
        "source_service": body.source_service,
        "metadata": body.metadata,
        "timestamp": time.time(),
    }

    # Check current queue length
    current_len = await redis.llen(key)

    if current_len >= MAX_EVENTS_PER_USER:
        # Evict oldest low-priority event
        await _evict_lowest_priority(redis, key)

    await redis.rpush(key, json.dumps(event))
    logger.info(
        "event_pushed",
        user_id=body.user_id,
        tenant_id=body.tenant_id,
        event_type=body.event_type,
        priority=body.priority,
    )
    return {"status": "ok"}


@router.post("/drain")
async def drain_events(body: EventDrainBody, request: Request) -> dict[str, Any]:
    """Return all queued events and clear the queue."""
    redis = request.app.state.redis
    key = _redis_key(body.tenant_id, body.user_id)

    # Get all events
    raw_events = await redis.lrange(key, 0, -1)
    # Clear the queue
    await redis.delete(key)

    events = [json.loads(raw) for raw in raw_events]
    logger.info(
        "events_drained",
        user_id=body.user_id,
        tenant_id=body.tenant_id,
        count=len(events),
    )
    return {"events": events}


async def _evict_lowest_priority(redis: Any, key: str) -> None:
    """Evict the oldest low-priority event from the queue.

    Priority ranking: low < medium < high < critical.
    Scans from oldest (index 0) and removes the first low-priority event found.
    If no low-priority event exists, removes the oldest event regardless.
    """
    priority_rank = {"low": 0, "medium": 1, "high": 2, "critical": 3}

    raw_events = await redis.lrange(key, 0, -1)
    if not raw_events:
        return

    # Find oldest low-priority event
    for raw in raw_events:
        event = json.loads(raw)
        if priority_rank.get(event.get("priority", "medium"), 1) == 0:
            # Remove this specific element by value (removes first occurrence)
            await redis.lrem(key, 1, raw)
            return

    # No low-priority event found — evict the oldest event (leftmost)
    await redis.lpop(key)
