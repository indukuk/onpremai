"""Tests for event routes: push and drain."""
from __future__ import annotations

import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../memory-service"))

from httpx import ASGITransport, AsyncClient
from fastapi import FastAPI

from src.routes.events import router, MAX_EVENTS_PER_USER


# ---------------------------------------------------------------------------
# App + Redis fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_redis() -> AsyncMock:
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock(return_value=True)
    redis.rpush = AsyncMock(return_value=1)
    redis.llen = AsyncMock(return_value=0)
    redis.lrange = AsyncMock(return_value=[])
    redis.lrem = AsyncMock(return_value=1)
    redis.lpop = AsyncMock(return_value=None)
    redis.delete = AsyncMock(return_value=1)
    return redis


@pytest.fixture
def app(mock_redis: AsyncMock) -> FastAPI:
    """Minimal FastAPI app with events router mounted."""
    _app = FastAPI()
    _app.state.redis = mock_redis
    _app.include_router(router)
    return _app


@pytest.fixture
def client(app: FastAPI) -> AsyncClient:
    """HTTPX async test client."""
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


# ---------------------------------------------------------------------------
# POST /v1/event/push
# ---------------------------------------------------------------------------


class TestPushEvent:
    @pytest.mark.asyncio
    async def test_push_appends_event(self, client: AsyncClient, mock_redis: AsyncMock):
        """Push appends an event to the Redis list."""
        mock_redis.llen.return_value = 5

        response = await client.post(
            "/v1/event/push",
            json={
                "user_id": "user-001",
                "tenant_id": "tenant-alpha",
                "event_type": "control_updated",
                "summary": "Control CC6.1 was updated",
                "priority": "high",
                "source_service": "agent-eval",
                "metadata": {"control_id": "CC6.1"},
            },
        )

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        mock_redis.rpush.assert_awaited_once()

        # Verify the event payload
        call_args = mock_redis.rpush.call_args
        key = call_args[0][0]
        payload = json.loads(call_args[0][1])
        assert key == "event_queue:tenant-alpha:user-001"
        assert payload["event_type"] == "control_updated"
        assert payload["summary"] == "Control CC6.1 was updated"
        assert payload["priority"] == "high"
        assert payload["source_service"] == "agent-eval"
        assert payload["metadata"] == {"control_id": "CC6.1"}
        assert "timestamp" in payload

    @pytest.mark.asyncio
    async def test_push_default_priority(self, client: AsyncClient, mock_redis: AsyncMock):
        """Default priority is medium."""
        mock_redis.llen.return_value = 0

        response = await client.post(
            "/v1/event/push",
            json={
                "user_id": "user-001",
                "tenant_id": "tenant-alpha",
                "event_type": "notification",
                "summary": "Something happened",
            },
        )

        assert response.status_code == 200
        call_args = mock_redis.rpush.call_args
        payload = json.loads(call_args[0][1])
        assert payload["priority"] == "medium"

    @pytest.mark.asyncio
    async def test_push_evicts_low_priority_when_at_cap(self, client: AsyncClient, mock_redis: AsyncMock):
        """When at MAX_EVENTS_PER_USER, evicts oldest low-priority event."""
        mock_redis.llen.return_value = MAX_EVENTS_PER_USER

        # Simulate existing queue with a low-priority event
        low_event = json.dumps({"event_type": "old", "priority": "low", "timestamp": 1.0})
        mock_redis.lrange.return_value = [
            json.dumps({"event_type": "high_one", "priority": "high", "timestamp": 2.0}),
            low_event,
            json.dumps({"event_type": "medium_one", "priority": "medium", "timestamp": 3.0}),
        ]

        response = await client.post(
            "/v1/event/push",
            json={
                "user_id": "user-001",
                "tenant_id": "tenant-alpha",
                "event_type": "new_event",
                "summary": "New important event",
                "priority": "high",
            },
        )

        assert response.status_code == 200
        # Should have removed the low-priority event
        mock_redis.lrem.assert_awaited_once_with(
            "event_queue:tenant-alpha:user-001", 1, low_event
        )

    @pytest.mark.asyncio
    async def test_push_evicts_oldest_when_no_low_priority(self, client: AsyncClient, mock_redis: AsyncMock):
        """When at cap with no low-priority events, evicts the oldest."""
        mock_redis.llen.return_value = MAX_EVENTS_PER_USER

        # All events are high priority
        mock_redis.lrange.return_value = [
            json.dumps({"event_type": "e1", "priority": "high", "timestamp": 1.0}),
            json.dumps({"event_type": "e2", "priority": "high", "timestamp": 2.0}),
        ]

        response = await client.post(
            "/v1/event/push",
            json={
                "user_id": "user-001",
                "tenant_id": "tenant-alpha",
                "event_type": "new_event",
                "summary": "New event",
                "priority": "high",
            },
        )

        assert response.status_code == 200
        # Should have popped the oldest (leftmost)
        mock_redis.lpop.assert_awaited_once_with("event_queue:tenant-alpha:user-001")

    @pytest.mark.asyncio
    async def test_push_requires_event_type(self, client: AsyncClient):
        """Missing event_type returns 422."""
        response = await client.post(
            "/v1/event/push",
            json={
                "user_id": "user-001",
                "tenant_id": "tenant-alpha",
                "summary": "Something",
            },
        )
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# POST /v1/event/drain
# ---------------------------------------------------------------------------


class TestDrainEvents:
    @pytest.mark.asyncio
    async def test_drain_returns_all_events_and_clears(self, client: AsyncClient, mock_redis: AsyncMock):
        """Drain returns all events and deletes the key."""
        events = [
            {"event_type": "e1", "summary": "First", "priority": "high", "timestamp": 1.0,
             "source_service": "svc1", "metadata": {}},
            {"event_type": "e2", "summary": "Second", "priority": "low", "timestamp": 2.0,
             "source_service": "svc2", "metadata": {"key": "val"}},
        ]
        mock_redis.lrange.return_value = [json.dumps(e) for e in events]

        response = await client.post(
            "/v1/event/drain",
            json={"user_id": "user-001", "tenant_id": "tenant-alpha"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["events"] == events
        mock_redis.lrange.assert_awaited_once_with("event_queue:tenant-alpha:user-001", 0, -1)
        mock_redis.delete.assert_awaited_once_with("event_queue:tenant-alpha:user-001")

    @pytest.mark.asyncio
    async def test_drain_returns_empty_when_no_events(self, client: AsyncClient, mock_redis: AsyncMock):
        """Drain returns empty list when no events exist."""
        mock_redis.lrange.return_value = []

        response = await client.post(
            "/v1/event/drain",
            json={"user_id": "user-001", "tenant_id": "tenant-alpha"},
        )

        assert response.status_code == 200
        assert response.json() == {"events": []}

    @pytest.mark.asyncio
    async def test_drain_requires_user_id(self, client: AsyncClient):
        """Missing user_id returns 422."""
        response = await client.post(
            "/v1/event/drain",
            json={"tenant_id": "tenant-alpha"},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_drain_requires_tenant_id(self, client: AsyncClient):
        """Missing tenant_id returns 422."""
        response = await client.post(
            "/v1/event/drain",
            json={"user_id": "user-001"},
        )
        assert response.status_code == 422
