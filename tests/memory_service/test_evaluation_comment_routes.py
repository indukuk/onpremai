"""Tests for evaluation comments routes (R7g)."""
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
    "src.routes.evaluation_comments",
    os.path.join(os.path.dirname(__file__), "../../memory-service/src/routes/evaluation_comments.py"),
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
    redis.rpush = AsyncMock(return_value=1)
    redis.lrange = AsyncMock(return_value=[])
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
# POST /v1/evaluation-comments/add
# ---------------------------------------------------------------------------


class TestAddComment:
    @pytest.mark.asyncio
    async def test_add_stores_comment(self, client: AsyncClient, mock_redis: AsyncMock):
        response = await client.post(
            "/v1/evaluation-comments/add",
            json={
                "evaluation_id": "eval-001",
                "tenant_id": "tenant-alpha",
                "author_id": "user-01",
                "author_role": "compliance_manager",
                "content": "I reviewed this criterion and agree with the AI assessment.",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        comment = data["comment"]
        assert comment["evaluation_id"] == "eval-001"
        assert comment["author_id"] == "user-01"
        assert comment["author_role"] == "compliance_manager"
        assert comment["content"] == "I reviewed this criterion and agree with the AI assessment."
        assert comment["criterion_id"] is None
        assert comment["parent_comment_id"] is None
        assert "comment_id" in comment
        assert "created_at" in comment

        # Verify Redis rpush called with correct key
        mock_redis.rpush.assert_awaited_once()
        call_args = mock_redis.rpush.call_args
        assert call_args[0][0] == "eval_comments:tenant-alpha:eval-001"

    @pytest.mark.asyncio
    async def test_add_comment_with_criterion_scope(self, client: AsyncClient, mock_redis: AsyncMock):
        response = await client.post(
            "/v1/evaluation-comments/add",
            json={
                "evaluation_id": "eval-001",
                "tenant_id": "tenant-alpha",
                "author_id": "user-02",
                "author_role": "auditor",
                "content": "This evidence file is outdated.",
                "criterion_id": "crit-3",
            },
        )

        assert response.status_code == 200
        comment = response.json()["comment"]
        assert comment["criterion_id"] == "crit-3"

    @pytest.mark.asyncio
    async def test_add_threaded_reply(self, client: AsyncClient, mock_redis: AsyncMock):
        response = await client.post(
            "/v1/evaluation-comments/add",
            json={
                "evaluation_id": "eval-001",
                "tenant_id": "tenant-alpha",
                "author_id": "user-03",
                "author_role": "contributor",
                "content": "Updated the evidence file just now.",
                "parent_comment_id": "comment-parent-01",
            },
        )

        assert response.status_code == 200
        comment = response.json()["comment"]
        assert comment["parent_comment_id"] == "comment-parent-01"

    @pytest.mark.asyncio
    async def test_add_requires_author_id(self, client: AsyncClient):
        response = await client.post(
            "/v1/evaluation-comments/add",
            json={
                "evaluation_id": "eval-001",
                "tenant_id": "tenant-alpha",
                "author_role": "admin",
                "content": "Missing author",
            },
        )
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# POST /v1/evaluation-comments/list
# ---------------------------------------------------------------------------


class TestListComments:
    @pytest.mark.asyncio
    async def test_list_returns_empty_when_no_comments(self, client: AsyncClient, mock_redis: AsyncMock):
        mock_redis.lrange.return_value = []

        response = await client.post(
            "/v1/evaluation-comments/list",
            json={"evaluation_id": "eval-001", "tenant_id": "tenant-alpha"},
        )

        assert response.status_code == 200
        assert response.json() == {"comments": []}

    @pytest.mark.asyncio
    async def test_list_returns_all_comments(self, client: AsyncClient, mock_redis: AsyncMock):
        comments = [
            {
                "comment_id": "c-1",
                "evaluation_id": "eval-001",
                "tenant_id": "tenant-alpha",
                "author_id": "user-01",
                "author_role": "admin",
                "content": "First comment",
                "criterion_id": None,
                "parent_comment_id": None,
                "created_at": 1000.0,
            },
            {
                "comment_id": "c-2",
                "evaluation_id": "eval-001",
                "tenant_id": "tenant-alpha",
                "author_id": "user-02",
                "author_role": "auditor",
                "content": "Reply",
                "criterion_id": None,
                "parent_comment_id": "c-1",
                "created_at": 2000.0,
            },
        ]
        mock_redis.lrange.return_value = [json.dumps(c) for c in comments]

        response = await client.post(
            "/v1/evaluation-comments/list",
            json={"evaluation_id": "eval-001", "tenant_id": "tenant-alpha"},
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["comments"]) == 2
        assert data["comments"][0]["comment_id"] == "c-1"
        assert data["comments"][1]["parent_comment_id"] == "c-1"

    @pytest.mark.asyncio
    async def test_list_requires_evaluation_id(self, client: AsyncClient):
        response = await client.post(
            "/v1/evaluation-comments/list",
            json={"tenant_id": "tenant-alpha"},
        )
        assert response.status_code == 422
