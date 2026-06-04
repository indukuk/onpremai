from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class GatewaySettings(BaseSettings):
    """LLM Gateway service configuration.

    All settings are overridable via environment variables with the LLM_GW_ prefix.
    """

    model_config = SettingsConfigDict(
        env_prefix="LLM_GW_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Service identity
    service_name: str = "llm-gateway"
    version: str = "0.1.0"

    # Network ports
    agent_port: int = Field(default=4000, description="Port for agent-facing API")
    admin_port: int = Field(default=4001, description="Port for admin API")

    # Routing config path (hot-reloaded via watchdog)
    routing_config_path: str = Field(
        default="config/routing.yaml",
        description="Path to routing YAML configuration",
    )

    # Redis connection for budget tracking and rate limiting
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection URL",
    )

    # S2S auth
    service_auth_enabled: bool = Field(
        default=True,
        description="Enable S2S HMAC auth on all endpoints",
    )
    service_keys_secret_name: str = Field(
        default="onpremai/service-keys",
        description="Secrets Manager name for S2S keys",
    )

    # Logging
    log_level: str = Field(default="INFO", description="Logging level")
    log_format: str = Field(default="json", description="Log format: json or console")

    # Health check
    health_check_interval_seconds: int = Field(
        default=30,
        description="Interval between model health checks",
    )
    health_check_timeout_ms: int = Field(
        default=5000,
        description="Timeout for health check probes",
    )

    # AWS region (for Bedrock)
    aws_region: str = Field(default="us-east-1", description="AWS region for Bedrock")

    # Anthropic API key (optional, can come from routing.yaml per-model)
    anthropic_api_key: str | None = Field(
        default=None,
        description="Default Anthropic API key",
    )

    # OpenAI API key (optional)
    openai_api_key: str | None = Field(
        default=None,
        description="Default OpenAI API key",
    )


def get_settings() -> GatewaySettings:
    """Get singleton settings instance."""
    return GatewaySettings()
