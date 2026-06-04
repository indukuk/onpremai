"""Tests for common.middleware trace ID, tenant context, and request logging."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient

from common.middleware import (
    RequestLoggingMiddleware,
    TenantContextMiddleware,
    TraceIdMiddleware,
)


def _create_app_with_middleware() -> FastAPI:
    """Create a test FastAPI app with all three middleware layers."""
    app = FastAPI()

    # Order matters: add in reverse (LIFO processing)
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(TenantContextMiddleware)
    app.add_middleware(TraceIdMiddleware)

    @app.get("/echo")
    async def echo(request: Request):
        return {
            "trace_id": getattr(request.state, "trace_id", None),
            "tenant_id": getattr(request.state, "tenant_id", None),
        }

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


class TestTraceIdMiddleware:
    """Test trace ID generation and propagation."""

    @pytest.mark.asyncio
    async def test_generates_trace_id_when_not_provided(self):
        app = _create_app_with_middleware()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/echo")

        assert resp.status_code == 200
        # Response should have X-Trace-Id header
        trace_id = resp.headers.get("X-Trace-Id")
        assert trace_id is not None
        # Should be a valid UUID
        uuid.UUID(trace_id)

    @pytest.mark.asyncio
    async def test_uses_provided_trace_id(self):
        app = _create_app_with_middleware()
        transport = ASGITransport(app=app)

        custom_trace_id = "my-custom-trace-123"
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/echo",
                headers={"X-Trace-Id": custom_trace_id},
            )

        assert resp.status_code == 200
        assert resp.headers["X-Trace-Id"] == custom_trace_id
        assert resp.json()["trace_id"] == custom_trace_id

    @pytest.mark.asyncio
    async def test_trace_id_available_in_request_state(self):
        app = _create_app_with_middleware()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/echo",
                headers={"X-Trace-Id": "trace-abc"},
            )

        data = resp.json()
        assert data["trace_id"] == "trace-abc"


class TestTenantContextMiddleware:
    """Test tenant extraction from headers and JWT."""

    @pytest.mark.asyncio
    async def test_extracts_tenant_from_header(self):
        app = _create_app_with_middleware()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/echo",
                headers={
                    "X-Tenant-Id": "tenant-xyz",
                    "X-Service-Id": "agent-eval",
                    "X-Service-Key": "test-key",
                },
            )

        assert resp.status_code == 200
        assert resp.json()["tenant_id"] == "tenant-xyz"

    @pytest.mark.asyncio
    async def test_no_tenant_sets_empty_string(self):
        app = _create_app_with_middleware()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/echo")

        assert resp.status_code == 200
        assert resp.json()["tenant_id"] == ""

    @pytest.mark.asyncio
    async def test_extracts_tenant_from_jwt_payload(self):
        """Test that tenant is extracted from JWT token payload."""
        import base64
        import json

        # Create a fake JWT with tenant_id in the payload
        header = base64.urlsafe_b64encode(json.dumps({"alg": "RS256"}).encode()).rstrip(b"=")
        payload = base64.urlsafe_b64encode(
            json.dumps({"custom:tenant_id": "jwt-tenant-999"}).encode()
        ).rstrip(b"=")
        signature = base64.urlsafe_b64encode(b"fakesig").rstrip(b"=")
        fake_jwt = f"{header.decode()}.{payload.decode()}.{signature.decode()}"

        app = _create_app_with_middleware()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/echo",
                headers={"Authorization": f"Bearer {fake_jwt}"},
            )

        assert resp.status_code == 200
        assert resp.json()["tenant_id"] == "jwt-tenant-999"

    @pytest.mark.asyncio
    async def test_header_takes_priority_over_jwt(self):
        """X-Tenant-Id header fallback is used when no prior claims exist."""
        import base64
        import json

        # JWT without tenant_id
        header = base64.urlsafe_b64encode(json.dumps({"alg": "RS256"}).encode()).rstrip(b"=")
        payload = base64.urlsafe_b64encode(
            json.dumps({"sub": "user-1"}).encode()
        ).rstrip(b"=")
        signature = base64.urlsafe_b64encode(b"sig").rstrip(b"=")
        fake_jwt = f"{header.decode()}.{payload.decode()}.{signature.decode()}"

        app = _create_app_with_middleware()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/echo",
                headers={
                    "Authorization": f"Bearer {fake_jwt}",
                    "X-Tenant-Id": "header-tenant",
                    "X-Service-Id": "agent-eval",
                    "X-Service-Key": "test-key",
                },
            )

        assert resp.status_code == 200
        assert resp.json()["tenant_id"] == "header-tenant"


class TestRequestLoggingMiddleware:
    """Test request logging behavior."""

    @pytest.mark.asyncio
    async def test_health_endpoint_skipped(self):
        """Health check endpoints are not logged."""
        app = _create_app_with_middleware()
        transport = ASGITransport(app=app)

        with patch("common.middleware.logger") as mock_logger:
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/health")

            assert resp.status_code == 200
            # Logger should NOT have been called for /health
            mock_logger.info.assert_not_called()
            mock_logger.warning.assert_not_called()
            mock_logger.error.assert_not_called()

    @pytest.mark.asyncio
    async def test_normal_request_logged(self):
        """Normal endpoints generate a log entry."""
        app = _create_app_with_middleware()
        transport = ASGITransport(app=app)

        with patch("common.middleware.logger") as mock_logger:
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/echo")

            assert resp.status_code == 200
            mock_logger.info.assert_called_once()
            log_kwargs = mock_logger.info.call_args.kwargs
            assert log_kwargs["method"] == "GET"
            assert log_kwargs["path"] == "/echo"
            assert log_kwargs["status"] == 200
            assert "duration_ms" in log_kwargs

    @pytest.mark.asyncio
    async def test_404_logged_as_warning(self):
        """4xx responses are logged at warning level."""
        app = _create_app_with_middleware()
        transport = ASGITransport(app=app)

        with patch("common.middleware.logger") as mock_logger:
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/nonexistent")

            assert resp.status_code == 404
            mock_logger.warning.assert_called_once()

    @pytest.mark.asyncio
    async def test_skip_paths_include_common_health_endpoints(self):
        """Verify the SKIP_PATHS set."""
        assert "/health" in RequestLoggingMiddleware.SKIP_PATHS
        assert "/ready" in RequestLoggingMiddleware.SKIP_PATHS
        assert "/healthz" in RequestLoggingMiddleware.SKIP_PATHS
        assert "/readyz" in RequestLoggingMiddleware.SKIP_PATHS


class TestCustomHeaderName:
    """Test middleware with custom header names."""

    @pytest.mark.asyncio
    async def test_custom_trace_header_name(self):
        app = FastAPI()
        app.add_middleware(TraceIdMiddleware, header_name="X-Request-Id")

        @app.get("/test")
        async def test_route(request: Request):
            return {"trace_id": request.state.trace_id}

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/test",
                headers={"X-Request-Id": "custom-id-456"},
            )

        assert resp.status_code == 200
        assert resp.json()["trace_id"] == "custom-id-456"
        assert resp.headers["X-Request-Id"] == "custom-id-456"
