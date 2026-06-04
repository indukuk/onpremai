"""Authentication and authorization package for the common library.

Exports:
    - UserContext: Authenticated user identity from JWT.
    - CognitoTokenValidator: Validates Cognito JWTs against JWKS.
    - ServiceIdentity: Authenticated inter-service caller identity.
    - ServiceAuthenticator: Validates service-to-service API keys.
    - verify_service: FastAPI dependency for service auth.
    - get_current_user: FastAPI dependency extracting user from Bearer token.
    - require_role: Factory for role-checking FastAPI dependencies.
    - require_scope: Factory for resource-scope FastAPI dependencies.
    - security: HTTPBearer security scheme instance.
"""

from __future__ import annotations

from common.auth.cognito import CognitoTokenValidator, UserContext
from common.auth.rbac import get_current_user, require_role, require_scope, security
from common.auth.service_auth import (
    ServiceAuthenticator,
    ServiceIdentity,
    verify_service,
)

__all__: list[str] = [
    "CognitoTokenValidator",
    "ServiceAuthenticator",
    "ServiceIdentity",
    "UserContext",
    "get_current_user",
    "require_role",
    "require_scope",
    "security",
    "verify_service",
]
