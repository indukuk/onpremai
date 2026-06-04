"""Tests for the agent registry routes: register, heartbeat, discover, deregister."""
from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../memory-service"))

from httpx import ASGITransport, AsyncClient
from fastapi import FastAPI

from src.routes.registry import (
    AgentRegistry,
    RegisterAgentBody,
    router,
    _agent_to_dict,
)
from src.db import get_session


# ---------------------------------------------------------------------------
# App + session fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def app() -> FastAPI:
    """Minimal FastAPI app with registry router mounted."""
    _app = FastAPI()
    _app.include_router(router)
    return _app


@pytest.fixture
def mock_session() -> AsyncMock:
    session = AsyncMock()
    session.execute = AsyncMock()
    session.flush = AsyncMock()
    session.add = MagicMock()
    session.delete = AsyncMock()
    return session


@pytest.fixture
def client(app: FastAPI, mock_session: AsyncMock) -> AsyncClient:
    """HTTPX async test client with session override."""
    app.dependency_overrides[get_session] = lambda: mock_session
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


# ---------------------------------------------------------------------------
# Helper: build a fake AgentRegistry
# ---------------------------------------------------------------------------


def make_agent_registry(
    agent_id: str = "agent-eval",
    name: str = "Agent Eval",
    url: str = "http://agent-eval:8080",
    capabilities: list[str] | None = None,
    status: str = "active",
) -> MagicMock:
    obj = MagicMock(spec=AgentRegistry)
    obj.id = agent_id
    obj.name = name
    obj.url = url
    obj.capabilities = capabilities or ["evaluate", "score"]
    obj.status = status
    obj.metadata_ = None
    obj.registered_at = datetime(2026, 1, 1, 12, 0, 0)
    obj.last_heartbeat = datetime(2026, 1, 1, 12, 0, 0)
    return obj


# ---------------------------------------------------------------------------
# POST /registry/agents — register
# ---------------------------------------------------------------------------


class TestRegisterAgent:
    async def test_register_new_agent(self, client: AsyncClient, mock_session: AsyncMock):
        """New agent registration returns agent data."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        response = await client.post(
            "/registry/agents",
            json={
                "id": "compliance-assistant",
                "name": "Compliance Assistant",
                "url": "http://compliance-assistant:8080",
                "capabilities": ["assist", "skill_execution"],
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "compliance-assistant"
        assert data["name"] == "Compliance Assistant"
        mock_session.add.assert_called_once()
        mock_session.flush.assert_awaited_once()

    async def test_register_existing_agent_updates(self, client: AsyncClient, mock_session: AsyncMock):
        """Re-registering an existing agent updates its record."""
        existing = make_agent_registry(agent_id="agent-eval")
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing
        mock_session.execute.return_value = mock_result

        response = await client.post(
            "/registry/agents",
            json={
                "id": "agent-eval",
                "name": "Agent Eval v2",
                "url": "http://agent-eval:9090",
                "capabilities": ["evaluate", "score", "report"],
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Agent Eval v2"
        assert data["url"] == "http://agent-eval:9090"
        assert existing.status == "active"


# ---------------------------------------------------------------------------
# PUT /registry/agents/{agent_id}/heartbeat
# ---------------------------------------------------------------------------


class TestHeartbeat:
    async def test_heartbeat_success(self, client: AsyncClient, mock_session: AsyncMock):
        """Heartbeat updates last_heartbeat and returns agent data."""
        agent = make_agent_registry()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = agent
        mock_session.execute.return_value = mock_result

        response = await client.put("/registry/agents/agent-eval/heartbeat")

        assert response.status_code == 200
        assert agent.status == "active"

    async def test_heartbeat_agent_not_found(self, client: AsyncClient, mock_session: AsyncMock):
        """Heartbeat for non-existent agent returns 404."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        response = await client.put("/registry/agents/nonexistent/heartbeat")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()


# ---------------------------------------------------------------------------
# GET /registry/agents — discover
# ---------------------------------------------------------------------------


class TestDiscoverAgents:
    async def test_list_all_active_agents(self, client: AsyncClient, mock_session: AsyncMock):
        """List returns all active agents."""
        agent1 = make_agent_registry(agent_id="agent-eval")
        agent2 = make_agent_registry(agent_id="preprocessor", name="Preprocessor", capabilities=["ocr"])
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [agent1, agent2]
        mock_session.execute.return_value = mock_result

        response = await client.get("/registry/agents")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2

    async def test_filter_by_capability(self, client: AsyncClient, mock_session: AsyncMock):
        """Filter agents by capability returns only matching agents."""
        agent1 = make_agent_registry(agent_id="agent-eval", capabilities=["evaluate", "score"])
        agent2 = make_agent_registry(agent_id="preprocessor", capabilities=["ocr", "ingest"])
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [agent1, agent2]
        mock_session.execute.return_value = mock_result

        response = await client.get("/registry/agents", params={"capability": "ocr"})

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["id"] == "preprocessor"

    async def test_filter_capability_no_match(self, client: AsyncClient, mock_session: AsyncMock):
        """Filter with non-existent capability returns empty list."""
        agent1 = make_agent_registry(capabilities=["evaluate"])
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [agent1]
        mock_session.execute.return_value = mock_result

        response = await client.get("/registry/agents", params={"capability": "nonexistent"})

        assert response.status_code == 200
        assert response.json() == []

    async def test_empty_registry(self, client: AsyncClient, mock_session: AsyncMock):
        """Empty registry returns empty list."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result

        response = await client.get("/registry/agents")

        assert response.status_code == 200
        assert response.json() == []


# ---------------------------------------------------------------------------
# DELETE /registry/agents/{agent_id} — deregister
# ---------------------------------------------------------------------------


class TestDeregisterAgent:
    async def test_deregister_existing_agent(self, client: AsyncClient, mock_session: AsyncMock):
        """Deregister returns success for existing agent."""
        agent = make_agent_registry(agent_id="agent-eval")
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = agent
        mock_session.execute.return_value = mock_result

        response = await client.delete("/registry/agents/agent-eval")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "agent-eval"
        assert data["status"] == "deregistered"
        mock_session.delete.assert_awaited_once_with(agent)

    async def test_deregister_nonexistent_agent(self, client: AsyncClient, mock_session: AsyncMock):
        """Deregister for non-existent agent returns 404."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        response = await client.delete("/registry/agents/unknown-agent")

        assert response.status_code == 404


# ---------------------------------------------------------------------------
# _agent_to_dict helper
# ---------------------------------------------------------------------------


class TestAgentToDict:
    def test_converts_agent_to_dict(self):
        """Helper function correctly serializes agent to dict."""
        agent = make_agent_registry()
        result = _agent_to_dict(agent)

        assert result["id"] == "agent-eval"
        assert result["name"] == "Agent Eval"
        assert result["url"] == "http://agent-eval:8080"
        assert "evaluate" in result["capabilities"]
        assert result["status"] == "active"
        assert result["registered_at"] is not None

    def test_handles_none_timestamps(self):
        """Dict conversion handles None timestamps gracefully."""
        agent = make_agent_registry()
        agent.registered_at = None
        agent.last_heartbeat = None
        result = _agent_to_dict(agent)

        assert result["registered_at"] is None
        assert result["last_heartbeat"] is None
