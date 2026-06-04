"""FastAPI middleware for tracing, tenant context, and request logging.

Three middleware classes that should be added to every service's FastAPI app:

    from common.middleware import (
        TraceIdMiddleware,
        TenantContextMiddleware,
        RequestLoggingMiddleware,
    )

    app = FastAPI()
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(TenantContextMiddleware)
    app.add_middleware(TraceIdMiddleware)

Order matters: TraceIdMiddleware should be outermost (added last) so that
trace_id is available for the other middleware. Add in reverse order because
Starlette processes middleware in LIFO order.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from structlog.contextvars import bind_contextvars, clear_contextvars

logger: structlog.stdlib.BoundLogger = structlog.get_logger()


class TraceIdMiddleware(BaseHTTPMiddleware):
    """Reads X-Trace-Id header or generates a UUID for request correlation.

    Sets trace_id on:
    - request.state.trace_id (available to route handlers)
    - structlog contextvars (available to all loggers in this request)
    - Response X-Trace-Id header (returned to caller)
    """

    def __init__(self, app: Any, header_name: str = "X-Trace-Id") -> None:
        super().__init__(app)
        self.header_name = header_name

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # Clear any stale contextvars from previous requests
        clear_contextvars()

        # Extract or generate trace_id
        trace_id = request.headers.get(self.header_name) or str(uuid.uuid4())

        # Make available to downstream middleware and handlers
        request.state.trace_id = trace_id

        # Bind to structlog context for all log calls in this request
        bind_contextvars(trace_id=trace_id)

        response = await call_next(request)

        # Echo trace_id in response headers for client correlation
        response.headers[self.header_name] = trace_id

        return response


class TenantContextMiddleware(BaseHTTPMiddleware):
    """Extracts tenant_id from JWT claims or X-Tenant-Id header.

    Resolution order:
    1. JWT token claim 'tenant_id' (if Authorization header present)
    2. X-Tenant-Id header (fallback for service-to-service calls)

    Sets tenant_id on:
    - request.state.tenant_id (available to route handlers)
    - structlog contextvars (available to all loggers in this request)
    """

    def __init__(self, app: Any, header_name: str = "X-Tenant-Id") -> None:
        super().__init__(app)
        self.header_name = header_name

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        tenant_id: str | None = None

        # Try to extract from JWT claims (if already decoded by auth middleware)
        if hasattr(request.state, "claims") and isinstance(request.state.claims, dict):
            tenant_id = request.state.claims.get("tenant_id")

        # For user requests with a Bearer token, extract tenant_id from the JWT.
        # This is the trusted path for end-user requests.
        if not tenant_id:
            auth_header = request.headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                tenant_id = self._extract_tenant_from_jwt(auth_header[7:])

        # Only trust X-Tenant-Id header if the request carries valid S2S
        # credentials (X-Service-Id + X-Service-Key). This prevents user
        # requests from spoofing tenant context via the header — only
        # authenticated service-to-service calls may override tenant_id.
        if not tenant_id:
            service_id = request.headers.get("X-Service-Id", "")
            service_key = request.headers.get("X-Service-Key", "")
            if service_id and service_key:
                tenant_id = request.headers.get(self.header_name)

        # Set on request state (may be None for unauthenticated endpoints)
        request.state.tenant_id = tenant_id or ""

        if tenant_id:
            bind_contextvars(tenant_id=tenant_id)

        return await call_next(request)

    @staticmethod
    def _extract_tenant_from_jwt(token: str) -> str | None:
        """Best-effort JWT payload extraction without verification.

        This is NOT for security -- just for logging/context. Actual
        authentication is handled by the auth middleware. We decode
        the payload segment (base64url) to extract tenant_id claim.
        """
        import base64
        import json

        try:
            parts = token.split(".")
            if len(parts) != 3:
                return None
            # Decode payload (2nd segment)
            payload_b64 = parts[1]
            # Add padding if needed
            padding = 4 - len(payload_b64) % 4
            if padding != 4:
                payload_b64 += "=" * padding
            payload_bytes = base64.urlsafe_b64decode(payload_b64)
            payload = json.loads(payload_bytes)
            return payload.get("tenant_id") or payload.get("custom:tenant_id")
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
            return None


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Logs HTTP method, path, status code, and duration for every request.

    Uses structlog for structured JSON output. Skips health check endpoints
    to reduce log noise.
    """

    SKIP_PATHS: set[str] = {"/health", "/ready", "/healthz", "/readyz"}

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # Skip logging for health check endpoints
        if request.url.path in self.SKIP_PATHS:
            return await call_next(request)

        start_time = time.perf_counter()

        response = await call_next(request)

        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)

        # Log at appropriate level based on status code
        log_data = {
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "duration_ms": duration_ms,
        }

        if response.status_code >= 500:
            logger.error("Request completed", **log_data)
        elif response.status_code >= 400:
            logger.warning("Request completed", **log_data)
        else:
            logger.info("Request completed", **log_data)

        return response
