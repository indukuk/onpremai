"""Tests for common.clients.llm_client LLMClient."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from common.clients.llm_client import LLMClient, LLMResponse
from common.errors import (
    LLMCreditExhaustedError,
    LLMTimeoutError,
    LLMUnavailableError,
)


@pytest.fixture
def mock_http_client() -> AsyncMock:
    """Provide a mocked httpx.AsyncClient."""
    client = AsyncMock()
    client.post = AsyncMock()
    client.aclose = AsyncMock()
    return client


@pytest.fixture
def llm_client(mock_http_client) -> LLMClient:
    """Create an LLMClient with mocked HTTP transport."""
    client = LLMClient(gateway_url="http://test-gateway:4000")
    client._http = mock_http_client
    return client


class TestLLMClientSuccess:
    """Test successful LLM completion requests."""

    @pytest.mark.asyncio
    async def test_complete_returns_llm_response(self, llm_client, mock_http_client):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "content": "The control is effective.",
            "model_used": "claude-3-haiku",
            "tier_used": "fast",
            "escalated": False,
            "input_tokens": 100,
            "output_tokens": 50,
            "latency_ms": 450.5,
            "confidence": 0.92,
            "tool_calls": [],
        }
        mock_response.raise_for_status = MagicMock()
        mock_http_client.post.return_value = mock_response

        result = await llm_client.complete(
            messages=[{"role": "user", "content": "Evaluate this control"}],
            task="evaluate_control",
            tenant_id="tenant-123",
        )

        assert isinstance(result, LLMResponse)
        assert result.content == "The control is effective."
        assert result.model_used == "claude-3-haiku"
        assert result.tier_used == "fast"
        assert result.escalated is False
        assert result.input_tokens == 100
        assert result.output_tokens == 50
        assert result.latency_ms == 450.5
        assert result.confidence == 0.92
        assert result.tool_calls == []

    @pytest.mark.asyncio
    async def test_complete_sends_correct_payload(self, llm_client, mock_http_client):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "content": "ok",
            "model_used": "m",
            "tier_used": "fast",
        }
        mock_response.raise_for_status = MagicMock()
        mock_http_client.post.return_value = mock_response

        await llm_client.complete(
            messages=[{"role": "user", "content": "test"}],
            task="my_task",
            tenant_id="t-1",
            max_tokens=2048,
            temperature=0.5,
        )

        call_kwargs = mock_http_client.post.call_args
        assert call_kwargs.args[0] == "/v1/complete"
        payload = call_kwargs.kwargs["json"]
        assert payload["task"] == "my_task"
        assert payload["max_tokens"] == 2048
        assert payload["temperature"] == 0.5
        assert payload["tenant_id"] == "t-1"

    @pytest.mark.asyncio
    async def test_complete_with_structured_output(self, llm_client, mock_http_client):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"content": "{}", "model_used": "m", "tier_used": "mid"}
        mock_response.raise_for_status = MagicMock()
        mock_http_client.post.return_value = mock_response

        schema = {"type": "object", "properties": {"score": {"type": "number"}}}
        await llm_client.complete(
            messages=[{"role": "user", "content": "evaluate"}],
            task="eval",
            structured_output=schema,
        )

        payload = mock_http_client.post.call_args.kwargs["json"]
        assert payload["structured_output"] == schema


class TestLLMClient5xx:
    """Test 5xx errors raise LLMUnavailableError."""

    @pytest.mark.asyncio
    async def test_500_raises_unavailable(self, llm_client, mock_http_client):
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_http_client.post.return_value = mock_response

        with pytest.raises(LLMUnavailableError, match="returned 500"):
            await llm_client.complete(
                messages=[{"role": "user", "content": "test"}],
                task="eval",
            )

    @pytest.mark.asyncio
    async def test_503_raises_unavailable(self, llm_client, mock_http_client):
        mock_response = MagicMock()
        mock_response.status_code = 503
        mock_http_client.post.return_value = mock_response

        with pytest.raises(LLMUnavailableError, match="returned 503"):
            await llm_client.complete(
                messages=[{"role": "user", "content": "test"}],
                task="eval",
            )

    @pytest.mark.asyncio
    async def test_5xx_includes_context(self, llm_client, mock_http_client):
        mock_response = MagicMock()
        mock_response.status_code = 502
        mock_http_client.post.return_value = mock_response

        with pytest.raises(LLMUnavailableError) as exc_info:
            await llm_client.complete(
                messages=[{"role": "user", "content": "test"}],
                task="my_task",
            )
        assert exc_info.value.context["task"] == "my_task"
        assert exc_info.value.context["status_code"] == 502


class TestLLMClientTimeout:
    """Test timeout raises LLMTimeoutError."""

    @pytest.mark.asyncio
    async def test_timeout_raises_llm_timeout_error(self, llm_client, mock_http_client):
        mock_http_client.post.side_effect = httpx.TimeoutException("timed out")

        with pytest.raises(LLMTimeoutError, match="timed out"):
            await llm_client.complete(
                messages=[{"role": "user", "content": "test"}],
                task="eval",
                tenant_id="t-1",
            )

    @pytest.mark.asyncio
    async def test_timeout_error_includes_context(self, llm_client, mock_http_client):
        mock_http_client.post.side_effect = httpx.TimeoutException("timeout")

        with pytest.raises(LLMTimeoutError) as exc_info:
            await llm_client.complete(
                messages=[{"role": "user", "content": "test"}],
                task="my_task",
                tenant_id="t-123",
            )
        assert exc_info.value.context["task"] == "my_task"
        assert exc_info.value.context["tenant_id"] == "t-123"


class TestLLMClient429:
    """Test 429 raises LLMCreditExhaustedError."""

    @pytest.mark.asyncio
    async def test_429_raises_credit_exhausted(self, llm_client, mock_http_client):
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.content = b'{"message": "Budget exhausted"}'
        mock_response.json.return_value = {
            "message": "Budget exhausted",
            "degradation": {
                "level": 2,
                "tier_availability": {"fast": "available", "mid": "exhausted", "strong": "exhausted"},
                "estimated_recovery": "2025-03-01T00:00:00Z",
                "can_queue": True,
                "queued_position": 3,
            },
        }
        mock_http_client.post.return_value = mock_response

        with pytest.raises(LLMCreditExhaustedError) as exc_info:
            await llm_client.complete(
                messages=[{"role": "user", "content": "test"}],
                task="eval",
                tenant_id="t-1",
            )

        err = exc_info.value
        assert err.degradation_level == 2
        assert err.tier_availability["strong"] == "exhausted"
        assert err.estimated_recovery == "2025-03-01T00:00:00Z"
        assert err.can_queue is True
        assert err.queued_position == 3

    @pytest.mark.asyncio
    async def test_429_empty_body(self, llm_client, mock_http_client):
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.content = b""
        mock_response.json.return_value = {}
        mock_http_client.post.return_value = mock_response

        with pytest.raises(LLMCreditExhaustedError) as exc_info:
            await llm_client.complete(
                messages=[{"role": "user", "content": "test"}],
                task="eval",
            )
        # Default degradation level
        assert exc_info.value.degradation_level == 1


class TestLLMClientConnectError:
    """Test connection failure raises LLMUnavailableError."""

    @pytest.mark.asyncio
    async def test_connect_error_raises_unavailable(self, llm_client, mock_http_client):
        mock_http_client.post.side_effect = httpx.ConnectError("connection refused")

        with pytest.raises(LLMUnavailableError, match="Cannot connect"):
            await llm_client.complete(
                messages=[{"role": "user", "content": "test"}],
                task="eval",
            )


class TestLLMClientEmbed:
    """Test the embed method."""

    @pytest.mark.asyncio
    async def test_embed_success(self, llm_client, mock_http_client):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "embeddings": [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
        }
        mock_response.raise_for_status = MagicMock()
        mock_http_client.post.return_value = mock_response

        result = await llm_client.embed(["hello", "world"], tenant_id="t-1")
        assert len(result) == 2
        assert result[0] == [0.1, 0.2, 0.3]

    @pytest.mark.asyncio
    async def test_embed_timeout(self, llm_client, mock_http_client):
        mock_http_client.post.side_effect = httpx.TimeoutException("timeout")

        with pytest.raises(LLMTimeoutError, match="Embedding request timed out"):
            await llm_client.embed(["hello"])

    @pytest.mark.asyncio
    async def test_embed_5xx(self, llm_client, mock_http_client):
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_http_client.post.return_value = mock_response

        with pytest.raises(LLMUnavailableError, match="returned 500"):
            await llm_client.embed(["hello"])


class TestLLMClientClose:
    """Test client cleanup."""

    @pytest.mark.asyncio
    async def test_close_calls_aclose(self, llm_client, mock_http_client):
        await llm_client.close()
        mock_http_client.aclose.assert_awaited_once()
