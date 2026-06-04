"""Common shared library for all services.

This package provides the abstraction layer that makes agents portable
across environments. Every agent imports from common/ -- no agent talks
to infrastructure directly.
"""

from common.config import CommonSettings
from common.errors import (
    AuthenticationError,
    AuthorizationError,
    CommonError,
    LLMCreditExhaustedError,
    LLMTimeoutError,
    LLMUnavailableError,
    RegistryError,
    SandboxError,
    StateError,
    StorageError,
    StorageNotFoundError,
)
from common.retry import retry
from common.middleware import (
    TraceIdMiddleware,
    TenantContextMiddleware,
    RequestLoggingMiddleware,
)
from common.logging.logger import AgentLogger, configure_logging
from common.logging.pii import PII
from common.auth import (
    CognitoTokenValidator,
    UserContext,
    ServiceAuthenticator,
    ServiceIdentity,
    require_role,
    require_scope,
    get_current_user,
)
from common.clients import (
    LLMClient,
    LLMResponse,
    MemoryClient,
    StorageClient,
    SandboxClient,
    ExecutionResult,
    StateClient,
    RegistryClient,
)
from common.storage import StorageAdapter, S3Adapter, MinIOAdapter

__all__ = [
    # Config
    "CommonSettings",
    # Errors
    "CommonError",
    "LLMUnavailableError",
    "LLMTimeoutError",
    "LLMCreditExhaustedError",
    "StorageError",
    "StorageNotFoundError",
    "SandboxError",
    "StateError",
    "AuthenticationError",
    "AuthorizationError",
    "RegistryError",
    # Retry
    "retry",
    # Middleware
    "TraceIdMiddleware",
    "TenantContextMiddleware",
    "RequestLoggingMiddleware",
    # Logging
    "AgentLogger",
    "PII",
    "configure_logging",
    # Auth
    "CognitoTokenValidator",
    "UserContext",
    "ServiceAuthenticator",
    "ServiceIdentity",
    "require_role",
    "require_scope",
    "get_current_user",
    # Clients
    "LLMClient",
    "LLMResponse",
    "MemoryClient",
    "StorageClient",
    "SandboxClient",
    "ExecutionResult",
    "StateClient",
    "RegistryClient",
    # Storage adapters
    "StorageAdapter",
    "S3Adapter",
    "MinIOAdapter",
]
