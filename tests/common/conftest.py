"""Shared fixtures for common/ library tests."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from common.auth.cognito import UserContext
from common.config import CommonSettings


@pytest.fixture
def fake_settings() -> CommonSettings:
    """Provide a CommonSettings instance with test-safe defaults."""
    return CommonSettings(
        llm_gateway_url="http://test-gateway:4000",
        memory_url="http://test-memory:5000",
        storage_backend="s3",
        storage_bucket="test-bucket",
        aws_region="us-east-1",
        redis_url="redis://test-redis:6379/0",
        log_level="debug",
        log_format="json",
        log_pii_redaction=True,
        service_name="test-service",
        service_version="0.0.1",
        environment="test",
        cognito_region="us-east-1",
        cognito_user_pool_id="us-east-1_TestPool",
        cognito_client_id="test-client-id-123",
        pii_hmac_key="test-hmac-key-for-unit-tests",
    )


@pytest.fixture
def mock_httpx_client() -> AsyncMock:
    """Provide a mocked httpx.AsyncClient with common response methods."""
    client = AsyncMock()
    client.post = AsyncMock()
    client.get = AsyncMock()
    client.put = AsyncMock()
    client.delete = AsyncMock()
    client.aclose = AsyncMock()
    return client


@pytest.fixture
def fake_user_context() -> UserContext:
    """Provide a fake authenticated UserContext for RBAC tests."""
    return UserContext(
        user_id="user-uuid-001",
        tenant_id="tenant-abc-123",
        role="analyst",
        email="analyst@acme.com",
        groups=["compliance-team"],
        token_exp=datetime(2099, 12, 31, tzinfo=timezone.utc),
    )


@pytest.fixture
def fake_admin_context() -> UserContext:
    """Provide a fake admin UserContext."""
    return UserContext(
        user_id="admin-uuid-001",
        tenant_id="tenant-abc-123",
        role="admin",
        email="admin@acme.com",
        groups=["admins"],
        token_exp=datetime(2099, 12, 31, tzinfo=timezone.utc),
    )


@pytest.fixture
def fake_contributor_context() -> UserContext:
    """Provide a fake contributor UserContext."""
    return UserContext(
        user_id="contributor-uuid-001",
        tenant_id="tenant-abc-123",
        role="contributor",
        email="contributor@acme.com",
        groups=[],
        token_exp=datetime(2099, 12, 31, tzinfo=timezone.utc),
    )
