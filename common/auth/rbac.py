"""Role-based access control (RBAC) dependencies for FastAPI.

Provides FastAPI dependency functions for:
- Extracting and validating the current user from a Bearer token.
- Enforcing role-based access (admin, analyst, contributor, auditor).
- Fine-grained scope checks (contributors limited to own resources).

Usage:
    from common.auth.rbac import get_current_user, require_role, require_scope

    @app.get("/admin-only")
    async def admin_endpoint(user: UserContext = Depends(require_role("admin"))):
        ...

    @app.get("/controls/{control_id}")
    async def get_control(
        control_id: str,
        user: UserContext = Depends(require_scope("control")),
    ):
        ...
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from common.auth.cognito import CognitoTokenValidator, UserContext
from common.errors import AuthenticationError

security = HTTPBearer(auto_error=True)


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> UserContext:
    """Extract and validate the current user from the Bearer token.

    Retrieves the CognitoTokenValidator from request.app.state.token_validator
    and validates the token. Returns the authenticated UserContext.

    Args:
        request: FastAPI request object (provides access to app.state).
        credentials: Bearer token extracted by HTTPBearer security scheme.

    Returns:
        Validated UserContext with user identity and claims.

    Raises:
        HTTPException(401): Token is invalid, expired, or malformed.
        HTTPException(403): Token valid but missing tenant_id claim.
    """
    validator: CognitoTokenValidator | None = getattr(
        request.app.state, "token_validator", None
    )

    if validator is None:
        raise HTTPException(
            status_code=500,
            detail="Token validator not configured",
        )

    try:
        user = await validator.validate(credentials.credentials)
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=401,
            detail=f"Authentication failed: {exc.message}",
        ) from exc

    if not user.tenant_id:
        raise HTTPException(
            status_code=403,
            detail="Token missing tenant context",
        )

    return user


def require_role(
    *allowed_roles: str,
) -> Callable[..., Coroutine[Any, Any, UserContext]]:
    """Create a dependency that enforces role membership.

    Returns a FastAPI dependency function that first authenticates the user
    via get_current_user, then checks that their role is in the allowed set.

    Args:
        *allowed_roles: One or more role names that are permitted access.

    Returns:
        Async dependency function returning UserContext if authorized.

    Raises:
        HTTPException(403): User's role is not in the allowed set.

    Example:
        @app.delete("/tenant/{tenant_id}")
        async def delete_tenant(
            tenant_id: str,
            user: UserContext = Depends(require_role("admin")),
        ):
            ...
    """
    roles_set = frozenset(allowed_roles)

    async def _check_role(
        user: UserContext = Depends(get_current_user),
    ) -> UserContext:
        if user.role not in roles_set:
            raise HTTPException(
                status_code=403,
                detail=(
                    f"Role '{user.role}' not permitted. "
                    f"Required: {sorted(roles_set)}"
                ),
            )
        return user

    return _check_role


def require_scope(
    resource_type: str,
) -> Callable[..., Coroutine[Any, Any, UserContext]]:
    """Create a dependency for fine-grained resource scope checks.

    Enforces that contributors can only access resources they own.
    Admin and analyst roles have full access. Auditors have read-only
    access (enforced at the route level). Contributors are restricted
    to resources where the owner_id matches their user_id.

    The dependency checks for an 'owner_id' path parameter or query
    parameter. If present and the user is a contributor, it must match
    the user's ID.

    Args:
        resource_type: The type of resource being accessed (for error messages).

    Returns:
        Async dependency function returning UserContext if authorized.

    Raises:
        HTTPException(403): Contributor attempting to access another user's resource.

    Example:
        @app.get("/evaluations/{evaluation_id}")
        async def get_evaluation(
            evaluation_id: str,
            user: UserContext = Depends(require_scope("evaluation")),
        ):
            ...
    """
    # Roles with unrestricted access to all resources
    unrestricted_roles = frozenset({"admin", "analyst", "auditor"})

    async def _check_scope(
        request: Request,
        user: UserContext = Depends(get_current_user),
    ) -> UserContext:
        # Admin, analyst, and auditor have unrestricted access
        if user.role in unrestricted_roles:
            return user

        # Contributors: check owner_id if present
        owner_id: str | None = request.path_params.get("owner_id")
        if owner_id is None:
            owner_id = request.query_params.get("owner_id")

        if owner_id is not None and owner_id != user.user_id:
            raise HTTPException(
                status_code=403,
                detail=(
                    f"Access denied: contributors can only access their own "
                    f"{resource_type} resources"
                ),
            )

        return user

    return _check_scope
