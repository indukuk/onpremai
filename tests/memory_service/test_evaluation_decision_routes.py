"""Tests for evaluation decision lifecycle routes (R7e)."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

import sys, os
import importlib.util
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../memory-service"))

from httpx import ASGITransport, AsyncClient
from fastapi import FastAPI

# Import directly to avoid triggering src/routes/__init__.py which pulls in db deps
_spec = importlib.util.spec_from_file_location(
    "src.routes.evaluation_decisions",
    os.path.join(os.path.dirname(__file__), "../../memory-service/src/routes/evaluation_decisions.py"),
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
router = _mod.router


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_redis() -> AsyncMock:
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock(return_value=True)
    redis.sadd = AsyncMock(return_value=1)
    redis.smembers = AsyncMock(return_value=set())
    return redis


@pytest.fixture
def app(mock_redis: AsyncMock) -> FastAPI:
    _app = FastAPI()
    _app.state.redis = mock_redis
    _app.include_router(router)
    return _app


@pytest.fixture
def client(app: FastAPI) -> AsyncClient:
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


# ---------------------------------------------------------------------------
# POST /v1/evaluation-decisions/create
# ---------------------------------------------------------------------------


class TestCreateDecision:
    @pytest.mark.asyncio
    async def test_create_stores_decision_as_draft(self, client: AsyncClient, mock_redis: AsyncMock):
        response = await client.post(
            "/v1/evaluation-decisions/create",
            json={
                "evaluation_id": "eval-001",
                "tenant_id": "tenant-alpha",
                "control_id": "CC6.1",
                "framework": "SOC2",
                "ai_score": 0.87,
                "ai_status": "compliant",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        decision = data["decision"]
        assert decision["status"] == "draft"
        assert decision["final_score"] == 0.87
        assert decision["final_status"] == "compliant"
        assert decision["overrides"] == []
        assert decision["approved_by"] is None

        # Verify Redis set was called with correct key
        mock_redis.set.assert_awaited_once()
        call_args = mock_redis.set.call_args
        assert call_args[0][0] == "eval_decision:tenant-alpha:eval-001"

        # Verify index update
        mock_redis.sadd.assert_awaited_once_with(
            "eval_decision_index:tenant-alpha", "eval-001"
        )


# ---------------------------------------------------------------------------
# POST /v1/evaluation-decisions/get
# ---------------------------------------------------------------------------


class TestGetDecision:
    @pytest.mark.asyncio
    async def test_get_returns_empty_when_not_found(self, client: AsyncClient, mock_redis: AsyncMock):
        mock_redis.get.return_value = None

        response = await client.post(
            "/v1/evaluation-decisions/get",
            json={"evaluation_id": "nonexistent", "tenant_id": "tenant-alpha"},
        )

        assert response.status_code == 200
        assert response.json() == {}

    @pytest.mark.asyncio
    async def test_get_returns_decision(self, client: AsyncClient, mock_redis: AsyncMock):
        decision = {
            "evaluation_id": "eval-001",
            "tenant_id": "tenant-alpha",
            "control_id": "CC6.1",
            "framework": "SOC2",
            "status": "draft",
            "ai_score": 0.87,
            "final_score": 0.87,
        }
        mock_redis.get.return_value = json.dumps(decision)

        response = await client.post(
            "/v1/evaluation-decisions/get",
            json={"evaluation_id": "eval-001", "tenant_id": "tenant-alpha"},
        )

        assert response.status_code == 200
        assert response.json()["evaluation_id"] == "eval-001"
        assert response.json()["status"] == "draft"


# ---------------------------------------------------------------------------
# POST /v1/evaluation-decisions/override
# ---------------------------------------------------------------------------


class TestOverrideDecision:
    @pytest.mark.asyncio
    async def test_override_appends_to_overrides(self, client: AsyncClient, mock_redis: AsyncMock):
        existing = {
            "evaluation_id": "eval-001",
            "tenant_id": "tenant-alpha",
            "overrides": [],
            "updated_at": 1000.0,
        }
        mock_redis.get.return_value = json.dumps(existing)

        response = await client.post(
            "/v1/evaluation-decisions/override",
            json={
                "evaluation_id": "eval-001",
                "tenant_id": "tenant-alpha",
                "criterion_id": "crit-1",
                "ai_result": "FAIL",
                "user_result": "PASS",
                "reason": "Evidence was reviewed manually and found adequate.",
                "overridden_by": "user-admin-01",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["override"]["criterion_id"] == "crit-1"
        assert data["override"]["user_result"] == "PASS"

        # Verify the decision was saved with the override
        saved_payload = json.loads(mock_redis.set.call_args[0][1])
        assert len(saved_payload["overrides"]) == 1

    @pytest.mark.asyncio
    async def test_override_rejects_empty_reason(self, client: AsyncClient, mock_redis: AsyncMock):
        response = await client.post(
            "/v1/evaluation-decisions/override",
            json={
                "evaluation_id": "eval-001",
                "tenant_id": "tenant-alpha",
                "criterion_id": "crit-1",
                "ai_result": "FAIL",
                "user_result": "PASS",
                "reason": "",
                "overridden_by": "user-admin-01",
            },
        )

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_override_rejects_whitespace_only_reason(self, client: AsyncClient, mock_redis: AsyncMock):
        response = await client.post(
            "/v1/evaluation-decisions/override",
            json={
                "evaluation_id": "eval-001",
                "tenant_id": "tenant-alpha",
                "criterion_id": "crit-1",
                "ai_result": "FAIL",
                "user_result": "PASS",
                "reason": "   ",
                "overridden_by": "user-admin-01",
            },
        )

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_override_returns_404_when_not_found(self, client: AsyncClient, mock_redis: AsyncMock):
        mock_redis.get.return_value = None

        response = await client.post(
            "/v1/evaluation-decisions/override",
            json={
                "evaluation_id": "nonexistent",
                "tenant_id": "tenant-alpha",
                "criterion_id": "crit-1",
                "ai_result": "FAIL",
                "user_result": "PASS",
                "reason": "Valid reason",
                "overridden_by": "user-admin-01",
            },
        )

        assert response.status_code == 404


# ---------------------------------------------------------------------------
# POST /v1/evaluation-decisions/approve
# ---------------------------------------------------------------------------


class TestApproveDecision:
    @pytest.mark.asyncio
    async def test_approve_sets_status_approved(self, client: AsyncClient, mock_redis: AsyncMock):
        existing = {
            "evaluation_id": "eval-001",
            "tenant_id": "tenant-alpha",
            "status": "draft",
            "overrides": [],
            "updated_at": 1000.0,
        }
        mock_redis.get.return_value = json.dumps(existing)

        response = await client.post(
            "/v1/evaluation-decisions/approve",
            json={
                "evaluation_id": "eval-001",
                "tenant_id": "tenant-alpha",
                "approved_by": "compliance-manager-01",
                "notes": "All overrides reviewed and accepted.",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["decision"]["status"] == "approved"
        assert data["decision"]["approved_by"] == "compliance-manager-01"
        assert data["decision"]["approved_at"] is not None

    @pytest.mark.asyncio
    async def test_approve_returns_404_when_not_found(self, client: AsyncClient, mock_redis: AsyncMock):
        mock_redis.get.return_value = None

        response = await client.post(
            "/v1/evaluation-decisions/approve",
            json={
                "evaluation_id": "nonexistent",
                "tenant_id": "tenant-alpha",
                "approved_by": "user-01",
            },
        )

        assert response.status_code == 404


# ---------------------------------------------------------------------------
# POST /v1/evaluation-decisions/list
# ---------------------------------------------------------------------------


class TestListDecisions:
    @pytest.mark.asyncio
    async def test_list_returns_empty_when_no_decisions(self, client: AsyncClient, mock_redis: AsyncMock):
        mock_redis.smembers.return_value = set()

        response = await client.post(
            "/v1/evaluation-decisions/list",
            json={"tenant_id": "tenant-alpha"},
        )

        assert response.status_code == 200
        assert response.json() == {"decisions": []}

    @pytest.mark.asyncio
    async def test_list_returns_decisions_filtered_by_status(self, client: AsyncClient, mock_redis: AsyncMock):
        mock_redis.smembers.return_value = {"eval-001", "eval-002"}

        decision1 = json.dumps({
            "evaluation_id": "eval-001",
            "status": "draft",
            "framework": "SOC2",
            "created_at": 2000.0,
        })
        decision2 = json.dumps({
            "evaluation_id": "eval-002",
            "status": "approved",
            "framework": "SOC2",
            "created_at": 1000.0,
        })

        async def mock_get(key):
            if "eval-001" in key:
                return decision1
            if "eval-002" in key:
                return decision2
            return None

        mock_redis.get = AsyncMock(side_effect=mock_get)

        response = await client.post(
            "/v1/evaluation-decisions/list",
            json={"tenant_id": "tenant-alpha", "status": "draft"},
        )

        assert response.status_code == 200
        decisions = response.json()["decisions"]
        assert len(decisions) == 1
        assert decisions[0]["evaluation_id"] == "eval-001"
