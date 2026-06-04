"""MCP client for tool discovery, execution, and resource reading.

The compliance-assistant is an MCP client that connects to the backend's
MCP server. It discovers tools (filtered by role via JWT), calls tools,
and reads resources for context building.
"""

from __future__ import annotations

import time
from typing import Any

import httpx
import structlog

from src.config import settings

logger = structlog.get_logger(__name__)


class MCPClient:
    """Async MCP protocol client for the compliance backend.

    Implements the MCP client protocol:
    - tools/list: Discover available tools (filtered by JWT role)
    - tools/call: Execute a tool with parameters
    - resources/read: Read tenant state resources
    - prompts/get: Load workflow guidance prompts

    All calls pass the user's JWT for auth enforcement by the MCP server.
    """

    def __init__(
        self,
        mcp_url: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self._mcp_url = (mcp_url or settings.mcp_server_url).rstrip("/")
        self._timeout = timeout or settings.tool_timeout_sec
        self._http = httpx.AsyncClient(
            base_url=self._mcp_url,
            timeout=httpx.Timeout(self._timeout, connect=5.0),
            headers={"Content-Type": "application/json"},
        )

    async def list_tools(self, jwt_token: str) -> list[dict[str, Any]]:
        """Discover available tools from the MCP server.

        The server returns tools filtered by the user's role (from JWT).
        New tools added to MCP server are discovered immediately.

        Args:
            jwt_token: User's JWT for role-based filtering.

        Returns:
            List of tool definition dicts with name, description, inputSchema.
        """
        try:
            response = await self._http.post(
                "/tools/list",
                json={},
                headers=self._auth_headers(jwt_token),
            )

            if response.status_code >= 400:
                logger.warning(
                    "mcp_tools_list_failed",
                    status=response.status_code,
                )
                return []

            data = response.json()
            tools = data.get("tools", data) if isinstance(data, dict) else data
            return tools if isinstance(tools, list) else []

        except httpx.TimeoutException:
            logger.warning("mcp_tools_list_timeout")
            return []
        except Exception as exc:
            logger.warning(
                "mcp_tools_list_error",
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return []

    async def call_tool(
        self,
        tool_name: str,
        params: dict[str, Any],
        jwt_token: str,
        confirmed: bool = False,
    ) -> dict[str, Any]:
        """Execute a tool via the MCP server.

        Returns the tool result or a confirmation_required status if the
        tool is destructive and needs human approval.

        Args:
            tool_name: Name of the tool to call.
            params: Tool parameters.
            jwt_token: User's JWT for auth.
            confirmed: Whether this is a confirmed re-call after approval.

        Returns:
            Dict with 'status' and 'data'/'summary' keys.
            Possible statuses: 'success', 'error', 'confirmation_required'.
        """
        payload: dict[str, Any] = {
            "name": tool_name,
            "arguments": params,
        }
        if confirmed:
            payload["confirmed"] = True

        start_time = time.perf_counter()

        try:
            response = await self._http.post(
                "/tools/call",
                json=payload,
                headers=self._auth_headers(jwt_token),
            )
            latency_ms = round((time.perf_counter() - start_time) * 1000, 2)

            if response.status_code == 401:
                return {
                    "status": "error",
                    "message": "Session expired. Please log in again.",
                }

            if response.status_code == 403:
                return {
                    "status": "error",
                    "message": "You don't have permission to perform this action.",
                }

            if response.status_code >= 500:
                logger.error(
                    "mcp_tool_call_5xx",
                    tool_name=tool_name,
                    status=response.status_code,
                )
                return {
                    "status": "error",
                    "message": f"Tool execution failed (server error {response.status_code}).",
                }

            data = response.json()

            # Check for confirmation_required status
            if data.get("status") == "confirmation_required":
                logger.info(
                    "mcp_tool_confirmation_required",
                    tool_name=tool_name,
                    latency_ms=latency_ms,
                )
                return {
                    "status": "confirmation_required",
                    "summary": data.get("summary", f"Confirm execution of {tool_name}"),
                    "tool_name": tool_name,
                    "params": params,
                }

            logger.info(
                "mcp_tool_call_success",
                tool_name=tool_name,
                latency_ms=latency_ms,
            )

            return {
                "status": "success",
                "data": data.get("content", data.get("result", data.get("data", data))),
            }

        except httpx.TimeoutException:
            latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
            logger.warning(
                "mcp_tool_call_timeout",
                tool_name=tool_name,
                latency_ms=latency_ms,
            )
            return {
                "status": "error",
                "message": f"Tool {tool_name} timed out after {self._timeout}s.",
            }
        except Exception as exc:
            logger.error(
                "mcp_tool_call_error",
                tool_name=tool_name,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return {
                "status": "error",
                "message": f"Tool execution failed: {type(exc).__name__}",
            }

    async def read_resource(
        self,
        uri: str,
        jwt_token: str,
    ) -> dict[str, Any]:
        """Read a resource from the MCP server.

        Resources provide tenant state context (readiness, timeline, etc.)
        without executing actions.

        Args:
            uri: Resource URI (e.g., "tenant://acme/frameworks/status").
            jwt_token: User's JWT for auth.

        Returns:
            Resource data dict, or empty dict on failure.
        """
        try:
            response = await self._http.post(
                "/resources/read",
                json={"uri": uri},
                headers=self._auth_headers(jwt_token),
            )

            if response.status_code >= 400:
                logger.warning(
                    "mcp_resource_read_failed",
                    uri=uri,
                    status=response.status_code,
                )
                return {}

            data = response.json()
            return data.get("contents", data) if isinstance(data, dict) else {}

        except Exception as exc:
            logger.warning(
                "mcp_resource_read_error",
                uri=uri,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return {}

    async def get_prompt(
        self,
        prompt_name: str,
        params: dict[str, Any] | None = None,
        jwt_token: str = "",
    ) -> str:
        """Fetch a prompt template from the MCP server.

        Used for loading workflow guidance for multi-step flows.

        Args:
            prompt_name: Name of the prompt to fetch.
            params: Parameters to fill in the prompt template.
            jwt_token: User's JWT.

        Returns:
            Rendered prompt text, or empty string on failure.
        """
        try:
            payload: dict[str, Any] = {"name": prompt_name}
            if params:
                payload["arguments"] = params

            response = await self._http.post(
                "/prompts/get",
                json=payload,
                headers=self._auth_headers(jwt_token),
            )

            if response.status_code >= 400:
                return ""

            data = response.json()
            messages = data.get("messages", [])
            if messages:
                return messages[0].get("content", {}).get("text", "")
            return data.get("text", data.get("content", ""))

        except Exception as exc:
            logger.warning(
                "mcp_prompt_get_error",
                prompt_name=prompt_name,
                error=str(exc),
            )
            return ""

    def _auth_headers(self, jwt_token: str) -> dict[str, str]:
        """Build authorization headers with JWT."""
        headers: dict[str, str] = {}
        if jwt_token:
            headers["Authorization"] = f"Bearer {jwt_token}"
        return headers

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._http.aclose()
