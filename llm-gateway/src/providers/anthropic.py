from __future__ import annotations

import json
import uuid
from typing import Any

import httpx
import structlog

from src.models import (
    ModelConfig,
    NormalizedRequest,
    NormalizedResponse,
    Tool,
    ToolCall,
    ToolCallFunction,
    Usage,
)
from src.providers.base import ProviderAdapter, ProviderError

logger = structlog.get_logger(__name__)

_ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
_ANTHROPIC_API_VERSION = "2023-06-01"

# Pricing per 1K tokens
_ANTHROPIC_PRICING: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5-20251001": (0.0008, 0.004),
    "claude-sonnet-4-20250514": (0.003, 0.015),
    "claude-opus-4-20250514": (0.015, 0.075),
    "claude-3-5-sonnet-20241022": (0.003, 0.015),
    "claude-3-5-haiku-20241022": (0.001, 0.005),
    "claude-3-opus-20240229": (0.015, 0.075),
}


class AnthropicAdapter(ProviderAdapter):
    """Anthropic Messages API adapter using httpx.

    Translates between OpenAI-format tool calls and Anthropic's
    tool_use content blocks.
    """

    def __init__(self, model_config: ModelConfig) -> None:
        super().__init__(model_config)
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        """Lazily initialize httpx async client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self._model_config.timeout_ms / 1000.0),
                limits=httpx.Limits(max_connections=50, max_keepalive_connections=10),
            )
        return self._client

    async def complete(self, request: NormalizedRequest) -> NormalizedResponse:
        """Execute completion via Anthropic Messages API."""
        client = self._get_client()

        # Build request body
        body = self._build_request_body(request)
        headers = {
            "x-api-key": self._model_config.api_key,
            "anthropic-version": _ANTHROPIC_API_VERSION,
            "content-type": "application/json",
        }

        try:
            response = await client.post(
                _ANTHROPIC_API_URL,
                json=body,
                headers=headers,
            )
            response.raise_for_status()
            data = response.json()
            return self._parse_response(data)
        except httpx.HTTPStatusError as exc:
            raise ProviderError(
                provider="anthropic",
                model=self._model_config.model,
                message=f"HTTP {exc.response.status_code}: {exc.response.text[:500]}",
                status_code=exc.response.status_code,
            ) from exc
        except httpx.TimeoutException as exc:
            raise ProviderError(
                provider="anthropic",
                model=self._model_config.model,
                message=f"Timeout after {self._model_config.timeout_ms}ms",
            ) from exc
        except Exception as exc:
            raise ProviderError(
                provider="anthropic",
                model=self._model_config.model,
                message=str(exc),
            ) from exc

    def _build_request_body(self, request: NormalizedRequest) -> dict[str, Any]:
        """Build Anthropic Messages API request body."""
        body: dict[str, Any] = {
            "model": self._model_config.model,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
        }

        # Separate system message
        system_content: list[str] = []
        messages: list[dict[str, Any]] = []

        for msg in request.messages:
            if msg.role.value == "system":
                if msg.content:
                    system_content.append(msg.content)
                continue

            anthropic_msg: dict[str, Any] = {"role": msg.role.value}
            content: list[dict[str, Any]] = []

            if msg.role.value == "tool" and msg.tool_call_id:
                # Tool result in Anthropic format
                anthropic_msg["role"] = "user"
                content.append({
                    "type": "tool_result",
                    "tool_use_id": msg.tool_call_id,
                    "content": msg.content or "",
                })
            elif msg.tool_calls:
                # Assistant message with tool calls
                if msg.content:
                    content.append({"type": "text", "text": msg.content})
                for tc in msg.tool_calls:
                    try:
                        tool_input = json.loads(tc.function.arguments)
                    except (json.JSONDecodeError, TypeError):
                        tool_input = {}
                    content.append({
                        "type": "tool_use",
                        "id": tc.id,
                        "name": tc.function.name,
                        "input": tool_input,
                    })
            else:
                if msg.content:
                    content.append({"type": "text", "text": msg.content})

            if content:
                anthropic_msg["content"] = content
                messages.append(anthropic_msg)

        if system_content:
            body["system"] = "\n\n".join(system_content)

        body["messages"] = messages

        # Add tools if present
        if request.tools:
            body["tools"] = self._translate_tools(request.tools)

        # Stop sequences
        if request.stop:
            body["stop_sequences"] = request.stop

        return body

    def _translate_tools(self, tools: list[Tool]) -> list[dict[str, Any]]:
        """Translate OpenAI-format tools to Anthropic format."""
        anthropic_tools: list[dict[str, Any]] = []
        for tool in tools:
            anthropic_tools.append({
                "name": tool.function.name,
                "description": tool.function.description,
                "input_schema": tool.function.parameters or {"type": "object", "properties": {}},
            })
        return anthropic_tools

    def _parse_response(self, data: dict[str, Any]) -> NormalizedResponse:
        """Parse Anthropic Messages API response into normalized format."""
        content_blocks = data.get("content", [])
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []

        for block in content_blocks:
            block_type = block.get("type")
            if block_type == "text":
                text_parts.append(block.get("text", ""))
            elif block_type == "tool_use":
                tool_calls.append(ToolCall(
                    id=block.get("id", str(uuid.uuid4())),
                    type="function",
                    function=ToolCallFunction(
                        name=block.get("name", ""),
                        arguments=json.dumps(block.get("input", {})),
                    ),
                ))

        text_content = "\n".join(text_parts) if text_parts else None

        # Usage
        usage_data = data.get("usage", {})
        usage = Usage(
            input_tokens=usage_data.get("input_tokens", 0),
            output_tokens=usage_data.get("output_tokens", 0),
        )

        # Finish reason mapping
        stop_reason = data.get("stop_reason", "end_turn")
        finish_reason = "stop"
        if stop_reason == "tool_use":
            finish_reason = "tool_calls"
        elif stop_reason == "max_tokens":
            finish_reason = "length"

        return NormalizedResponse(
            content=text_content,
            tool_calls=tool_calls if tool_calls else None,
            usage=usage,
            finish_reason=finish_reason,
            raw_response=data,
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Anthropic does not natively support embeddings."""
        raise ProviderError(
            provider="anthropic",
            model=self._model_config.model,
            message="Anthropic does not support embeddings",
        )

    async def health_check(self) -> bool:
        """Check Anthropic API availability with a minimal request."""
        client = self._get_client()
        headers = {
            "x-api-key": self._model_config.api_key,
            "anthropic-version": _ANTHROPIC_API_VERSION,
            "content-type": "application/json",
        }
        body = {
            "model": self._model_config.model,
            "max_tokens": 1,
            "messages": [{"role": "user", "content": [{"type": "text", "text": "hi"}]}],
        }
        try:
            response = await client.post(
                _ANTHROPIC_API_URL,
                json=body,
                headers=headers,
            )
            return response.status_code == 200
        except Exception:
            return False

    def estimate_cost(self, input_tokens: int, output_tokens: int) -> float:
        """Estimate cost based on Anthropic pricing."""
        pricing = _ANTHROPIC_PRICING.get(self._model_config.model)
        if pricing is None:
            return (input_tokens * 0.003 + output_tokens * 0.015) / 1000.0
        input_rate, output_rate = pricing
        return (input_tokens * input_rate + output_tokens * output_rate) / 1000.0

    async def close(self) -> None:
        """Close httpx client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
