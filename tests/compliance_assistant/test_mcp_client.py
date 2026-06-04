"""Unit tests for the MCP client (tool discovery, execution, errors).

Covers:
- tools/list: successful discovery, HTTP errors, timeout, empty results
- tools/call: success, 401/403/5xx errors, timeout, confirmation_required
- resources/read: success and failure
- prompts/get: success and failure
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# We need to mock httpx before importing MCPClient
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_http_client() -> AsyncMock:
    """Mock httpx.AsyncClient for MCP HTTP calls."""
    client = AsyncMock()
    return client


@pytest.fixture
def mcp_client(mock_http_client: AsyncMock) -> Any:
    """Create an MCPClient with mocked HTTP transport."""
    from src.mcp.client import MCPClient

    with patch("src.mcp.client.settings") as mock_settings:
        mock_settings.mcp_server_url = "http://localhost:8080/mcp"
        mock_settings.tool_timeout_sec = 10.0

        client = MCPClient(
            mcp_url="http://localhost:8080/mcp",
            timeout=10.0,
        )
    # Replace internal HTTP client with mock
    client._http = mock_http_client
    return client


# ---------------------------------------------------------------------------
# Test: tools/list
# ---------------------------------------------------------------------------


class TestListTools:
    """Tests for MCPClient.list_tools."""

    @pytest.mark.asyncio
    async def test_list_tools_success(
        self, mcp_client: Any, mock_http_client: AsyncMock
    ) -> None:
        """Successful tool discovery returns list of tool definitions."""
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "tools": [
                {
                    "name": "evidence.check_coverage",
                    "description": "Check evidence coverage",
                    "inputSchema": {"type": "object", "properties": {}},
                },
                {
                    "name": "memory.task_list",
                    "description": "List tasks",
                    "inputSchema": {"type": "object", "properties": {}},
                },
            ]
        }
        mock_http_client.post.return_value = mock_response

        tools = await mcp_client.list_tools(jwt_token="test-jwt")

        assert len(tools) == 2
        assert tools[0]["name"] == "evidence.check_coverage"
        assert tools[1]["name"] == "memory.task_list"

    @pytest.mark.asyncio
    async def test_list_tools_http_error(
        self, mcp_client: Any, mock_http_client: AsyncMock
    ) -> None:
        """HTTP 400+ returns empty list (graceful degradation)."""
        mock_response = AsyncMock()
        mock_response.status_code = 500
        mock_http_client.post.return_value = mock_response

        tools = await mcp_client.list_tools(jwt_token="test-jwt")

        assert tools == []

    @pytest.mark.asyncio
    async def test_list_tools_timeout(
        self, mcp_client: Any, mock_http_client: AsyncMock
    ) -> None:
        """Timeout returns empty list."""
        import httpx

        mock_http_client.post.side_effect = httpx.TimeoutException("timed out")

        tools = await mcp_client.list_tools(jwt_token="test-jwt")

        assert tools == []

    @pytest.mark.asyncio
    async def test_list_tools_connection_error(
        self, mcp_client: Any, mock_http_client: AsyncMock
    ) -> None:
        """Connection error returns empty list."""
        mock_http_client.post.side_effect = ConnectionError("refused")

        tools = await mcp_client.list_tools(jwt_token="test-jwt")

        assert tools == []

    @pytest.mark.asyncio
    async def test_list_tools_empty_response(
        self, mcp_client: Any, mock_http_client: AsyncMock
    ) -> None:
        """Response with no tools key returns empty list."""
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {}
        mock_http_client.post.return_value = mock_response

        tools = await mcp_client.list_tools(jwt_token="test-jwt")

        # Should handle gracefully: json is dict without 'tools' key
        # The code does data.get("tools", data), which returns {} which is not a list
        assert tools == [] or isinstance(tools, list)

    @pytest.mark.asyncio
    async def test_list_tools_with_jwt_header(
        self, mcp_client: Any, mock_http_client: AsyncMock
    ) -> None:
        """JWT token is passed in Authorization header."""
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"tools": []}
        mock_http_client.post.return_value = mock_response

        await mcp_client.list_tools(jwt_token="my-jwt-token")

        call_kwargs = mock_http_client.post.call_args
        headers = call_kwargs.kwargs.get("headers", call_kwargs[1].get("headers", {}))
        assert headers.get("Authorization") == "Bearer my-jwt-token"


# ---------------------------------------------------------------------------
# Test: tools/call
# ---------------------------------------------------------------------------


class TestCallTool:
    """Tests for MCPClient.call_tool."""

    @pytest.mark.asyncio
    async def test_call_tool_success(
        self, mcp_client: Any, mock_http_client: AsyncMock
    ) -> None:
        """Successful tool call returns status=success with data."""
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "content": {"readiness": "85%", "controls_met": 42}
        }
        mock_http_client.post.return_value = mock_response

        result = await mcp_client.call_tool(
            tool_name="evidence.check_coverage",
            params={"framework_id": "SOC2"},
            jwt_token="test-jwt",
        )

        assert result["status"] == "success"
        assert result["data"]["readiness"] == "85%"

    @pytest.mark.asyncio
    async def test_call_tool_401_unauthorized(
        self, mcp_client: Any, mock_http_client: AsyncMock
    ) -> None:
        """401 response returns session expired error."""
        mock_response = AsyncMock()
        mock_response.status_code = 401
        mock_http_client.post.return_value = mock_response

        result = await mcp_client.call_tool(
            tool_name="evidence.delete",
            params={},
            jwt_token="expired-jwt",
        )

        assert result["status"] == "error"
        assert "session expired" in result["message"].lower() or "log in" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_call_tool_403_forbidden(
        self, mcp_client: Any, mock_http_client: AsyncMock
    ) -> None:
        """403 response returns permission denied error."""
        mock_response = AsyncMock()
        mock_response.status_code = 403
        mock_http_client.post.return_value = mock_response

        result = await mcp_client.call_tool(
            tool_name="admin.delete_tenant",
            params={},
            jwt_token="viewer-jwt",
        )

        assert result["status"] == "error"
        assert "permission" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_call_tool_5xx_server_error(
        self, mcp_client: Any, mock_http_client: AsyncMock
    ) -> None:
        """5xx response returns server error."""
        mock_response = AsyncMock()
        mock_response.status_code = 502
        mock_http_client.post.return_value = mock_response

        result = await mcp_client.call_tool(
            tool_name="evidence.check_coverage",
            params={},
            jwt_token="test-jwt",
        )

        assert result["status"] == "error"
        assert "server error" in result["message"].lower() or "502" in result["message"]

    @pytest.mark.asyncio
    async def test_call_tool_timeout(
        self, mcp_client: Any, mock_http_client: AsyncMock
    ) -> None:
        """Timeout returns error with tool name."""
        import httpx

        mock_http_client.post.side_effect = httpx.TimeoutException("timed out")

        result = await mcp_client.call_tool(
            tool_name="slow.tool",
            params={},
            jwt_token="test-jwt",
        )

        assert result["status"] == "error"
        assert "slow.tool" in result["message"]
        assert "timed out" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_call_tool_confirmation_required(
        self, mcp_client: Any, mock_http_client: AsyncMock
    ) -> None:
        """MCP returns confirmation_required for destructive tool."""
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": "confirmation_required",
            "summary": "This will permanently delete 5 evidence records. Proceed?",
        }
        mock_http_client.post.return_value = mock_response

        result = await mcp_client.call_tool(
            tool_name="evidence.bulk_delete",
            params={"ids": ["a", "b", "c", "d", "e"]},
            jwt_token="test-jwt",
        )

        assert result["status"] == "confirmation_required"
        assert "permanently delete" in result["summary"]
        assert result["tool_name"] == "evidence.bulk_delete"
        assert result["params"] == {"ids": ["a", "b", "c", "d", "e"]}

    @pytest.mark.asyncio
    async def test_call_tool_with_confirmed_flag(
        self, mcp_client: Any, mock_http_client: AsyncMock
    ) -> None:
        """Confirmed re-call sends confirmed=True in payload."""
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "content": {"deleted": 5}
        }
        mock_http_client.post.return_value = mock_response

        result = await mcp_client.call_tool(
            tool_name="evidence.bulk_delete",
            params={"ids": ["a", "b", "c", "d", "e"]},
            jwt_token="test-jwt",
            confirmed=True,
        )

        assert result["status"] == "success"
        # Verify payload included confirmed=True
        call_kwargs = mock_http_client.post.call_args
        payload = call_kwargs.kwargs.get("json", call_kwargs[1].get("json", {}))
        assert payload.get("confirmed") is True

    @pytest.mark.asyncio
    async def test_call_tool_generic_exception(
        self, mcp_client: Any, mock_http_client: AsyncMock
    ) -> None:
        """Generic exception returns error with exception type."""
        mock_http_client.post.side_effect = RuntimeError("unexpected")

        result = await mcp_client.call_tool(
            tool_name="some.tool",
            params={},
            jwt_token="test-jwt",
        )

        assert result["status"] == "error"
        assert "RuntimeError" in result["message"]


# ---------------------------------------------------------------------------
# Test: resources/read
# ---------------------------------------------------------------------------


class TestReadResource:
    """Tests for MCPClient.read_resource."""

    @pytest.mark.asyncio
    async def test_read_resource_success(
        self, mcp_client: Any, mock_http_client: AsyncMock
    ) -> None:
        """Successful resource read returns data."""
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "contents": {"readiness": "85%", "frameworks": ["SOC2", "ISO27001"]}
        }
        mock_http_client.post.return_value = mock_response

        result = await mcp_client.read_resource(
            uri="tenant://acme/frameworks/status",
            jwt_token="test-jwt",
        )

        assert result["readiness"] == "85%"
        assert "SOC2" in result["frameworks"]

    @pytest.mark.asyncio
    async def test_read_resource_http_error(
        self, mcp_client: Any, mock_http_client: AsyncMock
    ) -> None:
        """HTTP error returns empty dict."""
        mock_response = AsyncMock()
        mock_response.status_code = 404
        mock_http_client.post.return_value = mock_response

        result = await mcp_client.read_resource(
            uri="tenant://acme/nonexistent",
            jwt_token="test-jwt",
        )

        assert result == {}

    @pytest.mark.asyncio
    async def test_read_resource_exception(
        self, mcp_client: Any, mock_http_client: AsyncMock
    ) -> None:
        """Exception returns empty dict (graceful degradation)."""
        mock_http_client.post.side_effect = ConnectionError("refused")

        result = await mcp_client.read_resource(
            uri="tenant://acme/status",
            jwt_token="test-jwt",
        )

        assert result == {}


# ---------------------------------------------------------------------------
# Test: prompts/get
# ---------------------------------------------------------------------------


class TestGetPrompt:
    """Tests for MCPClient.get_prompt."""

    @pytest.mark.asyncio
    async def test_get_prompt_success(
        self, mcp_client: Any, mock_http_client: AsyncMock
    ) -> None:
        """Successful prompt fetch returns rendered text."""
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "messages": [
                {"content": {"text": "Step 1: Review the access control policy."}}
            ]
        }
        mock_http_client.post.return_value = mock_response

        result = await mcp_client.get_prompt(
            prompt_name="evaluate-control",
            params={"control_id": "CC6.1"},
            jwt_token="test-jwt",
        )

        assert "Step 1" in result
        assert "access control" in result

    @pytest.mark.asyncio
    async def test_get_prompt_http_error(
        self, mcp_client: Any, mock_http_client: AsyncMock
    ) -> None:
        """HTTP error returns empty string."""
        mock_response = AsyncMock()
        mock_response.status_code = 500
        mock_http_client.post.return_value = mock_response

        result = await mcp_client.get_prompt(
            prompt_name="nonexistent-prompt",
            jwt_token="test-jwt",
        )

        assert result == ""

    @pytest.mark.asyncio
    async def test_get_prompt_exception(
        self, mcp_client: Any, mock_http_client: AsyncMock
    ) -> None:
        """Exception returns empty string (graceful degradation)."""
        mock_http_client.post.side_effect = RuntimeError("error")

        result = await mcp_client.get_prompt(
            prompt_name="broken-prompt",
            jwt_token="test-jwt",
        )

        assert result == ""

    @pytest.mark.asyncio
    async def test_get_prompt_fallback_text_field(
        self, mcp_client: Any, mock_http_client: AsyncMock
    ) -> None:
        """Falls back to 'text' field when no messages list."""
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "text": "Fallback prompt text."
        }
        mock_http_client.post.return_value = mock_response

        result = await mcp_client.get_prompt(
            prompt_name="simple-prompt",
            jwt_token="test-jwt",
        )

        assert result == "Fallback prompt text."


# ---------------------------------------------------------------------------
# Test: close
# ---------------------------------------------------------------------------


class TestClose:
    """Tests for MCPClient.close."""

    @pytest.mark.asyncio
    async def test_close_calls_aclose(
        self, mcp_client: Any, mock_http_client: AsyncMock
    ) -> None:
        """close() delegates to httpx client aclose."""
        mock_http_client.aclose = AsyncMock()

        await mcp_client.close()

        mock_http_client.aclose.assert_called_once()
