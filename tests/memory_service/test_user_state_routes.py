"""Tests for user-state routes: get and put."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../memory-service"))

from httpx import ASGITransport, AsyncClient
from fastapi import FastAPI

from src.routes.user_state import router


# ---------------------------------------------------------------------------
# App + Redis fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_redis() -> AsyncMock:
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock(return_value=True)
    return redis


@pytest.fixture
def app(mock_redis: AsyncMock) -> FastAPI:
    """Minimal FastAPI app with user-state router mounted."""
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
# POST /v1/user-state/get
# ---------------------------------------------------------------------------


class TestGetUserState:
    @pytest.mark.asyncio
    async def test_get_returns_empty_when_not_found(self, client: AsyncClient, mock_redis: AsyncMock):
        """Returns empty dict when no state exists."""
        mock_redis.get.return_value = None

        response = await client.post(
            "/v1/user-state/get",
            json={"user_id": "user-001", "tenant_id": "tenant-alpha"},
        )

        assert response.status_code == 200
        assert response.json() == {}
        mock_redis.get.assert_awaited_once_with("user_state:tenant-alpha:user-001")

    @pytest.mark.asyncio
    async def test_get_returns_stored_state(self, client: AsyncClient, mock_redis: AsyncMock):
        """Returns the stored JSON document."""
        stored = {"focus_area": "SOC2", "onboarding_step": 3}
        mock_redis.get.return_value = json.dumps(stored)

        response = await client.post(
            "/v1/user-state/get",
            json={"user_id": "user-001", "tenant_id": "tenant-alpha"},
        )

        assert response.status_code == 200
        assert response.json() == stored

    @pytest.mark.asyncio
    async def test_get_requires_user_id(self, client: AsyncClient):
        """Missing user_id returns 422."""
        response = await client.post(
            "/v1/user-state/get",
            json={"tenant_id": "tenant-alpha"},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_get_requires_tenant_id(self, client: AsyncClient):
        """Missing tenant_id returns 422."""
        response = await client.post(
            "/v1/user-state/get",
            json={"user_id": "user-001"},
        )
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# POST /v1/user-state/put
# ---------------------------------------------------------------------------


class TestPutUserState:
    @pytest.mark.asyncio
    async def test_put_stores_state(self, client: AsyncClient, mock_redis: AsyncMock):
        """Stores data and returns ok."""
        data = {"focus_area": "ISO27001", "preferences": {"language": "en"}}

        response = await client.post(
            "/v1/user-state/put",
            json={"user_id": "user-001", "tenant_id": "tenant-alpha", "data": data},
        )

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        mock_redis.set.assert_awaited_once_with(
            "user_state:tenant-alpha:user-001",
            json.dumps(data),
        )

    @pytest.mark.asyncio
    async def test_put_requires_data_field(self, client: AsyncClient):
        """Missing data field returns 422."""
        response = await client.post(
            "/v1/user-state/put",
            json={"user_id": "user-001", "tenant_id": "tenant-alpha"},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_put_overwrites_existing_state(self, client: AsyncClient, mock_redis: AsyncMock):
        """Put is an upsert — always overwrites."""
        response = await client.post(
            "/v1/user-state/put",
            json={"user_id": "user-001", "tenant_id": "tenant-alpha", "data": {"v": 2}},
        )

        assert response.status_code == 200
        mock_redis.set.assert_awaited_once()
