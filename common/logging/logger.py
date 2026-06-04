"""Structured logging configuration and AgentLogger facade.

Provides:
- configure_logging(): sets up structlog with the full processor pipeline
  including PII redaction, service metadata, and JSON/console rendering.
- AgentLogger: high-level facade with domain-specific convenience methods
  (node_start/end, llm_call, tool_call) for instrumented agent code.

Usage:
    from common.logging import AgentLogger
    from common.logging.logger import configure_logging

    configure_logging(service_name="agent-eval", log_level="INFO")
    logger = AgentLogger(agent_name="agent-eval", trace_id="abc-123")
    logger.info("Control evaluated", control_id="CC6.1", duration_ms=4200)
"""

from __future__ import annotations

import logging
import os
import sys
import time
from typing import Any

import structlog

from common.logging.processors import (
    add_service_info,
    redact_pii_fields,
    redact_pii_patterns,
)


def configure_logging(
    service_name: str,
    log_level: str = "INFO",
    json_output: bool = True,
    pii_hmac_key: str = "",
) -> None:
    """Configure structlog with the full processor pipeline.

    Sets up structlog processors in order:
    1. merge_contextvars - merge thread-local context into event dict
    2. add_log_level - attach the log level string
    3. TimeStamper - ISO-8601 timestamp
    4. add_service_info - attach service name
    5. redact_pii_fields - hash PII wrappers, redact unknown fields
    6. redact_pii_patterns - regex scrub the event message
    7. Renderer - JSON (production) or Console (development)

    Also bridges stdlib logging through structlog so third-party library
    logs are processed through the same pipeline.

    Args:
        service_name: Identifies the service in log output.
        log_level: Minimum log level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        json_output: If True, render as JSON. If False, use colored console output.
        pii_hmac_key: HMAC key for PII hashing. Stored in environment for
            processor access.
    """
    # Store hmac key in env for processor access
    if pii_hmac_key:
        os.environ["PII_HMAC_KEY"] = pii_hmac_key

    # Store service name in env for processors
    os.environ.setdefault("SERVICE_NAME", service_name)

    # Shared processors used by both structlog-native and stdlib bridge
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        add_service_info(service_name),
        redact_pii_fields,
        redact_pii_patterns,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if json_output:
        renderer: structlog.types.Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

    # Configure structlog
    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_events_in_msg_field,
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )

    # Configure stdlib logging to route through structlog
    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
        foreign_pre_chain=shared_processors,
    )

    root_logger = logging.getLogger()
    root_logger.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    root_logger.addHandler(handler)
    root_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))


class AgentLogger:
    """High-level structured logger for agent services.

    Wraps structlog with bound context (agent_name, trace_id, tenant_id)
    and provides domain-specific convenience methods for common agent
    instrumentation patterns.

    Usage:
        logger = AgentLogger(agent_name="agent-eval", trace_id="t-123")
        start = logger.node_start("rules_engine")
        # ... do work ...
        logger.node_end("rules_engine", start, controls_evaluated=42)
    """

    def __init__(
        self,
        agent_name: str,
        trace_id: str | None = None,
        tenant_id: str | None = None,
    ) -> None:
        self._agent_name = agent_name
        self._trace_id = trace_id
        self._tenant_id = tenant_id

        bind_kwargs: dict[str, Any] = {"agent_name": agent_name}
        if trace_id is not None:
            bind_kwargs["trace_id"] = trace_id
        if tenant_id is not None:
            bind_kwargs["tenant_id"] = tenant_id

        self._logger: structlog.stdlib.BoundLogger = structlog.get_logger().bind(
            **bind_kwargs
        )

    def info(self, message: str, **context: Any) -> None:
        """Log an informational message with optional structured context."""
        self._logger.info(message, **context)

    def error(
        self, message: str, error: Exception | None = None, **context: Any
    ) -> None:
        """Log an error with optional exception details.

        If an exception is provided, its type and message are included as
        structured fields (error_type, error_detail).
        """
        if error is not None:
            context["error_type"] = type(error).__name__
            context["error_detail"] = str(error)
        self._logger.error(message, **context)

    def warn(self, message: str, **context: Any) -> None:
        """Log a warning message with optional structured context."""
        self._logger.warning(message, **context)

    def debug(self, message: str, **context: Any) -> None:
        """Log a debug message with optional structured context."""
        self._logger.debug(message, **context)

    def node_start(self, node_name: str) -> float:
        """Mark the start of a processing node and return the start time.

        Args:
            node_name: Identifier for the processing node (e.g., "rules_engine").

        Returns:
            The current perf_counter value (pass to node_end for duration).
        """
        self._logger.debug("node_started", node_name=node_name)
        return time.perf_counter()

    def node_end(self, node_name: str, start: float, **context: Any) -> None:
        """Mark the end of a processing node and log the duration.

        Args:
            node_name: Same identifier passed to node_start.
            start: The float returned by node_start.
            **context: Additional structured fields to include.
        """
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        self._logger.info(
            "node_completed",
            node_name=node_name,
            duration_ms=duration_ms,
            **context,
        )

    def llm_call(
        self, task: str, latency_ms: float, success: bool, **context: Any
    ) -> None:
        """Log an LLM gateway call with standard metrics.

        Args:
            task: The task name sent to the LLM gateway (e.g., "evaluate_control").
            latency_ms: Round-trip latency in milliseconds.
            success: Whether the call completed successfully.
            **context: Additional fields (model_used, tier_used, tokens, etc.).
        """
        self._logger.info(
            "llm_call",
            task=task,
            latency_ms=latency_ms,
            success=success,
            **context,
        )

    def tool_call(
        self, tool_name: str, latency_ms: float, success: bool, **context: Any
    ) -> None:
        """Log a tool/skill invocation with standard metrics.

        Args:
            tool_name: The tool or skill name invoked.
            latency_ms: Execution latency in milliseconds.
            success: Whether the tool call succeeded.
            **context: Additional fields.
        """
        self._logger.info(
            "tool_call",
            tool_name=tool_name,
            latency_ms=latency_ms,
            success=success,
            **context,
        )

    def with_context(self, **kwargs: Any) -> AgentLogger:
        """Create a new AgentLogger with additional bound context fields.

        Returns a new logger instance that inherits all current bindings
        plus the new ones. The original logger is unchanged.

        Usage:
            child = logger.with_context(control_id="CC6.1", framework="SOC2")
            child.info("Evaluating control")  # includes control_id and framework
        """
        new_logger = AgentLogger.__new__(AgentLogger)
        new_logger._agent_name = self._agent_name
        new_logger._trace_id = self._trace_id
        new_logger._tenant_id = self._tenant_id
        new_logger._logger = self._logger.bind(**kwargs)
        return new_logger
