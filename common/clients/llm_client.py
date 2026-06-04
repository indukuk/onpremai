"""LLM Gateway client with automatic retry, escalation, and credit tracking.

Usage:
    from common.clients import LLMClient, LLMResponse

    llm = LLMClient()
    response = await llm.complete(
        messages=[{"role": "user", "content": "Evaluate this control"}],
        task="evaluate_control",
        tenant_id="tenant-123",
    )
    print(response.content, response.model_used, response.tier_used)

The client never exposes provider or model details to agents. Agents declare
a task name, and the gateway resolves the appropriate model via routing config.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field

import httpx
import structlog

from common.errors import (
    LLMCreditExhaustedError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from common.retry import retry

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class LLMResponse:
    """Structured response from the LLM Gateway.

    Attributes:
        content: The generated text content.
        model_used: Model identifier used (opaque to agents).
        tier_used: Tier name (fast/mid/strong) that served the request.
        escalated: Whether the request was escalated to a higher tier.
        input_tokens: Number of input tokens consumed.
        output_tokens: Number of output tokens generated.
        latency_ms: End-to-end latency in milliseconds.
        confidence: Model-reported confidence score if available.
        tool_calls: List of tool call dicts if the model invoked tools.
    """

    content: str
    model_used: str
    tier_used: str
    escalated: bool = False
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0
    confidence: float | None = None
    tool_calls: list[dict] = field(default_factory=list)


class LLMClient:
    """Async client for the LLM Gateway service.

    All LLM calls flow through this client. Agents declare a task name,
    never a model name. The gateway handles routing, escalation, and
    budget enforcement.
    """

    def __init__(
        self,
        gateway_url: str | None = None,
        timeout: float = 120.0,
    ) -> None:
        self._gateway_url = (
            gateway_url or os.environ.get("LLM_GATEWAY_URL", "http://llm-gateway:4000")
        ).rstrip("/")
        self._timeout = timeout
        self._http = httpx.AsyncClient(
            base_url=self._gateway_url,
            timeout=httpx.Timeout(timeout, connect=10.0),
            headers={"Content-Type": "application/json"},
        )

    @retry(max_attempts=2, base_delay=1.0, exceptions=(LLMTimeoutError,))
    async def complete(
        self,
        messages: list[dict],
        task: str,
        confidence_threshold: float = 0.0,
        structured_output: dict | None = None,
        tools: list[dict] | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        tenant_id: str | None = None,
        trace_id: str | None = None,
    ) -> LLMResponse:
        """Send a completion request to the LLM Gateway.

        Args:
            messages: Chat messages in OpenAI-compatible format.
            task: Task identifier for routing (e.g., "evaluate_control").
            confidence_threshold: Minimum confidence before escalation.
            structured_output: JSON schema for structured responses.
            tools: Tool definitions for function calling.
            max_tokens: Maximum tokens to generate.
            temperature: Sampling temperature (0.0 = deterministic).
            tenant_id: Tenant identifier for budget tracking.
            trace_id: Distributed trace identifier.

        Returns:
            LLMResponse with the generated content and metadata.

        Raises:
            LLMUnavailableError: Gateway returned 5xx.
            LLMTimeoutError: Request exceeded timeout.
            LLMCreditExhaustedError: Tenant budget exhausted (429).
        """
        request_id = trace_id or str(uuid.uuid4())
        payload: dict = {
            "messages": messages,
            "task": task,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "confidence_threshold": confidence_threshold,
        }
        if structured_output is not None:
            payload["structured_output"] = structured_output
        if tools is not None:
            payload["tools"] = tools
        if tenant_id is not None:
            payload["tenant_id"] = tenant_id

        headers: dict[str, str] = {"X-Trace-Id": request_id}

        try:
            response = await self._http.post(
                "/v1/complete",
                json=payload,
                headers=headers,
            )
        except httpx.TimeoutException as exc:
            logger.warning(
                "llm_gateway_timeout",
                task=task,
                tenant_id=tenant_id,
                trace_id=request_id,
            )
            raise LLMTimeoutError(
                f"LLM Gateway request timed out after {self._timeout}s",
                task=task,
                tenant_id=tenant_id,
            ) from exc
        except httpx.ConnectError as exc:
            logger.error(
                "llm_gateway_unreachable",
                url=self._gateway_url,
                trace_id=request_id,
            )
            raise LLMUnavailableError(
                "Cannot connect to LLM Gateway",
                url=self._gateway_url,
            ) from exc

        if response.status_code == 429:
            body = response.json() if response.content else {}
            degradation = body.get("degradation", {})
            raise LLMCreditExhaustedError(
                body.get("message", "Credit budget exhausted for tenant"),
                degradation_level=degradation.get("level", 1),
                tier_availability=degradation.get("tier_availability"),
                estimated_recovery=degradation.get("estimated_recovery"),
                can_queue=degradation.get("can_queue", False),
                queued_position=degradation.get("queued_position"),
                tenant_id=tenant_id,
                task=task,
            )

        if response.status_code >= 500:
            logger.error(
                "llm_gateway_5xx",
                status=response.status_code,
                task=task,
                trace_id=request_id,
            )
            raise LLMUnavailableError(
                f"LLM Gateway returned {response.status_code}",
                status_code=response.status_code,
                task=task,
            )

        response.raise_for_status()
        data = response.json()

        return LLMResponse(
            content=data.get("content", ""),
            model_used=data.get("model_used", "unknown"),
            tier_used=data.get("tier_used", "unknown"),
            escalated=data.get("escalated", False),
            input_tokens=data.get("input_tokens", 0),
            output_tokens=data.get("output_tokens", 0),
            latency_ms=data.get("latency_ms", 0.0),
            confidence=data.get("confidence"),
            tool_calls=data.get("tool_calls", []),
        )

    async def embed(
        self,
        texts: list[str],
        tenant_id: str | None = None,
    ) -> list[list[float]]:
        """Generate embeddings for the given texts.

        Args:
            texts: List of text strings to embed.
            tenant_id: Tenant identifier for budget tracking.

        Returns:
            List of embedding vectors (list of floats).

        Raises:
            LLMUnavailableError: Gateway unreachable or 5xx.
            LLMTimeoutError: Request timed out.
        """
        payload: dict = {"texts": texts}
        if tenant_id is not None:
            payload["tenant_id"] = tenant_id

        try:
            response = await self._http.post("/v1/embed", json=payload)
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError(
                "Embedding request timed out",
                tenant_id=tenant_id,
            ) from exc
        except httpx.ConnectError as exc:
            raise LLMUnavailableError(
                "Cannot connect to LLM Gateway for embedding",
                url=self._gateway_url,
            ) from exc

        if response.status_code >= 500:
            raise LLMUnavailableError(
                f"LLM Gateway returned {response.status_code} for embed",
                status_code=response.status_code,
            )

        response.raise_for_status()
        data = response.json()
        return data.get("embeddings", [])

    async def close(self) -> None:
        """Close the underlying HTTP client and release connections."""
        await self._http.aclose()
