"""Exception hierarchy for all services.

All common library errors inherit from CommonError. Agents catch specific
exceptions to decide degradation behavior. The hierarchy is:

CommonError
├── LLMUnavailableError
│   ├── LLMTimeoutError
│   └── LLMCreditExhaustedError
├── StorageError
│   └── StorageNotFoundError
├── SandboxError
├── StateError
├── AuthenticationError
├── AuthorizationError
└── RegistryError
"""

from __future__ import annotations


class CommonError(Exception):
    """Base exception for all common library errors.

    All subclasses accept an arbitrary keyword context dict that is
    available for structured logging and error reporting.
    """

    def __init__(self, message: str = "", **context: object) -> None:
        self.message = message
        self.context = context
        super().__init__(message)

    def __repr__(self) -> str:
        ctx = ", ".join(f"{k}={v!r}" for k, v in self.context.items())
        cls = type(self).__name__
        if ctx:
            return f"{cls}({self.message!r}, {ctx})"
        return f"{cls}({self.message!r})"


class LLMUnavailableError(CommonError):
    """LLM Gateway is unreachable or returned 5xx.

    Agents should decide their own fallback behavior when this is raised:
    - agent-eval: fall back to rules-only evaluation
    - compliance-assistant: switch to data-only mode
    - observer: pause diagnosis, continue metric collection
    - preprocessor: continue deterministic processing
    """


class LLMTimeoutError(LLMUnavailableError):
    """LLM request exceeded the configured timeout.

    This is a subclass of LLMUnavailableError so agents that catch the
    parent will also handle timeouts.
    """


class LLMCreditExhaustedError(LLMUnavailableError):
    """All LLM budget/credits exhausted for this tenant.

    The system enters degraded mode according to degradation_level:
        Level 1: Strong tier gone -> cap at mid
        Level 2: Mid tier gone -> fast only
        Level 3: Fast tier gone -> deterministic only
        Level 4: Monthly cap hit -> queue indefinitely

    Attributes:
        degradation_level: Current degradation level (1-4).
        tier_availability: Dict mapping tier names to availability status.
        estimated_recovery: ISO timestamp when budget resets, or None.
        can_queue: Whether the gateway will queue and retry when credits return.
        queued_position: Position in the queue if the request was queued.
    """

    def __init__(
        self,
        message: str = "",
        *,
        degradation_level: int = 1,
        tier_availability: dict[str, str] | None = None,
        estimated_recovery: str | None = None,
        can_queue: bool = False,
        queued_position: int | None = None,
        **context: object,
    ) -> None:
        self.degradation_level = degradation_level
        self.tier_availability = tier_availability or {
            "fast": "available",
            "mid": "available",
            "strong": "exhausted",
        }
        self.estimated_recovery = estimated_recovery
        self.can_queue = can_queue
        self.queued_position = queued_position
        super().__init__(message, **context)


class StorageError(CommonError):
    """Storage operation failed after retries.

    Raised when the storage backend (S3 or MinIO) is unreachable or
    returns an unrecoverable error.
    """


class StorageNotFoundError(StorageError):
    """Requested key does not exist in storage.

    Agents should handle this gracefully -- missing evidence files are
    a normal condition during evaluation.
    """


class SandboxError(CommonError):
    """Sandbox service is unreachable or execution failed.

    When sandbox is down, agents should return a failed execution result
    rather than crashing.
    """


class StateError(CommonError):
    """State backend operation failed.

    The job tracking / async state system (PostgreSQL or DynamoDB)
    is unreachable or returned an error.
    """


class AuthenticationError(CommonError):
    """JWT or API key validation failed.

    The request could not be authenticated -- token is expired, malformed,
    or the signature is invalid.
    """


class AuthorizationError(CommonError):
    """User lacks permission for this operation.

    The request was authenticated but the user's role does not have
    sufficient privileges.
    """


class RegistryError(CommonError):
    """Agent registry operation failed.

    The agent could not register, renew its lease, or look up other
    agents in the service registry.
    """
