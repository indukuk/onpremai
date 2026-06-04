"""PII detection, wrapping, and redaction utilities.

Provides the PII wrapper class for structured logging fields and regex-based
redaction for free-text log messages. PII values are never exposed in string
context -- access .raw only for audit trail persistence.
"""

from __future__ import annotations

import hashlib
import hmac
import re


class PII:
    """Wraps a PII value for structured logging.

    In structured logs, PII fields are replaced with an HMAC hash prefix
    so that the same value produces the same token (useful for correlation)
    without exposing the underlying data.

    Usage:
        logger.info("User logged in", email=PII("john@acme.com"))
    """

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value

    def hash(self, hmac_key: str) -> str:
        """Produce a deterministic redacted token using HMAC-SHA256.

        Returns a string like ``[redacted:a1b2c3d4]`` where the hex portion
        is the first 8 characters of the HMAC digest. This allows correlation
        of the same PII value across log entries without revealing the data.
        """
        digest = hmac.new(
            hmac_key.encode("utf-8"),
            self._value.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return f"[redacted:{digest[:8]}]"

    def __repr__(self) -> str:
        return "[PII]"

    def __str__(self) -> str:
        return "[PII]"

    @property
    def raw(self) -> str:
        """Access the original PII value (for audit trail only)."""
        return self._value


# ---------------------------------------------------------------------------
# Regex-based redaction patterns for free-text log messages
# ---------------------------------------------------------------------------

REDACTION_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Email addresses
    (
        re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"),
        "[EMAIL]",
    ),
    # US Social Security Numbers (XXX-XX-XXXX)
    (
        re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
        "[SSN]",
    ),
    # Credit card numbers (13-19 digits, optionally separated by spaces or dashes)
    (
        re.compile(r"\b(?:\d[ \-]*?){13,19}\b"),
        "[CARD]",
    ),
    # IBAN (2 letter country code + 2 check digits + up to 30 alphanumeric)
    (
        re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{4,30}\b"),
        "[IBAN]",
    ),
    # US phone numbers (various formats)
    (
        re.compile(
            r"\b(?:\+1[\s\-]?)?"
            r"(?:\(?\d{3}\)?[\s\-]?)"
            r"\d{3}[\s\-]?\d{4}\b"
        ),
        "[PHONE]",
    ),
]


# ---------------------------------------------------------------------------
# Safe field names that do not require PII wrapping
# ---------------------------------------------------------------------------

SAFE_FIELDS: frozenset[str] = frozenset(
    {
        "trace_id",
        "tenant_id",
        "session_id",
        "job_id",
        "task_id",
        "control_id",
        "framework",
        "framework_id",
        "skill_id",
        "pattern_id",
        "duration_ms",
        "latency_ms",
        "memory_used_mb",
        "tokens",
        "cost_usd",
        "input_tokens",
        "output_tokens",
        "retries",
        "queue_position",
        "status",
        "level",
        "task",
        "tier",
        "model_used",
        "tier_used",
        "success",
        "error_type",
        "degradation_level",
        "node_name",
        "tool_name",
        "file_type",
        "file_key",
        "storage_key",
        "count",
        "total",
        "row_count",
        "file_count",
        "queue_depth",
        "method",
        "path",
        "status_code",
    }
)


def redact_string(text: str) -> str:
    """Apply all redaction patterns to a free-text string.

    Scans the input for known PII patterns (emails, phone numbers, SSNs,
    credit cards, IBANs) and replaces matches with bracketed tokens.
    """
    result = text
    for pattern, replacement in REDACTION_PATTERNS:
        result = pattern.sub(replacement, result)
    return result
