"""Tests for common.auth.cognito CognitoTokenValidator."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from common.auth.cognito import CognitoTokenValidator, UserContext
from common.errors import AuthenticationError


@pytest.fixture
def validator() -> CognitoTokenValidator:
    """Create a CognitoTokenValidator with test config."""
    return CognitoTokenValidator(
        region="us-east-1",
        user_pool_id="us-east-1_TestPool",
        client_id="test-client-id",
    )


@pytest.fixture
def valid_payload() -> dict:
    """A payload representing a valid decoded JWT."""
    return {
        "sub": "user-uuid-123",
        "custom:tenant_id": "tenant-abc",
        "custom:role": "analyst",
        "email": "analyst@corp.com",
        "cognito:groups": ["compliance-team"],
        "exp": 4102444800,  # 2100-01-01
        "iss": "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_TestPool",
        "aud": "test-client-id",
    }


@pytest.fixture
def jwks_response() -> dict:
    """Fake JWKS response."""
    return {
        "keys": [
            {"kid": "test-kid-1", "kty": "RSA", "n": "abc", "e": "AQAB"},
            {"kid": "test-kid-2", "kty": "RSA", "n": "def", "e": "AQAB"},
        ]
    }


class TestCognitoTokenValidatorInit:
    """Test validator construction."""

    def test_issuer_url_constructed_correctly(self, validator):
        expected = "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_TestPool"
        assert validator._issuer == expected

    def test_jwks_url_constructed_correctly(self, validator):
        expected = "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_TestPool/.well-known/jwks.json"
        assert validator._jwks_url == expected

    def test_cache_initially_empty(self, validator):
        assert validator._jwks_cache is None


class TestValidToken:
    """Test successful token validation."""

    @pytest.mark.asyncio
    async def test_valid_token_returns_user_context(self, validator, valid_payload, jwks_response):
        fake_token = "header.payload.signature"

        with patch("common.auth.cognito.jwt") as mock_jwt:
            mock_jwt.get_unverified_header.return_value = {"kid": "test-kid-1", "alg": "RS256"}
            mock_jwt.decode.return_value = valid_payload

            # Mock JWKS fetch
            mock_response = MagicMock()
            mock_response.json.return_value = jwks_response
            mock_response.raise_for_status = MagicMock()

            with patch("common.auth.cognito.httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.get = AsyncMock(return_value=mock_response)
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=None)
                mock_client_cls.return_value = mock_client

                user = await validator.validate(fake_token)

        assert isinstance(user, UserContext)
        assert user.user_id == "user-uuid-123"
        assert user.tenant_id == "tenant-abc"
        assert user.role == "analyst"
        assert user.email == "analyst@corp.com"
        assert user.groups == ["compliance-team"]
        assert user.token_exp == datetime(2100, 1, 1, tzinfo=timezone.utc)

    @pytest.mark.asyncio
    async def test_default_role_is_contributor(self, validator, valid_payload, jwks_response):
        """If custom:role not in token, defaults to 'contributor'."""
        del valid_payload["custom:role"]
        fake_token = "header.payload.signature"

        with patch("common.auth.cognito.jwt") as mock_jwt:
            mock_jwt.get_unverified_header.return_value = {"kid": "test-kid-1", "alg": "RS256"}
            mock_jwt.decode.return_value = valid_payload

            mock_response = MagicMock()
            mock_response.json.return_value = jwks_response
            mock_response.raise_for_status = MagicMock()

            with patch("common.auth.cognito.httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.get = AsyncMock(return_value=mock_response)
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=None)
                mock_client_cls.return_value = mock_client

                user = await validator.validate(fake_token)

        assert user.role == "contributor"


class TestExpiredToken:
    """Test expired token handling."""

    @pytest.mark.asyncio
    async def test_expired_token_raises_auth_error(self, validator, jwks_response):
        from jose import JWTError

        fake_token = "header.payload.signature"

        with patch("common.auth.cognito.jwt") as mock_jwt:
            mock_jwt.get_unverified_header.return_value = {"kid": "test-kid-1", "alg": "RS256"}
            mock_jwt.decode.side_effect = JWTError("Signature has expired")

            mock_response = MagicMock()
            mock_response.json.return_value = jwks_response
            mock_response.raise_for_status = MagicMock()

            with patch("common.auth.cognito.httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.get = AsyncMock(return_value=mock_response)
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=None)
                mock_client_cls.return_value = mock_client

                with pytest.raises(AuthenticationError, match="Token verification failed"):
                    await validator.validate(fake_token)


class TestWrongIssuer:
    """Test wrong issuer handling."""

    @pytest.mark.asyncio
    async def test_wrong_issuer_raises_auth_error(self, validator, jwks_response):
        from jose import JWTError

        fake_token = "header.payload.signature"

        with patch("common.auth.cognito.jwt") as mock_jwt:
            mock_jwt.get_unverified_header.return_value = {"kid": "test-kid-1", "alg": "RS256"}
            mock_jwt.decode.side_effect = JWTError("Invalid issuer")

            mock_response = MagicMock()
            mock_response.json.return_value = jwks_response
            mock_response.raise_for_status = MagicMock()

            with patch("common.auth.cognito.httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.get = AsyncMock(return_value=mock_response)
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=None)
                mock_client_cls.return_value = mock_client

                with pytest.raises(AuthenticationError, match="Token verification failed"):
                    await validator.validate(fake_token)


class TestMissingKid:
    """Test missing key ID in token header."""

    @pytest.mark.asyncio
    async def test_missing_kid_raises_auth_error(self, validator):
        fake_token = "header.payload.signature"

        with patch("common.auth.cognito.jwt") as mock_jwt:
            mock_jwt.get_unverified_header.return_value = {"alg": "RS256"}

            with pytest.raises(AuthenticationError, match="missing 'kid' claim"):
                await validator.validate(fake_token)

    @pytest.mark.asyncio
    async def test_malformed_header_raises_auth_error(self, validator):
        from jose import JWTError

        fake_token = "not-a-valid-jwt"

        with patch("common.auth.cognito.jwt") as mock_jwt:
            mock_jwt.get_unverified_header.side_effect = JWTError("Invalid header")

            with pytest.raises(AuthenticationError, match="Malformed token header"):
                await validator.validate(fake_token)


class TestJWKSFetch:
    """Test JWKS cache and fetch behavior."""

    @pytest.mark.asyncio
    async def test_kid_not_found_raises_auth_error(self, validator, jwks_response):
        """Token has kid not in JWKS."""
        fake_token = "header.payload.signature"

        with patch("common.auth.cognito.jwt") as mock_jwt:
            mock_jwt.get_unverified_header.return_value = {"kid": "unknown-kid", "alg": "RS256"}

            mock_response = MagicMock()
            mock_response.json.return_value = jwks_response
            mock_response.raise_for_status = MagicMock()

            with patch("common.auth.cognito.httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.get = AsyncMock(return_value=mock_response)
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=None)
                mock_client_cls.return_value = mock_client

                with pytest.raises(AuthenticationError, match="Signing key not found"):
                    await validator.validate(fake_token)

    @pytest.mark.asyncio
    async def test_jwks_fetch_failure_raises_auth_error(self, validator):
        """Network failure fetching JWKS."""
        import httpx

        fake_token = "header.payload.signature"

        with patch("common.auth.cognito.jwt") as mock_jwt:
            mock_jwt.get_unverified_header.return_value = {"kid": "test-kid-1", "alg": "RS256"}

            with patch("common.auth.cognito.httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.get = AsyncMock(
                    side_effect=httpx.ConnectError("connection refused")
                )
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=None)
                mock_client_cls.return_value = mock_client

                with pytest.raises(AuthenticationError, match="Failed to fetch JWKS"):
                    await validator.validate(fake_token)


class TestMissingClaims:
    """Test missing required claims."""

    @pytest.mark.asyncio
    async def test_missing_sub_raises_auth_error(self, validator, jwks_response):
        payload_no_sub = {
            "custom:tenant_id": "tenant-abc",
            "custom:role": "analyst",
            "email": "a@b.com",
            "cognito:groups": [],
            "exp": 4102444800,
        }
        fake_token = "header.payload.signature"

        with patch("common.auth.cognito.jwt") as mock_jwt:
            mock_jwt.get_unverified_header.return_value = {"kid": "test-kid-1", "alg": "RS256"}
            mock_jwt.decode.return_value = payload_no_sub

            mock_response = MagicMock()
            mock_response.json.return_value = jwks_response
            mock_response.raise_for_status = MagicMock()

            with patch("common.auth.cognito.httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.get = AsyncMock(return_value=mock_response)
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=None)
                mock_client_cls.return_value = mock_client

                with pytest.raises(AuthenticationError, match="missing 'sub' claim"):
                    await validator.validate(fake_token)

    @pytest.mark.asyncio
    async def test_missing_tenant_id_raises_auth_error(self, validator, jwks_response):
        payload_no_tenant = {
            "sub": "user-uuid-123",
            "custom:role": "analyst",
            "email": "a@b.com",
            "cognito:groups": [],
            "exp": 4102444800,
        }
        fake_token = "header.payload.signature"

        with patch("common.auth.cognito.jwt") as mock_jwt:
            mock_jwt.get_unverified_header.return_value = {"kid": "test-kid-1", "alg": "RS256"}
            mock_jwt.decode.return_value = payload_no_tenant

            mock_response = MagicMock()
            mock_response.json.return_value = jwks_response
            mock_response.raise_for_status = MagicMock()

            with patch("common.auth.cognito.httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.get = AsyncMock(return_value=mock_response)
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=None)
                mock_client_cls.return_value = mock_client

                with pytest.raises(AuthenticationError, match="missing 'custom:tenant_id' claim"):
                    await validator.validate(fake_token)
