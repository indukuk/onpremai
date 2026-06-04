from __future__ import annotations

import abc

from src.models import ModelConfig, NormalizedRequest, NormalizedResponse


class ProviderAdapter(abc.ABC):
    """Abstract base class for all LLM provider adapters.

    Each adapter translates between the gateway's normalized format
    and the provider-specific API format. Adapters are stateless
    and independently testable.
    """

    def __init__(self, model_config: ModelConfig) -> None:
        self._model_config = model_config

    @property
    def model_id(self) -> str:
        """Unique model identifier from config."""
        return self._model_config.id

    @property
    def provider_name(self) -> str:
        """Provider name (e.g., 'bedrock', 'anthropic', 'ollama')."""
        return self._model_config.provider

    @property
    def model_name(self) -> str:
        """Provider-specific model name."""
        return self._model_config.model

    @property
    def timeout_ms(self) -> int:
        """Request timeout in milliseconds."""
        return self._model_config.timeout_ms

    @abc.abstractmethod
    async def complete(self, request: NormalizedRequest) -> NormalizedResponse:
        """Execute a completion request against this provider.

        Args:
            request: Normalized request with messages, tools, parameters.

        Returns:
            NormalizedResponse with content, tool_calls, usage.

        Raises:
            ProviderError: On any provider communication failure.
        """
        ...

    @abc.abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for the given texts.

        Args:
            texts: List of strings to embed.

        Returns:
            List of embedding vectors.

        Raises:
            ProviderError: If embedding is not supported or fails.
        """
        ...

    @abc.abstractmethod
    async def health_check(self) -> bool:
        """Check if this provider/model is reachable and healthy.

        Returns:
            True if healthy, False otherwise.
        """
        ...

    def estimate_cost(self, input_tokens: int, output_tokens: int) -> float:
        """Estimate cost for a given token count.

        Default implementation returns 0.0 (local models).
        Override in cloud provider adapters with actual pricing.
        """
        return 0.0

    async def close(self) -> None:
        """Clean up resources (e.g., HTTP clients). Override if needed."""
        pass


class ProviderError(Exception):
    """Raised when a provider call fails."""

    def __init__(self, provider: str, model: str, message: str, status_code: int = 0) -> None:
        self.provider = provider
        self.model = model
        self.status_code = status_code
        super().__init__(f"[{provider}/{model}] {message}")


class ProviderRegistry:
    """Registry of provider adapter instances, keyed by model ID."""

    def __init__(self) -> None:
        self._adapters: dict[str, ProviderAdapter] = {}

    def register(self, model_id: str, adapter: ProviderAdapter) -> None:
        """Register an adapter for a model ID."""
        self._adapters[model_id] = adapter

    def get(self, model_id: str) -> ProviderAdapter | None:
        """Get the adapter for a model ID."""
        return self._adapters.get(model_id)

    def all_adapters(self) -> dict[str, ProviderAdapter]:
        """Get all registered adapters."""
        return dict(self._adapters)

    async def close_all(self) -> None:
        """Close all adapter resources."""
        for adapter in self._adapters.values():
            await adapter.close()
        self._adapters.clear()
