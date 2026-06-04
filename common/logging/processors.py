"""Structlog processors for PII redaction and service metadata.

Processors are inserted into the structlog pipeline to ensure that:
1. PII-wrapped values are hashed before serialization.
2. Unknown fields in production mode are redacted.
3. Free-text log messages are scrubbed for PII patterns.
4. Service identity is attached to every log event.
"""

from __future__ import annotations

import os
from typing import Any

import structlog

from common.logging.pii import PII, SAFE_FIELDS, redact_string


# Internal fields added by structlog or our pipeline that should never be redacted
_INTERNAL_FIELDS: frozenset[str] = frozenset(
    {
        "event",
        "level",
        "timestamp",
        "logger",
        "service",
        "agent_name",
        "_record",
        "_from_structlog",
    }
)


def _get_hmac_key() -> str:
    """Retrieve the HMAC key for PII hashing from environment."""
    return os.environ.get("PII_HMAC_KEY", "")


def redact_pii_fields(
    logger: structlog.types.WrappedLogger,
    method_name: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    """Replace PII-wrapped values with HMAC hashes and redact unknown fields.

    Processing rules:
    - If a value is a PII instance, replace it with its HMAC hash token.
    - If a key is in SAFE_FIELDS or _INTERNAL_FIELDS, pass through unchanged.
    - If a key is unknown and the environment is production, redact the value.
    - In non-production environments, unknown fields pass through for debugging.
    """
    hmac_key = _get_hmac_key()
    environment = os.environ.get("ENVIRONMENT", "production")
    is_production = environment.lower() in ("production", "prod")
    unknown_action = os.environ.get("LOG_UNKNOWN_FIELDS_ACTION", "redact")

    processed: dict[str, Any] = {}
    for key, value in event_dict.items():
        if isinstance(value, PII):
            if hmac_key:
                processed[key] = value.hash(hmac_key)
            else:
                processed[key] = "[redacted:no_key]"
        elif key in SAFE_FIELDS or key in _INTERNAL_FIELDS:
            processed[key] = value
        elif is_production and unknown_action == "redact":
            if isinstance(value, str):
                processed[key] = redact_string(value)
            else:
                processed[key] = "[redacted]"
        else:
            processed[key] = value

    return processed


def redact_pii_patterns(
    logger: structlog.types.WrappedLogger,
    method_name: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    """Apply regex-based PII redaction to the event message.

    Scans the ``event`` field (the log message) for known PII patterns
    such as emails, phone numbers, SSNs, credit cards, and IBANs.
    Matches are replaced with bracketed tokens like ``[EMAIL]``.
    """
    event_message = event_dict.get("event")
    if isinstance(event_message, str):
        event_dict["event"] = redact_string(event_message)
    return event_dict


def add_service_info(service_name: str) -> structlog.types.Processor:
    """Return a processor that attaches service identity to every log event.

    Args:
        service_name: The name of the service emitting logs (e.g., "agent-eval").

    Returns:
        A structlog processor function that adds ``service=service_name`` to
        every event dict.
    """

    def _processor(
        logger: structlog.types.WrappedLogger,
        method_name: str,
        event_dict: dict[str, Any],
    ) -> dict[str, Any]:
        event_dict["service"] = service_name
        return event_dict

    return _processor
