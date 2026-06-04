"""Service-to-service authentication via API keys.

Internal services authenticate using a shared-secret scheme:
- Each service has a unique service_id and API key.
- Keys are stored as SHA-256 hashes (never plaintext).
- Validation uses constant-time comparison to prevent timing attacks.

Usage in FastAPI:
    app.state.service_authenticator = ServiceAuthenticator(valid_keys={
        "llm-gateway": "sha256hex...",
        "agent-eval": "sha256hex...",
    })

    @app.get("/internal/health")
    async def health(identity: ServiceIdentity = Depends(verify_service)):
        return {"caller": identity.service_id}
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass

from fastapi import Header, HTTPException, Request


@dataclass(frozen=True)
class ServiceIdentity:
    """Authenticated service caller identity.

    Attributes:
        service_id: Unique identifier of the calling service.
        tenant_id: Optional tenant context forwarded with the request.
        trace_id: Optional distributed trace ID for observability.
    """

    service_id: str
    tenant_id: str | None = None
    trace_id: str | None = None


class ServiceAuthenticator:
    """Validates service API keys using SHA-256 hash comparison.

    Keys are never stored in plaintext. On initialization, provide a dict
    mapping service_id -> sha256 hex digest of the service's key.

    Example:
        auth = ServiceAuthenticator(valid_keys={
            "agent-eval": hashlib.sha256(b"secret-key").hexdigest(),
        })
        assert auth.validate("agent-eval", "secret-key") is True
    """

    def __init__(self, valid_keys: dict[str, str]) -> None:
        """Initialize with a mapping of service_id to SHA-256 hash of key.

        Args:
            valid_keys: Dict where keys are service IDs and values are
                        lowercase hex SHA-256 digests of the API keys.
        """
        self._valid_keys: dict[str, str] = valid_keys

    def validate(self, service_id: str, api_key: str) -> bool:
        """Validate an API key for the given service.

        Computes SHA-256 of the provided key and performs constant-time
        comparison against the stored hash.

        Args:
            service_id: The service claiming the identity.
            api_key: The plaintext API key provided by the caller.

        Returns:
            True if the key is valid for the given service_id, False otherwise.
        """
        stored_hash = self._valid_keys.get(service_id)
        if stored_hash is None:
            return False

        provided_hash = hashlib.sha256(api_key.encode("utf-8")).hexdigest()
        return hmac.compare_digest(provided_hash, stored_hash)


async def verify_service(
    request: Request,
    x_service_id: str = Header(..., description="Calling service identifier"),
    x_service_key: str = Header(..., description="Service API key"),
    x_tenant_id: str | None = Header(
        None, description="Tenant context for the request"
    ),
    x_trace_id: str | None = Header(
        None, description="Distributed trace ID"
    ),
) -> ServiceIdentity:
    """FastAPI dependency for service-to-service authentication.

    Retrieves the ServiceAuthenticator from app.state and validates
    the provided credentials. Falls back to format validation if
    no authenticator is configured (development mode).

    Args:
        request: FastAPI request (used to access app.state).
        x_service_id: Service identifier header.
        x_service_key: Service API key header.
        x_tenant_id: Optional tenant context header.
        x_trace_id: Optional trace ID header.

    Returns:
        ServiceIdentity with validated service context.

    Raises:
        HTTPException(401): If credentials are invalid.
        HTTPException(400): If required headers have invalid format.
    """
    # Validate header formats
    if not x_service_id or not x_service_id.strip():
        raise HTTPException(
            status_code=400,
            detail="X-Service-Id header must be non-empty",
        )

    if not x_service_key or not x_service_key.strip():
        raise HTTPException(
            status_code=400,
            detail="X-Service-Key header must be non-empty",
        )

    # Check if authenticator is available on app.state
    authenticator: ServiceAuthenticator | None = getattr(
        request.app.state, "service_authenticator", None
    )

    if authenticator is not None:
        if not authenticator.validate(x_service_id, x_service_key):
            raise HTTPException(
                status_code=401,
                detail="Invalid service credentials",
            )

    return ServiceIdentity(
        service_id=x_service_id.strip(),
        tenant_id=x_tenant_id.strip() if x_tenant_id else None,
        trace_id=x_trace_id.strip() if x_trace_id else None,
    )
