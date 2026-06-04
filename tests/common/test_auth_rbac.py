"""Tests for common.auth.rbac role-based access control."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from common.auth.cognito import CognitoTokenValidator, UserContext
from common.auth.rbac import get_current_user, require_role, require_scope
from common.errors import AuthenticationError


def _make_app_with_role_check(*roles: str) -> FastAPI:
    """Create a FastAPI app with a route protected by require_role."""
    app = FastAPI()

    @app.get("/protected")
    async def protected(user: UserContext = Depends(require_role(*roles))):
        return {"user_id": user.user_id, "role": user.role}

    return app


def _make_app_with_scope_check(resource_type: str) -> FastAPI:
    """Create a FastAPI app with a route protected by require_scope."""
    app = FastAPI()

    @app.get("/resources/{owner_id}")
    async def scoped_resource(
        owner_id: str,
        user: UserContext = Depends(require_scope(resource_type)),
    ):
        return {"user_id": user.user_id, "owner_id": owner_id}

    return app


def _setup_mock_validator(app: FastAPI, user: UserContext) -> None:
    """Attach a mock token validator that returns the given user."""
    mock_validator = AsyncMock(spec=CognitoTokenValidator)
    mock_validator.validate = AsyncMock(return_value=user)
    app.state.token_validator = mock_validator


class TestRequireRolePass:
    """Test require_role when user has a permitted role."""

    @pytest.mark.asyncio
    async def test_admin_passes_admin_check(self, fake_admin_context):
        app = _make_app_with_role_check("admin")
        _setup_mock_validator(app, fake_admin_context)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/protected",
                headers={"Authorization": "Bearer fake-token"},
            )
        assert resp.status_code == 200
        assert resp.json()["role"] == "admin"

    @pytest.mark.asyncio
    async def test_analyst_passes_multi_role_check(self, fake_user_context):
        app = _make_app_with_role_check("admin", "analyst")
        _setup_mock_validator(app, fake_user_context)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/protected",
                headers={"Authorization": "Bearer fake-token"},
            )
        assert resp.status_code == 200
        assert resp.json()["role"] == "analyst"


class TestRequireRoleFail:
    """Test require_role when user lacks permission."""

    @pytest.mark.asyncio
    async def test_contributor_denied_admin_only(self, fake_contributor_context):
        app = _make_app_with_role_check("admin")
        _setup_mock_validator(app, fake_contributor_context)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/protected",
                headers={"Authorization": "Bearer fake-token"},
            )
        assert resp.status_code == 403
        assert "not permitted" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_analyst_denied_admin_only(self, fake_user_context):
        app = _make_app_with_role_check("admin")
        _setup_mock_validator(app, fake_user_context)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/protected",
                headers={"Authorization": "Bearer fake-token"},
            )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_invalid_token_returns_401(self):
        app = _make_app_with_role_check("admin")
        mock_validator = AsyncMock(spec=CognitoTokenValidator)
        mock_validator.validate = AsyncMock(
            side_effect=AuthenticationError("Token expired")
        )
        app.state.token_validator = mock_validator

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/protected",
                headers={"Authorization": "Bearer expired-token"},
            )
        assert resp.status_code == 401
        assert "Authentication failed" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_no_token_validator_returns_500(self):
        app = _make_app_with_role_check("admin")
        # Intentionally do not set token_validator on app.state

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/protected",
                headers={"Authorization": "Bearer any-token"},
            )
        assert resp.status_code == 500
        assert "not configured" in resp.json()["detail"]


class TestRequireScopeContributor:
    """Test require_scope for contributor role (restricted to own resources)."""

    @pytest.mark.asyncio
    async def test_contributor_accesses_own_resource(self, fake_contributor_context):
        app = _make_app_with_scope_check("evaluation")
        _setup_mock_validator(app, fake_contributor_context)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # owner_id matches user_id
            resp = await client.get(
                f"/resources/{fake_contributor_context.user_id}",
                headers={"Authorization": "Bearer fake-token"},
            )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_contributor_denied_other_resource(self, fake_contributor_context):
        app = _make_app_with_scope_check("evaluation")
        _setup_mock_validator(app, fake_contributor_context)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # owner_id does NOT match user_id
            resp = await client.get(
                "/resources/other-user-uuid",
                headers={"Authorization": "Bearer fake-token"},
            )
        assert resp.status_code == 403
        assert "contributors can only access their own" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_admin_accesses_any_resource(self, fake_admin_context):
        app = _make_app_with_scope_check("evaluation")
        _setup_mock_validator(app, fake_admin_context)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/resources/any-user-id",
                headers={"Authorization": "Bearer fake-token"},
            )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_analyst_accesses_any_resource(self, fake_user_context):
        """Analyst role has unrestricted access."""
        app = _make_app_with_scope_check("evaluation")
        _setup_mock_validator(app, fake_user_context)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/resources/some-other-user",
                headers={"Authorization": "Bearer fake-token"},
            )
        assert resp.status_code == 200


class TestGetCurrentUser:
    """Test the get_current_user dependency."""

    @pytest.mark.asyncio
    async def test_missing_tenant_id_returns_403(self):
        """User with empty tenant_id gets 403."""
        user_no_tenant = UserContext(
            user_id="user-1",
            tenant_id="",
            role="analyst",
            email="a@b.com",
        )
        app = FastAPI()

        @app.get("/me")
        async def me(user: UserContext = Depends(get_current_user)):
            return {"user_id": user.user_id}

        mock_validator = AsyncMock(spec=CognitoTokenValidator)
        mock_validator.validate = AsyncMock(return_value=user_no_tenant)
        app.state.token_validator = mock_validator

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/me",
                headers={"Authorization": "Bearer fake-token"},
            )
        assert resp.status_code == 403
        assert "missing tenant context" in resp.json()["detail"]
