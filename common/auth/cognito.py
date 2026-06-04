"""Cognito JWT token validation for user authentication.

Validates RS256-signed JWTs issued by AWS Cognito User Pools. Caches
JWKS keys for 1 hour to minimize network calls. Extracts tenant context
from custom claims (custom:tenant_id, custom:role).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx
from jose import jwt, JWTError

from common.errors import AuthenticationError

_JWKS_CACHE_TTL_SECONDS: int = 3600  # 1 hour


@dataclass(frozen=True)
class UserContext:
    """Authenticated user identity extracted from a validated JWT.

    Attributes:
        user_id: Cognito 'sub' claim (UUID).
        tenant_id: Custom claim 'custom:tenant_id'.
        role: Custom claim 'custom:role' (admin, analyst, contributor, auditor).
        email: Verified email from the token.
        groups: Cognito group memberships.
        token_exp: Token expiration timestamp (UTC).
    """

    user_id: str
    tenant_id: str
    role: str
    email: str
    groups: list[str] = field(default_factory=list)
    token_exp: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))


class CognitoTokenValidator:
    """Validates Cognito-issued JWTs against the User Pool JWKS endpoint.

    Usage:
        validator = CognitoTokenValidator(
            region="us-east-1",
            user_pool_id="us-east-1_abc123",
            client_id="7s4xg2...",
        )
        user = await validator.validate(token)
    """

    def __init__(self, region: str, user_pool_id: str, client_id: str) -> None:
        self._issuer: str = (
            f"https://cognito-idp.{region}.amazonaws.com/{user_pool_id}"
        )
        self._jwks_url: str = f"{self._issuer}/.well-known/jwks.json"
        self._client_id: str = client_id
        self._jwks_cache: dict[str, dict] | None = None
        self._jwks_fetched_at: float = 0.0

    async def validate(self, token: str) -> UserContext:
        """Validate a JWT and return the authenticated user context.

        Steps:
            1. Decode the JWT header to extract the key ID (kid).
            2. Retrieve the matching signing key from the cached JWKS.
            3. Verify the signature (RS256), expiration, issuer, and audience.
            4. Extract identity claims into a UserContext.

        Args:
            token: Raw JWT string from the Authorization header.

        Returns:
            UserContext with verified claims.

        Raises:
            AuthenticationError: Token is malformed, expired, or signature invalid.
        """
        try:
            unverified_header = jwt.get_unverified_header(token)
        except JWTError as exc:
            raise AuthenticationError(
                "Malformed token header", detail=str(exc)
            ) from exc

        kid: str | None = unverified_header.get("kid")
        if not kid:
            raise AuthenticationError("Token header missing 'kid' claim")

        signing_key = await self._get_signing_key(kid)

        try:
            payload: dict = jwt.decode(
                token,
                signing_key,
                algorithms=["RS256"],
                audience=self._client_id,
                issuer=self._issuer,
                options={
                    "verify_exp": True,
                    "verify_iss": True,
                    "verify_aud": True,
                    "verify_at_hash": False,
                },
            )
        except JWTError as exc:
            raise AuthenticationError(
                "Token verification failed", detail=str(exc)
            ) from exc

        # Extract required claims
        user_id: str | None = payload.get("sub")
        if not user_id:
            raise AuthenticationError("Token missing 'sub' claim")

        tenant_id: str | None = payload.get("custom:tenant_id")
        if not tenant_id:
            raise AuthenticationError("Token missing 'custom:tenant_id' claim")

        role: str = payload.get("custom:role", "contributor")
        email: str = payload.get("email", "")
        groups: list[str] = payload.get("cognito:groups", [])

        exp_timestamp: int | None = payload.get("exp")
        if exp_timestamp is not None:
            token_exp = datetime.fromtimestamp(exp_timestamp, tz=timezone.utc)
        else:
            token_exp = datetime.now(tz=timezone.utc)

        return UserContext(
            user_id=user_id,
            tenant_id=tenant_id,
            role=role,
            email=email,
            groups=groups,
            token_exp=token_exp,
        )

    async def _get_signing_key(self, kid: str) -> dict:
        """Retrieve the signing key matching the given key ID.

        Fetches JWKS from Cognito if the cache is empty or has expired
        (1 hour TTL). Uses httpx async client for the network call.

        Args:
            kid: Key ID from the JWT header.

        Returns:
            JWK dict suitable for jose.jwt.decode().

        Raises:
            AuthenticationError: If the key ID is not found in JWKS or fetch fails.
        """
        now = time.monotonic()
        cache_expired = (now - self._jwks_fetched_at) > _JWKS_CACHE_TTL_SECONDS

        if self._jwks_cache is None or cache_expired:
            await self._refresh_jwks()

        assert self._jwks_cache is not None  # noqa: S101

        key = self._jwks_cache.get(kid)
        if key is None:
            # Key rotation may have occurred; try one more refresh
            await self._refresh_jwks()
            key = self._jwks_cache.get(kid)
            if key is None:
                raise AuthenticationError(
                    "Signing key not found in JWKS",
                    kid=kid,
                )
        return key

    async def _refresh_jwks(self) -> None:
        """Fetch JWKS from Cognito and rebuild the key cache.

        Raises:
            AuthenticationError: If the HTTP request fails or response is invalid.
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(self._jwks_url)
                response.raise_for_status()
                jwks_data = response.json()
        except httpx.HTTPError as exc:
            raise AuthenticationError(
                "Failed to fetch JWKS", url=self._jwks_url, detail=str(exc)
            ) from exc

        keys = jwks_data.get("keys")
        if not keys:
            raise AuthenticationError(
                "JWKS response missing 'keys'", url=self._jwks_url
            )

        self._jwks_cache = {k["kid"]: k for k in keys if "kid" in k}
        self._jwks_fetched_at = time.monotonic()
