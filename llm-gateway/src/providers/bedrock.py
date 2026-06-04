from __future__ import annotations

import json
import time
import uuid
from typing import Any

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

# Bedrock pricing per 1K tokens (approximate, varies by region)
_BEDROCK_PRICING: dict[str, tuple[float, float]] = {
    # (input_per_1k, output_per_1k)
    "anthropic.claude-3-haiku-20240307-v1:0": (0.00025, 0.00125),
    "anthropic.claude-3-5-sonnet-20241022-v2:0": (0.003, 0.015),
    "anthropic.claude-3-5-sonnet-20240620-v1:0": (0.003, 0.015),
    "anthropic.claude-3-opus-20240229-v1:0": (0.015, 0.075),
    "us.anthropic.claude-sonnet-4-20250514-v1:0": (0.003, 0.015),
    "us.anthropic.claude-opus-4-20250514-v1:0": (0.015, 0.075),
}


class BedrockAdapter(ProviderAdapter):
    """AWS Bedrock adapter using the Converse API via boto3.

    Uses boto3 synchronously in a thread executor since aiobotocore's
    Bedrock runtime support may be limited. The gateway wraps this in
    asyncio.to_thread for non-blocking behavior.
    """

    def __init__(self, model_config: ModelConfig, region: str = "us-east-1") -> None:
        super().__init__(model_config)
        self._region = region
        self._client: Any = None

    def _get_client(self) -> Any:
        """Lazily initialize boto3 bedrock-runtime client."""
        if self._client is None:
            import boto3

            self._client = boto3.client(
                "bedrock-runtime",
                region_name=self._region,
            )
        return self._client

    async def complete(self, request: NormalizedRequest) -> NormalizedResponse:
        """Execute completion via Bedrock Converse API."""
        import asyncio

        try:
            response = await asyncio.to_thread(self._sync_complete, request)
            return response
        except Exception as exc:
            raise ProviderError(
                provider="bedrock",
                model=self._model_config.model,
                message=str(exc),
            ) from exc

    def _sync_complete(self, request: NormalizedRequest) -> NormalizedResponse:
        """Synchronous Converse API call (runs in thread)."""
        client = self._get_client()

        # Build messages in Bedrock Converse format
        messages = self._translate_messages(request)

        # Build request kwargs
        kwargs: dict[str, Any] = {
            "modelId": self._model_config.model,
            "messages": messages,
            "inferenceConfig": {
                "maxTokens": request.max_tokens,
                "temperature": request.temperature,
            },
        }

        # System messages go in the system parameter
        system_messages = [
            {"text": m.content}
            for m in request.messages
            if m.role.value == "system" and m.content
        ]
        if system_messages:
            kwargs["system"] = system_messages

        # Add tools if present
        if request.tools:
            kwargs["toolConfig"] = self._translate_tools(request.tools)

        # Add stop sequences if present
        if request.stop:
            kwargs["inferenceConfig"]["stopSequences"] = request.stop

        response = client.converse(**kwargs)

        return self._parse_response(response)

    def _translate_messages(self, request: NormalizedRequest) -> list[dict[str, Any]]:
        """Translate normalized messages to Bedrock Converse format."""
        messages: list[dict[str, Any]] = []
        for msg in request.messages:
            if msg.role.value == "system":
                continue  # system messages handled separately
            bedrock_msg: dict[str, Any] = {"role": msg.role.value}
            content_blocks: list[dict[str, Any]] = []

            if msg.content:
                content_blocks.append({"text": msg.content})

            if msg.tool_calls:
                for tc in msg.tool_calls:
                    try:
                        tool_input = json.loads(tc.function.arguments)
                    except (json.JSONDecodeError, TypeError):
                        tool_input = {}
                    content_blocks.append({
                        "toolUse": {
                            "toolUseId": tc.id,
                            "name": tc.function.name,
                            "input": tool_input,
                        }
                    })

            if msg.role.value == "tool" and msg.tool_call_id:
                content_blocks = [{
                    "toolResult": {
                        "toolUseId": msg.tool_call_id,
                        "content": [{"text": msg.content or ""}],
                    }
                }]
                bedrock_msg["role"] = "user"

            if content_blocks:
                bedrock_msg["content"] = content_blocks
                messages.append(bedrock_msg)

        return messages

    def _translate_tools(self, tools: list[Tool]) -> dict[str, Any]:
        """Translate OpenAI-format tools to Bedrock toolConfig."""
        bedrock_tools: list[dict[str, Any]] = []
        for tool in tools:
            bedrock_tools.append({
                "toolSpec": {
                    "name": tool.function.name,
                    "description": tool.function.description,
                    "inputSchema": {
                        "json": tool.function.parameters or {"type": "object", "properties": {}},
                    },
                }
            })
        return {"tools": bedrock_tools}

    def _parse_response(self, response: dict[str, Any]) -> NormalizedResponse:
        """Parse Bedrock Converse response into normalized format."""
        output = response.get("output", {})
        message = output.get("message", {})
        content_blocks = message.get("content", [])

        text_content: str | None = None
        tool_calls: list[ToolCall] = []

        for block in content_blocks:
            if "text" in block:
                text_content = block["text"]
            elif "toolUse" in block:
                tool_use = block["toolUse"]
                tool_calls.append(ToolCall(
                    id=tool_use.get("toolUseId", str(uuid.uuid4())),
                    type="function",
                    function=ToolCallFunction(
                        name=tool_use.get("name", ""),
                        arguments=json.dumps(tool_use.get("input", {})),
                    ),
                ))

        # Extract usage
        usage_data = response.get("usage", {})
        usage = Usage(
            input_tokens=usage_data.get("inputTokens", 0),
            output_tokens=usage_data.get("outputTokens", 0),
        )

        # Extract stop reason
        stop_reason = response.get("stopReason", "end_turn")
        finish_reason = "tool_calls" if tool_calls else "stop"
        if stop_reason == "max_tokens":
            finish_reason = "length"

        return NormalizedResponse(
            content=text_content,
            tool_calls=tool_calls if tool_calls else None,
            usage=usage,
            finish_reason=finish_reason,
            raw_response=response,
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Bedrock embedding via Titan or Cohere models."""
        import asyncio

        try:
            embeddings = await asyncio.to_thread(self._sync_embed, texts)
            return embeddings
        except Exception as exc:
            raise ProviderError(
                provider="bedrock",
                model=self._model_config.model,
                message=f"Embedding failed: {exc}",
            ) from exc

    def _sync_embed(self, texts: list[str]) -> list[list[float]]:
        """Synchronous embedding call."""
        client = self._get_client()
        embeddings: list[list[float]] = []

        for text in texts:
            body = json.dumps({"inputText": text})
            response = client.invoke_model(
                modelId=self._model_config.model,
                body=body,
                contentType="application/json",
                accept="application/json",
            )
            result = json.loads(response["body"].read())
            embedding = result.get("embedding", [])
            embeddings.append(embedding)

        return embeddings

    async def health_check(self) -> bool:
        """Check Bedrock model availability with a minimal request."""
        import asyncio

        try:
            result = await asyncio.to_thread(self._sync_health_check)
            return result
        except Exception:
            return False

    def _sync_health_check(self) -> bool:
        """Synchronous health check."""
        client = self._get_client()
        try:
            client.converse(
                modelId=self._model_config.model,
                messages=[{"role": "user", "content": [{"text": "hi"}]}],
                inferenceConfig={"maxTokens": 1},
            )
            return True
        except Exception:
            return False

    def estimate_cost(self, input_tokens: int, output_tokens: int) -> float:
        """Estimate cost based on Bedrock pricing."""
        pricing = _BEDROCK_PRICING.get(self._model_config.model)
        if pricing is None:
            # Default pricing for unknown models
            return (input_tokens * 0.003 + output_tokens * 0.015) / 1000.0
        input_rate, output_rate = pricing
        return (input_tokens * input_rate + output_tokens * output_rate) / 1000.0

    async def close(self) -> None:
        """Close boto3 client."""
        self._client = None
