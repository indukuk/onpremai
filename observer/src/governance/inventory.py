"""Model inventory — tracks all models available in the LLM gateway.

Reads routing configuration from the gateway admin API to build a live
inventory of models, their tiers, tasks, and health status.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx
import structlog

from observer.src.config import ObserverSettings

logger = structlog.get_logger(__name__)


@dataclass
class ModelRecord:
    """A single model in the inventory."""

    model_id: str
    provider: str = ""
    tier: str = ""
    tasks: list[str] = field(default_factory=list)
    max_tokens: int = 0
    cost_per_1k_input: float = 0.0
    cost_per_1k_output: float = 0.0
    status: str = "active"
    last_seen: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    avg_latency_ms: float = 0.0
    error_rate: float = 0.0
    total_requests_24h: int = 0


@dataclass
class ModelInventory:
    """Complete model inventory snapshot."""

    models: dict[str, ModelRecord] = field(default_factory=dict)
    total_models: int = 0
    active_models: int = 0
    degraded_models: int = 0
    inactive_models: int = 0
    last_refreshed: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    routing_config_hash: str = ""


class ModelInventoryManager:
    """Manages the model inventory by reading from the gateway admin API.

    Periodically refreshes the inventory to detect new models, removed models,
    and changes in tier assignments. Tracks model health over time.
    """

    def __init__(self, settings: ObserverSettings) -> None:
        self._settings = settings
        self._http_client: httpx.AsyncClient | None = None
        self._inventory: ModelInventory = ModelInventory()
        self._history: list[ModelInventory] = []

    async def start(self) -> None:
        """Initialize the HTTP client."""
        self._http_client = httpx.AsyncClient(
            base_url=self._settings.llm_gateway_admin_url,
            timeout=httpx.Timeout(30.0),
        )

    async def close(self) -> None:
        """Shutdown the HTTP client."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None

    async def refresh(self) -> ModelInventory:
        """Refresh the model inventory from the gateway admin API.

        Fetches routing config and metrics to build a complete picture.

        Returns:
            Updated ModelInventory snapshot.
        """
        routing_config = await self._fetch_routing_config()
        metrics = await self._fetch_model_metrics()

        models: dict[str, ModelRecord] = {}

        # Parse routing config into model records
        tiers = routing_config.get("tiers", {})
        task_routing = routing_config.get("task_routing", {})

        # Build tier-to-models mapping
        for tier_name, tier_config in tiers.items():
            tier_models = tier_config if isinstance(tier_config, list) else tier_config.get("models", [])
            for model_entry in tier_models:
                model_id = model_entry if isinstance(model_entry, str) else model_entry.get("model_id", "")
                if not model_id:
                    continue

                provider = self._extract_provider(model_id)
                record = models.get(model_id, ModelRecord(model_id=model_id, provider=provider))
                record.tier = tier_name

                if isinstance(model_entry, dict):
                    record.max_tokens = model_entry.get("max_tokens", record.max_tokens)
                    record.cost_per_1k_input = model_entry.get("cost_per_1k_input", record.cost_per_1k_input)
                    record.cost_per_1k_output = model_entry.get("cost_per_1k_output", record.cost_per_1k_output)

                models[model_id] = record

        # Map tasks to models via routing
        for task_name, task_config in task_routing.items():
            target_tier = task_config if isinstance(task_config, str) else task_config.get("tier", "")
            for model_id, record in models.items():
                if record.tier == target_tier:
                    if task_name not in record.tasks:
                        record.tasks.append(task_name)

        # Enrich with metrics
        for model_id, model_metrics in metrics.items():
            if model_id in models:
                models[model_id].avg_latency_ms = model_metrics.get("avg_latency_ms", 0.0)
                models[model_id].error_rate = model_metrics.get("error_rate", 0.0)
                models[model_id].total_requests_24h = model_metrics.get("total_requests_24h", 0)
                models[model_id].last_seen = model_metrics.get("last_seen", models[model_id].last_seen)

                # Determine status based on error rate
                error_rate = models[model_id].error_rate
                if error_rate > 0.10:
                    models[model_id].status = "degraded"
                elif error_rate > 0.50:
                    models[model_id].status = "inactive"
                else:
                    models[model_id].status = "active"

        # Build inventory
        active_count = sum(1 for m in models.values() if m.status == "active")
        degraded_count = sum(1 for m in models.values() if m.status == "degraded")
        inactive_count = sum(1 for m in models.values() if m.status == "inactive")

        import hashlib
        import json

        config_str = json.dumps(routing_config, sort_keys=True, default=str)
        config_hash = hashlib.sha256(config_str.encode()).hexdigest()[:16]

        self._inventory = ModelInventory(
            models=models,
            total_models=len(models),
            active_models=active_count,
            degraded_models=degraded_count,
            inactive_models=inactive_count,
            last_refreshed=datetime.now(timezone.utc).isoformat(),
            routing_config_hash=config_hash,
        )

        # Keep history (max 30 snapshots for weekly reporting)
        self._history.append(self._inventory)
        if len(self._history) > 30:
            self._history = self._history[-30:]

        logger.info(
            "model_inventory_refreshed",
            total=len(models),
            active=active_count,
            degraded=degraded_count,
            inactive=inactive_count,
        )

        return self._inventory

    @property
    def current(self) -> ModelInventory:
        """Get the current inventory snapshot."""
        return self._inventory

    @property
    def history(self) -> list[ModelInventory]:
        """Get inventory history for trend analysis."""
        return list(self._history)

    async def _fetch_routing_config(self) -> dict[str, Any]:
        """Fetch current routing configuration from the gateway."""
        if not self._http_client:
            return {}

        try:
            response = await self._http_client.get("/admin/routing")
            if response.status_code == 200:
                return response.json()
            logger.warning("routing_config_fetch_failed", status=response.status_code)
        except httpx.HTTPError as exc:
            logger.error("routing_config_fetch_error", error=str(exc))

        return {}

    async def _fetch_model_metrics(self) -> dict[str, Any]:
        """Fetch per-model metrics from the gateway."""
        if not self._http_client:
            return {}

        try:
            response = await self._http_client.get(
                "/admin/metrics/models",
                params={"window": "24h"},
            )
            if response.status_code == 200:
                return response.json()
            logger.warning("model_metrics_fetch_failed", status=response.status_code)
        except httpx.HTTPError as exc:
            logger.error("model_metrics_fetch_error", error=str(exc))

        return {}

    @staticmethod
    def _extract_provider(model_id: str) -> str:
        """Extract provider name from model ID.

        Examples:
            anthropic.claude-3-5-sonnet -> anthropic
            meta.llama3-70b -> meta
            amazon.titan-text-express -> amazon
        """
        if "." in model_id:
            return model_id.split(".")[0]
        if "/" in model_id:
            return model_id.split("/")[0]
        return "unknown"

    def detect_config_changes(self, previous_hash: str) -> bool:
        """Detect whether routing configuration has changed since last check."""
        return self._inventory.routing_config_hash != previous_hash

    def get_models_by_tier(self, tier: str) -> list[ModelRecord]:
        """Get all models in a specific tier."""
        return [m for m in self._inventory.models.values() if m.tier == tier]

    def get_degraded_models(self) -> list[ModelRecord]:
        """Get models currently in degraded or inactive state."""
        return [
            m for m in self._inventory.models.values()
            if m.status in ("degraded", "inactive")
        ]
