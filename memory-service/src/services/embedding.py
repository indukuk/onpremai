from __future__ import annotations

import structlog
import httpx

from src.config import settings

logger = structlog.get_logger(__name__)


class EmbeddingService:
    """Calls LLM Gateway /v1/embed for vector generation."""

    def __init__(self, gateway_url: str | None = None, timeout: float = 10.0) -> None:
        self._gateway_url = (gateway_url or settings.LLM_GATEWAY_URL).rstrip("/")
        self._timeout = timeout

    async def embed(self, text: str) -> list[float] | None:
        """
        Generate an embedding vector for the given text.
        Returns None if the gateway is unavailable or errors occur.
        """
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    f"{self._gateway_url}/v1/embed",
                    json={"text": text, "model": "nomic-embed-text"},
                )
                if response.status_code == 200:
                    data = response.json()
                    embedding = data.get("embedding")
                    if embedding and isinstance(embedding, list):
                        return embedding
                    logger.warning(
                        "embedding_response_invalid",
                        status=response.status_code,
                        body=data,
                    )
                    return None
                logger.warning(
                    "embedding_request_failed",
                    status=response.status_code,
                    body=response.text[:200],
                )
                return None
        except (httpx.HTTPError, httpx.TimeoutException) as exc:
            logger.warning("embedding_service_unavailable", error=str(exc))
            return None

    async def embed_batch(self, texts: list[str]) -> list[list[float] | None]:
        """Embed multiple texts. Returns list aligned with input (None for failures)."""
        results: list[list[float] | None] = []
        for text in texts:
            result = await self.embed(text)
            results.append(result)
        return results
