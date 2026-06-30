"""Configuration for the compliance-assistant service.

All settings are loaded from environment variables with sensible defaults
for docker-compose deployment.
"""

from __future__ import annotations

from common.config import CommonSettings


class AssistantSettings(CommonSettings):
    """Settings specific to the compliance assistant agent.

    Inherits shared settings (LLM gateway, memory, Redis, storage, auth)
    from CommonSettings. Adds assistant-specific fields.
    """

    # --- Service Identity ---
    service_name: str = "compliance-assistant"
    agent_type: str = "compliance-assistant"

    # --- MCP Server ---
    mcp_server_url: str = "http://backend:8080/mcp"

    # --- Agent Loop ---
    max_tool_rounds: int = 5
    tool_timeout_sec: float = 10.0

    # --- Session ---
    session_ttl_hours: int = 4

    # --- Reflection ---
    reflection_min_messages: int = 6
    reflection_max_history: int = 30

    # --- User State ---
    user_state_max_chars: int = 2000
    max_preferences: int = 10

    # --- Version ---
    chat_version: str = "0.2.0"

    # --- Port ---
    port: int = 8082
    host: str = "0.0.0.0"


settings = AssistantSettings()
