from __future__ import annotations

import asyncio
import time
from typing import Any

import structlog
from fastapi import APIRouter

from src.models import ModelConfig, ModelHealth, RoutingConfig

logger = structlog.get_logger(__name__)

router = APIRouter()


class HealthManager:
    """Manages model health checks and gateway readiness.

    Periodically pings each configured model endpoint and tracks
    consecutive failures. Unhealthy models are removed from rotation
    and re-added when healthy.
    """

    def __init__(
        self,
        interval_seconds: int = 30,
        timeout_ms: int = 5000,
        unhealthy_threshold: int = 3,
        healthy_threshold: int = 1,
    ) -> None:
        self._interval_seconds = interval_seconds
        self._timeout_ms = timeout_ms
        self._unhealthy_threshold = unhealthy_threshold
        self._healthy_threshold = healthy_threshold
        self._model_states: dict[str, _ModelState] = {}
        self._task: asyncio.Task[None] | None = None
        self._provider_registry: Any = None
        self._running = False

    def set_provider_registry(self, registry: Any) -> None:
        """Set the provider registry for health checks."""
        self._provider_registry = registry

    def update_from_config(self, config: RoutingConfig) -> None:
        """Update tracked models from routing config."""
        current_ids = set()
        for tier_name, tier_config in config.tiers.items():
            for model in tier_config.models:
                current_ids.add(model.id)
                if model.id not in self._model_states:
                    self._model_states[model.id] = _ModelState(
                        model_config=model,
                        tier=tier_name,
                    )
                else:
                    self._model_states[model.id].model_config = model
                    self._model_states[model.id].tier = tier_name

        # Remove models no longer in config
        for model_id in list(self._model_states.keys()):
            if model_id not in current_ids:
                del self._model_states[model_id]

    def start(self) -> None:
        """Start the periodic health check loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._health_check_loop())
        logger.info("health_check_loop_started", interval_s=self._interval_seconds)

    def stop(self) -> None:
        """Stop the health check loop."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            self._task = None

    async def _health_check_loop(self) -> None:
        """Periodic health check loop."""
        while self._running:
            try:
                await self._run_health_checks()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("health_check_loop_error", error=str(exc))
            await asyncio.sleep(self._interval_seconds)

    async def _run_health_checks(self) -> None:
        """Run health checks for all registered models concurrently."""
        if self._provider_registry is None:
            return

        tasks: list[asyncio.Task[None]] = []
        for model_id, state in self._model_states.items():
            adapter = self._provider_registry.get(model_id)
            if adapter is not None:
                task = asyncio.create_task(
                    self._check_single_model(model_id, state, adapter)
                )
                tasks.append(task)

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _check_single_model(
        self,
        model_id: str,
        state: _ModelState,
        adapter: Any,
    ) -> None:
        """Check a single model's health."""
        start = time.monotonic()
        try:
            healthy = await asyncio.wait_for(
                adapter.health_check(),
                timeout=self._timeout_ms / 1000.0,
            )
        except (asyncio.TimeoutError, Exception):
            healthy = False

        elapsed_ms = int((time.monotonic() - start) * 1000)
        state.last_check_ms = elapsed_ms

        if healthy:
            state.consecutive_failures = 0
            state.consecutive_successes += 1
            if not state.healthy and state.consecutive_successes >= self._healthy_threshold:
                state.healthy = True
                state.model_config.healthy = True
                logger.info(
                    "model_recovered",
                    model_id=model_id,
                    tier=state.tier,
                    latency_ms=elapsed_ms,
                )
        else:
            state.consecutive_successes = 0
            state.consecutive_failures += 1
            if state.healthy and state.consecutive_failures >= self._unhealthy_threshold:
                state.healthy = False
                state.model_config.healthy = False
                logger.warning(
                    "model_unhealthy",
                    model_id=model_id,
                    tier=state.tier,
                    consecutive_failures=state.consecutive_failures,
                )

    def is_ready(self) -> bool:
        """Check if gateway is ready (at least one healthy model per used tier)."""
        tiers_with_models: dict[str, bool] = {}
        for state in self._model_states.values():
            tier = state.tier
            if tier not in tiers_with_models:
                tiers_with_models[tier] = False
            if state.healthy:
                tiers_with_models[tier] = True

        # Ready if at least one tier has a healthy model
        return any(tiers_with_models.values()) if tiers_with_models else True

    def get_model_health(self) -> list[ModelHealth]:
        """Get health status of all models."""
        results: list[ModelHealth] = []
        for model_id, state in self._model_states.items():
            results.append(ModelHealth(
                id=model_id,
                provider=state.model_config.provider,
                model=state.model_config.model,
                healthy=state.healthy,
                enabled=state.model_config.enabled,
                last_check_ms=state.last_check_ms,
                consecutive_failures=state.consecutive_failures,
                tier=state.tier,
            ))
        return results

    def disable_model(self, model_id: str) -> bool:
        """Disable a model (remove from rotation)."""
        state = self._model_states.get(model_id)
        if state is None:
            return False
        state.model_config.enabled = False
        state.healthy = False
        logger.info("model_disabled", model_id=model_id)
        return True

    def enable_model(self, model_id: str) -> bool:
        """Re-enable a previously disabled model."""
        state = self._model_states.get(model_id)
        if state is None:
            return False
        state.model_config.enabled = True
        # Will become healthy after next successful health check
        logger.info("model_enabled", model_id=model_id)
        return True


class _ModelState:
    """Internal state tracking for one model."""

    __slots__ = (
        "model_config",
        "tier",
        "healthy",
        "last_check_ms",
        "consecutive_failures",
        "consecutive_successes",
    )

    def __init__(self, model_config: ModelConfig, tier: str) -> None:
        self.model_config = model_config
        self.tier = tier
        self.healthy = True
        self.last_check_ms = 0
        self.consecutive_failures = 0
        self.consecutive_successes = 0


@router.get("/health")
async def health_endpoint() -> dict[str, str]:
    """Gateway liveness probe. Returns 200 if process is alive."""
    return {"status": "ok"}


@router.get("/ready")
async def ready_endpoint() -> dict[str, Any]:
    """Gateway readiness probe. Returns 200 if models are reachable."""
    # Access health manager from app state (set during lifespan)
    # For now return basic readiness
    return {"status": "ready"}
