"""Tests for common.auth.service_auth ServiceAuthenticator."""

from __future__ import annotations

import hashlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import Depends, FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

from common.auth.service_auth import (
    ServiceAuthenticator,
    ServiceIdentity,
    verify_service,
)


class TestServiceAuthenticator:
    """Tests for the ServiceAuthenticator validation logic."""

    @pytest.fixture
    def authenticator(self) -> ServiceAuthenticator:
        """Create authenticator with known test keys."""
        return ServiceAuthenticator(
            valid_keys={
                "agent-eval": hashlib.sha256(b"secret-key-eval").hexdigest(),
                "llm-gateway": hashlib.sha256(b"secret-key-gateway").hexdigest(),
            }
        )

    def test_valid_key_returns_true(self, authenticator):
        result = authenticator.validate("agent-eval", "secret-key-eval")
        assert result is True

    def test_valid_key_different_service(self, authenticator):
        result = authenticator.validate("llm-gateway", "secret-key-gateway")
        assert result is True

    def test_invalid_key_returns_false(self, authenticator):
        result = authenticator.validate("agent-eval", "wrong-key")
        assert result is False

    def test_unknown_service_returns_false(self, authenticator):
        result = authenticator.validate("unknown-service", "any-key")
        assert result is False

    def test_empty_key_returns_false(self, authenticator):
        result = authenticator.validate("agent-eval", "")
        assert result is False

    def test_constant_time_comparison_used(self, authenticator):
        """Verify that hmac.compare_digest is used (not ==)."""
        with patch("common.auth.service_auth.hmac.compare_digest", return_value=True) as mock_cmp:
            authenticator.validate("agent-eval", "secret-key-eval")
            assert mock_cmp.called

    def test_key_hashed_with_sha256(self, authenticator):
        """Verify that the provided key is SHA-256 hashed before comparison."""
        with patch("common.auth.service_auth.hashlib.sha256") as mock_sha:
            mock_sha.return_value.hexdigest.return_value = "fakehash"
            authenticator.validate("agent-eval", "test-input")
            mock_sha.assert_called_once_with(b"test-input")


class TestVerifyServiceDependency:
    """Tests for the verify_service FastAPI dependency."""

    @pytest.fixture
    def app_with_auth(self) -> FastAPI:
        """FastAPI app with service authenticator configured."""
        app = FastAPI()
        app.state.service_authenticator = ServiceAuthenticator(
            valid_keys={
                "agent-eval": hashlib.sha256(b"good-key").hexdigest(),
            }
        )

        @app.get("/internal/data")
        async def internal_endpoint(identity: ServiceIdentity = Depends(verify_service)):
            return {
                "service_id": identity.service_id,
                "tenant_id": identity.tenant_id,
                "trace_id": identity.trace_id,
            }

        return app

    @pytest.fixture
    def app_no_auth(self) -> FastAPI:
        """FastAPI app without authenticator (development mode)."""
        app = FastAPI()

        @app.get("/internal/data")
        async def internal_endpoint(identity: ServiceIdentity = Depends(verify_service)):
            return {"service_id": identity.service_id}

        return app

    @pytest.mark.asyncio
    async def test_valid_credentials(self, app_with_auth):
        transport = ASGITransport(app=app_with_auth)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/internal/data",
                headers={
                    "X-Service-Id": "agent-eval",
                    "X-Service-Key": "good-key",
                    "X-Tenant-Id": "tenant-1",
                    "X-Trace-Id": "trace-abc",
                },
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["service_id"] == "agent-eval"
        assert data["tenant_id"] == "tenant-1"
        assert data["trace_id"] == "trace-abc"

    @pytest.mark.asyncio
    async def test_invalid_credentials_returns_401(self, app_with_auth):
        transport = ASGITransport(app=app_with_auth)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/internal/data",
                headers={
                    "X-Service-Id": "agent-eval",
                    "X-Service-Key": "wrong-key",
                },
            )
        assert resp.status_code == 401
        assert "Invalid service credentials" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_missing_service_id_returns_422(self, app_with_auth):
        """Missing required header returns 422 from FastAPI validation."""
        transport = ASGITransport(app=app_with_auth)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/internal/data",
                headers={"X-Service-Key": "good-key"},
            )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_empty_service_id_returns_400(self, app_with_auth):
        transport = ASGITransport(app=app_with_auth)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/internal/data",
                headers={
                    "X-Service-Id": "   ",
                    "X-Service-Key": "good-key",
                },
            )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_empty_service_key_returns_400(self, app_with_auth):
        transport = ASGITransport(app=app_with_auth)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/internal/data",
                headers={
                    "X-Service-Id": "agent-eval",
                    "X-Service-Key": "  ",
                },
            )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_no_authenticator_allows_pass_through(self, app_no_auth):
        """Without authenticator on app.state, credentials pass through (dev mode)."""
        transport = ASGITransport(app=app_no_auth)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/internal/data",
                headers={
                    "X-Service-Id": "any-service",
                    "X-Service-Key": "any-key",
                },
            )
        assert resp.status_code == 200
        assert resp.json()["service_id"] == "any-service"


class TestServiceIdentity:
    """Tests for the ServiceIdentity dataclass."""

    def test_basic_construction(self):
        identity = ServiceIdentity(service_id="test-svc")
        assert identity.service_id == "test-svc"
        assert identity.tenant_id is None
        assert identity.trace_id is None

    def test_full_construction(self):
        identity = ServiceIdentity(
            service_id="my-svc",
            tenant_id="t-1",
            trace_id="tr-abc",
        )
        assert identity.service_id == "my-svc"
        assert identity.tenant_id == "t-1"
        assert identity.trace_id == "tr-abc"

    def test_immutable(self):
        identity = ServiceIdentity(service_id="test")
        with pytest.raises(Exception):  # frozen=True raises FrozenInstanceError
            identity.service_id = "changed"  # type: ignore[misc]
