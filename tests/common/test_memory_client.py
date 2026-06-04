"""Tests for common.clients.memory_client MemoryClient with graceful degradation."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from common.clients.memory_client import MemoryClient


@pytest.fixture
def mock_http_client() -> AsyncMock:
    """Provide a mocked httpx.AsyncClient."""
    client = AsyncMock()
    client.post = AsyncMock()
    client.aclose = AsyncMock()
    return client


@pytest.fixture
def memory_client(mock_http_client) -> MemoryClient:
    """Create a MemoryClient with mocked HTTP transport."""
    client = MemoryClient(memory_url="http://test-memory:5000")
    client._http = mock_http_client
    return client


class TestGracefulDegradationOnFailure:
    """Verify that all methods return empty/neutral values on failure."""

    @pytest.mark.asyncio
    async def test_tenant_recall_returns_empty_on_connect_error(
        self, memory_client, mock_http_client
    ):
        mock_http_client.post.side_effect = httpx.ConnectError("connection refused")

        result = await memory_client.tenant_recall("t-1", "SOC2 controls")
        assert result == []

    @pytest.mark.asyncio
    async def test_tenant_recall_returns_empty_on_timeout(
        self, memory_client, mock_http_client
    ):
        mock_http_client.post.side_effect = httpx.TimeoutException("timed out")

        result = await memory_client.tenant_recall("t-1", "query")
        assert result == []

    @pytest.mark.asyncio
    async def test_tenant_recall_returns_empty_on_500(
        self, memory_client, mock_http_client
    ):
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_http_client.post.return_value = mock_response

        result = await memory_client.tenant_recall("t-1", "query")
        assert result == []

    @pytest.mark.asyncio
    async def test_tenant_store_returns_false_on_error(
        self, memory_client, mock_http_client
    ):
        mock_http_client.post.side_effect = Exception("network error")

        result = await memory_client.tenant_store("t-1", "some fact")
        assert result is False

    @pytest.mark.asyncio
    async def test_session_recall_returns_empty_on_error(
        self, memory_client, mock_http_client
    ):
        mock_http_client.post.side_effect = httpx.ConnectError("fail")

        result = await memory_client.session_recall("session-1")
        assert result == []

    @pytest.mark.asyncio
    async def test_user_recall_returns_empty_on_error(
        self, memory_client, mock_http_client
    ):
        mock_http_client.post.side_effect = Exception("fail")

        result = await memory_client.user_recall("u-1", "query")
        assert result == []

    @pytest.mark.asyncio
    async def test_eval_recall_returns_empty_on_error(
        self, memory_client, mock_http_client
    ):
        mock_http_client.post.side_effect = Exception("fail")

        result = await memory_client.eval_recall("t-1", "SOC2")
        assert result == []

    @pytest.mark.asyncio
    async def test_task_recall_returns_empty_dict_on_error(
        self, memory_client, mock_http_client
    ):
        mock_http_client.post.side_effect = Exception("fail")

        result = await memory_client.task_recall("task-1", "t-1")
        assert result == {}

    @pytest.mark.asyncio
    async def test_pattern_recall_returns_empty_on_error(
        self, memory_client, mock_http_client
    ):
        mock_http_client.post.side_effect = Exception("fail")

        result = await memory_client.pattern_recall("t-1")
        assert result == []

    @pytest.mark.asyncio
    async def test_skill_recall_returns_empty_on_error(
        self, memory_client, mock_http_client
    ):
        mock_http_client.post.side_effect = Exception("fail")

        result = await memory_client.skill_recall("t-1")
        assert result == []

    @pytest.mark.asyncio
    async def test_interaction_recall_returns_empty_on_error(
        self, memory_client, mock_http_client
    ):
        mock_http_client.post.side_effect = Exception("fail")

        result = await memory_client.interaction_recall("u-1", "t-1")
        assert result == []

    @pytest.mark.asyncio
    async def test_store_returns_false_on_4xx(
        self, memory_client, mock_http_client
    ):
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_http_client.post.return_value = mock_response

        result = await memory_client.session_store("s-1", [{"role": "user", "content": "hi"}])
        assert result is False


class TestSuccessfulOperations:
    """Test successful memory operations."""

    @pytest.mark.asyncio
    async def test_tenant_recall_returns_facts(self, memory_client, mock_http_client):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "facts": [
                {"content": "SOC2 audit passed", "score": 0.95},
                {"content": "CC6.1 has evidence", "score": 0.88},
            ]
        }
        mock_http_client.post.return_value = mock_response

        result = await memory_client.tenant_recall("t-1", "SOC2", top_k=5)
        assert len(result) == 2
        assert result[0]["content"] == "SOC2 audit passed"

    @pytest.mark.asyncio
    async def test_tenant_recall_handles_list_response(self, memory_client, mock_http_client):
        """Some endpoints return a direct list instead of a dict."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [{"fact": "data"}]
        mock_http_client.post.return_value = mock_response

        result = await memory_client.tenant_recall("t-1", "query")
        assert result == [{"fact": "data"}]

    @pytest.mark.asyncio
    async def test_tenant_store_returns_true(self, memory_client, mock_http_client):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_http_client.post.return_value = mock_response

        result = await memory_client.tenant_store("t-1", "fact text")
        assert result is True

    @pytest.mark.asyncio
    async def test_eval_store_sends_correct_payload(self, memory_client, mock_http_client):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_http_client.post.return_value = mock_response

        await memory_client.eval_store(
            tenant_id="t-1",
            framework="SOC2",
            control_id="CC6.1",
            result={"score": 0.95, "status": "compliant"},
        )

        call_kwargs = mock_http_client.post.call_args
        assert call_kwargs.args[0] == "/v1/eval/store"
        payload = call_kwargs.kwargs["json"]
        assert payload["tenant_id"] == "t-1"
        assert payload["framework"] == "SOC2"
        assert payload["control_id"] == "CC6.1"
        assert payload["result"]["score"] == 0.95

    @pytest.mark.asyncio
    async def test_session_recall_returns_messages(self, memory_client, mock_http_client):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "messages": [
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "hi"},
            ]
        }
        mock_http_client.post.return_value = mock_response

        result = await memory_client.session_recall("session-1")
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_task_recall_returns_dict(self, memory_client, mock_http_client):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"state": "running", "progress": 0.5}
        mock_http_client.post.return_value = mock_response

        result = await memory_client.task_recall("task-1", "t-1")
        assert result == {"state": "running", "progress": 0.5}


class TestMemoryClientClose:
    """Test client cleanup."""

    @pytest.mark.asyncio
    async def test_close_calls_aclose(self, memory_client, mock_http_client):
        await memory_client.close()
        mock_http_client.aclose.assert_awaited_once()


class TestNeverCrashes:
    """Ensure that NO exception type causes a crash -- all are caught."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "exception",
        [
            httpx.ConnectError("refused"),
            httpx.TimeoutException("timeout"),
            OSError("socket error"),
            RuntimeError("unexpected"),
            ValueError("bad data"),
            ConnectionResetError("reset"),
        ],
    )
    async def test_recall_never_raises(self, memory_client, mock_http_client, exception):
        mock_http_client.post.side_effect = exception
        # Should not raise -- returns empty
        result = await memory_client.tenant_recall("t-1", "query")
        assert result == [] or result == {}

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "exception",
        [
            httpx.ConnectError("refused"),
            httpx.TimeoutException("timeout"),
            RuntimeError("unexpected"),
        ],
    )
    async def test_store_never_raises(self, memory_client, mock_http_client, exception):
        mock_http_client.post.side_effect = exception
        # Should not raise -- returns False
        result = await memory_client.tenant_store("t-1", "data")
        assert result is False
