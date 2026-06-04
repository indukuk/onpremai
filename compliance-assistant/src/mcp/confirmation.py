"""Human-in-the-loop confirmation flow for destructive MCP tool calls.

When MCP server returns confirmation_required, the agent pauses execution
and presents the server's summary to the user. The user can confirm or cancel.
"""

from __future__ import annotations

from typing import Any

import structlog

from src.mcp.client import MCPClient

logger = structlog.get_logger(__name__)


class ConfirmationHandler:
    """Handles the confirmation flow for destructive tool actions.

    The flow:
    1. Agent calls tools/call -> MCP returns {status: "confirmation_required", summary: "..."}
    2. Agent shows MCP's summary to user, asks confirm/cancel
    3. User confirms -> agent re-calls tools/call with confirmed=True
    4. User cancels -> agent acknowledges, logs cancellation

    The agent MUST show the MCP server's summary text (not generate its own).
    """

    def __init__(self, mcp: MCPClient) -> None:
        self._mcp = mcp

    async def execute_confirmed(
        self,
        tool_name: str,
        params: dict[str, Any],
        jwt_token: str,
    ) -> dict[str, Any]:
        """Execute a tool that was previously confirmed by the user.

        Re-calls the MCP server with confirmed=True.

        Args:
            tool_name: The tool to execute.
            params: Original tool parameters.
            jwt_token: User's JWT.

        Returns:
            Tool execution result dict.
        """
        logger.info(
            "confirmed_tool_execution",
            tool_name=tool_name,
        )

        result = await self._mcp.call_tool(
            tool_name=tool_name,
            params=params,
            jwt_token=jwt_token,
            confirmed=True,
        )

        if result.get("status") == "success":
            logger.info(
                "confirmed_tool_success",
                tool_name=tool_name,
            )
        else:
            logger.warning(
                "confirmed_tool_failed",
                tool_name=tool_name,
                error=result.get("message", "unknown"),
            )

        return result

    def format_confirmation_prompt(self, summary: str, tool_name: str) -> str:
        """Format the confirmation prompt shown to the user.

        Uses the MCP server's summary text directly (not generated).

        Args:
            summary: The summary text from MCP server.
            tool_name: The tool name for context.

        Returns:
            Formatted confirmation message for the user.
        """
        return (
            f"{summary}\n\n"
            f"This action ({tool_name}) requires your confirmation. "
            "Reply /confirm to proceed or /cancel to abort."
        )
