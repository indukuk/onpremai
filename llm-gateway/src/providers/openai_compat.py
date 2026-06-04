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


class OpenAICompatAdapter(ProviderAdapter):
    """OpenAI-compatible API adapter for vLLM, Ollama, and similar endpoints.

    Works with any endpoint that implements the OpenAI chat completions
    API format (vLLM, Ollama with OpenAI compatibility, LocalAI, etc.).
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

    def _base_url(self) -> str:
        """Get the base URL for this provider's endpoint."""
        endpoint = self._model_config.endpoint.rstrip("/")
        return endpoint

    async def complete(self, request: NormalizedRequest) -> NormalizedResponse:
        """Execute completion via OpenAI-compatible chat completions endpoint."""
        client = self._get_client()
        url = f"{self._base_url()}/v1/chat/completions"

        body = self._build_request_body(request)
        headers: dict[str, str] = {"content-type": "application/json"}

        if self._model_config.api_key:
            headers["authorization"] = f"Bearer {self._model_config.api_key}"

        try:
            response = await client.post(url, json=body, headers=headers)
            response.raise_for_status()
            data = response.json()
            return self._parse_response(data)
        except httpx.HTTPStatusError as exc:
            raise ProviderError(
                provider=self._model_config.provider,
                model=self._model_config.model,
                message=f"HTTP {exc.response.status_code}: {exc.response.text[:500]}",
                status_code=exc.response.status_code,
            ) from exc
        except httpx.TimeoutException as exc:
            raise ProviderError(
                provider=self._model_config.provider,
                model=self._model_config.model,
                message=f"Timeout after {self._model_config.timeout_ms}ms",
            ) from exc
        except Exception as exc:
            raise ProviderError(
                provider=self._model_config.provider,
                model=self._model_config.model,
                message=str(exc),
            ) from exc

    def _build_request_body(self, request: NormalizedRequest) -> dict[str, Any]:
        """Build OpenAI-compatible chat completions request body."""
        messages: list[dict[str, Any]] = []
        for msg in request.messages:
            msg_dict: dict[str, Any] = {"role": msg.role.value}
            if msg.content is not None:
                msg_dict["content"] = msg.content
            if msg.tool_calls:
                msg_dict["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in msg.tool_calls
                ]
            if msg.tool_call_id:
                msg_dict["tool_call_id"] = msg.tool_call_id
            if msg.name:
                msg_dict["name"] = msg.name
            messages.append(msg_dict)

        body: dict[str, Any] = {
            "model": self._model_config.model,
            "messages": messages,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
        }

        # Add tools in OpenAI format (pass through)
        if request.tools:
            body["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool.function.name,
                        "description": tool.function.description,
                        "parameters": tool.function.parameters,
                    },
                }
                for tool in request.tools
            ]

        if request.stop:
            body["stop"] = request.stop

        if request.response_format and request.response_format.type != "text":
            body["response_format"] = {"type": request.response_format.type}

        return body

    def _parse_response(self, data: dict[str, Any]) -> NormalizedResponse:
        """Parse OpenAI-compatible response into normalized format."""
        choices = data.get("choices", [])
        if not choices:
            return NormalizedResponse(
                content=None,
                usage=Usage(),
                finish_reason="stop",
                raw_response=data,
            )

        choice = choices[0]
        message = choice.get("message", {})

        text_content = message.get("content")
        tool_calls: list[ToolCall] = []

        raw_tool_calls = message.get("tool_calls", [])
        for raw_tc in raw_tool_calls:
            function_data = raw_tc.get("function", {})
            tool_calls.append(ToolCall(
                id=raw_tc.get("id", str(uuid.uuid4())),
                type="function",
                function=ToolCallFunction(
                    name=function_data.get("name", ""),
                    arguments=function_data.get("arguments", "{}"),
                ),
            ))

        # Usage
        usage_data = data.get("usage", {})
        usage = Usage(
            input_tokens=usage_data.get("prompt_tokens", 0),
            output_tokens=usage_data.get("completion_tokens", 0),
        )

        finish_reason = choice.get("finish_reason", "stop")
        if finish_reason == "tool_calls":
            pass  # keep as-is
        elif finish_reason == "length":
            pass  # keep as-is
        else:
            finish_reason = "stop"

        return NormalizedResponse(
            content=text_content,
            tool_calls=tool_calls if tool_calls else None,
            usage=usage,
            finish_reason=finish_reason,
            raw_response=data,
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings via OpenAI-compatible embeddings endpoint."""
        client = self._get_client()
        url = f"{self._base_url()}/v1/embeddings"

        body: dict[str, Any] = {
            "model": self._model_config.model,
            "input": texts,
        }
        headers: dict[str, str] = {"content-type": "application/json"}
        if self._model_config.api_key:
            headers["authorization"] = f"Bearer {self._model_config.api_key}"

        try:
            response = await client.post(url, json=body, headers=headers)
            response.raise_for_status()
            data = response.json()
            embeddings: list[list[float]] = []
            for item in data.get("data", []):
                embeddings.append(item.get("embedding", []))
            return embeddings
        except httpx.HTTPStatusError as exc:
            raise ProviderError(
                provider=self._model_config.provider,
                model=self._model_config.model,
                message=f"Embedding HTTP {exc.response.status_code}",
                status_code=exc.response.status_code,
            ) from exc
        except Exception as exc:
            raise ProviderError(
                provider=self._model_config.provider,
                model=self._model_config.model,
                message=f"Embedding failed: {exc}",
            ) from exc

    async def health_check(self) -> bool:
        """Check endpoint availability via /v1/models or minimal completion."""
        client = self._get_client()
        url = f"{self._base_url()}/v1/models"
        headers: dict[str, str] = {}
        if self._model_config.api_key:
            headers["authorization"] = f"Bearer {self._model_config.api_key}"

        try:
            response = await client.get(url, headers=headers)
            return response.status_code == 200
        except Exception:
            return False

    def estimate_cost(self, input_tokens: int, output_tokens: int) -> float:
        """Local models have near-zero marginal cost. Return 0."""
        return 0.0

    async def close(self) -> None:
        """Close httpx client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
