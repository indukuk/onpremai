"""Shared configuration base for all services.

All services inherit from CommonSettings to get shared defaults that work
with docker-compose out of the box. Service-specific settings should
subclass CommonSettings and add their own fields.

Environment variables override all defaults. An optional .env file is
loaded if present (extra fields are ignored).
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class CommonSettings(BaseSettings):
    """Base settings inherited by every service.

    All fields have sensible defaults for docker-compose deployment.
    Override via environment variables or .env file.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        env_file_encoding="utf-8",
    )

    # --- LLM Gateway ---
    llm_gateway_url: str = "http://llm-gateway:4000"

    # --- Memory Service ---
    memory_url: str = "http://memory-service:5000"

    # --- Storage ---
    storage_endpoint: str = ""
    storage_backend: str = "s3"
    storage_bucket: str = "compliance-artifacts"
    storage_access_key: str = ""
    storage_secret_key: str = ""
    aws_region: str = "us-east-1"

    # --- Redis ---
    redis_url: str = "redis://redis:6379/0"

    # --- Logging ---
    log_level: str = "info"
    log_format: str = "json"
    log_pii_redaction: bool = True
    log_audit_enabled: bool = True
    log_unknown_fields_action: str = "redact"

    # --- Service Identity ---
    service_name: str = "unknown"
    service_version: str = "0.0.0"
    environment: str = "production"

    # --- Cognito Auth ---
    cognito_region: str = "us-east-1"
    cognito_user_pool_id: str = ""
    cognito_client_id: str = ""

    # --- Service-to-Service Auth ---
    service_id: str = ""
    service_key: str = ""

    # --- PII ---
    pii_hmac_key: str = ""

    # --- Agent Registry ---
    registry_enabled: bool = True
    agent_type: str = ""
    agent_capabilities: str = "[]"
    agent_max_concurrency: int = 10
    heartbeat_interval_sec: int = 10
    lease_ttl_sec: int = 30

    # --- Tracing ---
    trace_header: str = "X-Trace-Id"

    # --- Sandbox ---
    sandbox_url: str = "http://sandbox-service:6000"

    # --- State ---
    state_backend: str = "postgres"
    state_dsn: str = "postgresql://compliance:password@postgres:5432/compliance"
