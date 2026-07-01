from __future__ import annotations

import asyncio
import hashlib
import hmac
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any

import structlog
import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from src.admin.routes import MetricsResponse, router as admin_router
from src.budget.degradation import DegradationLevel, DegradationManager
from src.budget.queue import RequestQueue
from src.budget.tracker import BudgetTracker
from src.config import GatewaySettings, get_settings
from src.escalation import EscalationEngine
from src.health import HealthManager, router as health_router
from src.models import (
    CompletionRequest,
    CompletionResponse,
    EmbedRequest,
    EmbedResponse,
    ModelConfig,
    NormalizedRequest,
    RoutingConfig,
    ToolCall,
    Usage,
)
from src.providers.base import ProviderAdapter, ProviderError, ProviderRegistry
from src.routing.canary import CanaryManager
from src.routing.config_loader import ConfigLoader
from src.routing.resolver import RouteResolution, RouteResolver

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Metrics store (in-memory aggregation for admin API)
# ---------------------------------------------------------------------------


class MetricsStore:
    """In-memory metrics aggregation for the admin API."""

    def __init__(self) -> None:
        self._records: list[dict[str, Any]] = []
        self._max_records = 100_000

    def record(self, entry: dict[str, Any]) -> None:
        """Record a request metric entry."""
        self._records.append(entry)
        if len(self._records) > self._max_records:
            # Keep most recent half
            self._records = self._records[self._max_records // 2 :]

    def get_summary(self, window: str = "1h") -> MetricsResponse:
        """Get aggregated metrics for a time window."""
        window_seconds = self._parse_window(window)
        cutoff = time.time() - window_seconds

        filtered = [r for r in self._records if r.get("timestamp", 0) >= cutoff]
        if not filtered:
            return MetricsResponse(window=window)

        by_task: dict[str, int] = {}
        by_model: dict[str, int] = {}
        by_tier: dict[str, int] = {}
        total_latency = 0.0
        errors = 0
        escalations = 0

        for r in filtered:
            task = r.get("task", "unknown")
            by_task[task] = by_task.get(task, 0) + 1
            model = r.get("model_used", "unknown")
            by_model[model] = by_model.get(model, 0) + 1
            tier = r.get("tier_used", "unknown")
            by_tier[tier] = by_tier.get(tier, 0) + 1
            total_latency += r.get("latency_ms", 0)
            if r.get("error"):
                errors += 1
            if r.get("escalated"):
                escalations += 1

        total = len(filtered)
        return MetricsResponse(
            window=window,
            total_requests=total,
            by_task=by_task,
            by_model=by_model,
            by_tier=by_tier,
            avg_latency_ms=total_latency / total if total > 0 else 0.0,
            error_rate=errors / total if total > 0 else 0.0,
            escalation_rate=escalations / total if total > 0 else 0.0,
        )

    def get_task_metrics(self, task: str) -> dict[str, Any]:
        """Get metrics for a specific task."""
        cutoff = time.time() - 3600  # default 1h window
        filtered = [
            r for r in self._records
            if r.get("task") == task and r.get("timestamp", 0) >= cutoff
        ]
        if not filtered:
            return {"task": task, "total_requests": 0}

        latencies = [r.get("latency_ms", 0) for r in filtered]
        confidences = [r.get("confidence", 0) for r in filtered]
        errors = sum(1 for r in filtered if r.get("error"))
        escalations = sum(1 for r in filtered if r.get("escalated"))
        total = len(filtered)

        return {
            "task": task,
            "total_requests": total,
            "avg_latency_ms": sum(latencies) / total,
            "avg_confidence": sum(confidences) / total if confidences else 0,
            "error_rate": errors / total,
            "escalation_rate": escalations / total,
        }

    def _parse_window(self, window: str) -> int:
        """Parse window string like '1h', '30m', '24h' to seconds."""
        if window.endswith("h"):
            return int(window[:-1]) * 3600
        if window.endswith("m"):
            return int(window[:-1]) * 60
        if window.endswith("s"):
            return int(window[:-1])
        return 3600  # default 1 hour


# ---------------------------------------------------------------------------
# Provider factory
# ---------------------------------------------------------------------------


def create_provider_adapter(model_config: ModelConfig, settings: GatewaySettings) -> ProviderAdapter:
    """Create the appropriate provider adapter for a model config."""
    provider = model_config.provider.lower()

    if provider == "bedrock":
        from src.providers.bedrock import BedrockAdapter

        return BedrockAdapter(model_config, region=settings.aws_region)

    if provider == "anthropic":
        from src.providers.anthropic import AnthropicAdapter

        # Use model-specific key or default from settings
        if not model_config.api_key and settings.anthropic_api_key:
            model_config.api_key = settings.anthropic_api_key
        return AnthropicAdapter(model_config)

    # For openai, vllm, ollama, and any other OpenAI-compatible
    from src.providers.openai_compat import OpenAICompatAdapter

    if not model_config.api_key and settings.openai_api_key and provider == "openai":
        model_config.api_key = settings.openai_api_key
    return OpenAICompatAdapter(model_config)


# ---------------------------------------------------------------------------
# S2S Auth dependency
# ---------------------------------------------------------------------------

_SERVICE_KEYS: dict[str, str] = {}


async def verify_service(request: Request) -> str:
    """Verify S2S authentication.

    Checks X-Service-Id and X-Service-Key headers against known keys.
    Returns the verified service ID.
    """
    settings: GatewaySettings = request.app.state.settings

    if not settings.service_auth_enabled:
        return "anonymous"

    service_id = request.headers.get("X-Service-Id", "")
    service_key = request.headers.get("X-Service-Key", "")

    if not service_id or not service_key:
        raise HTTPException(status_code=401, detail="Missing service credentials")

    expected_key = _SERVICE_KEYS.get(service_id)
    if expected_key is None:
        raise HTTPException(status_code=401, detail="Unknown service")

    if not hmac.compare_digest(service_key, expected_key):
        raise HTTPException(status_code=401, detail="Invalid service key")

    return service_id


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown."""
    settings = get_settings()
    app.state.settings = settings

    # Initialize structlog
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer()
            if settings.log_format == "console"
            else structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            structlog.get_level_from_name(settings.log_level)
        ),
    )

    # Load routing config
    config_loader = ConfigLoader(settings.routing_config_path)
    config = config_loader.load()
    app.state.config_loader = config_loader

    # Initialize route resolver
    resolver = RouteResolver(config)
    app.state.resolver = resolver

    # Initialize canary manager
    canary_manager = CanaryManager()
    canary_manager.update_from_config(config)
    app.state.canary_manager = canary_manager

    # Initialize escalation engine
    escalation_engine = EscalationEngine(config.escalation)
    app.state.escalation_engine = escalation_engine

    # Initialize provider registry
    provider_registry = ProviderRegistry()
    for tier_config in config.tiers.values():
        for model_config in tier_config.models:
            adapter = create_provider_adapter(model_config, settings)
            provider_registry.register(model_config.id, adapter)
    app.state.provider_registry = provider_registry

    # Initialize health manager
    health_manager = HealthManager(
        interval_seconds=settings.health_check_interval_seconds,
        timeout_ms=settings.health_check_timeout_ms,
    )
    health_manager.set_provider_registry(provider_registry)
    health_manager.update_from_config(config)
    app.state.health_manager = health_manager

    # Initialize budget tracker
    budget_tracker = BudgetTracker(redis_url=settings.redis_url)
    await budget_tracker.connect()
    app.state.budget_tracker = budget_tracker

    # Initialize degradation manager
    degradation_manager = DegradationManager(config.cost)
    app.state.degradation_manager = degradation_manager

    # Initialize request queue
    request_queue = RequestQueue(redis_url=settings.redis_url)
    await request_queue.connect()
    app.state.request_queue = request_queue

    # Initialize metrics store
    metrics_store = MetricsStore()
    app.state.metrics_store = metrics_store

    # Confidence thresholds (overridable via admin API)
    app.state.confidence_thresholds: dict[str, float] = {}

    # Register config reload callback
    def on_config_reload(new_config: RoutingConfig) -> None:
        resolver.update_config(new_config)
        canary_manager.update_from_config(new_config)
        escalation_engine.update_config(new_config.escalation)
        health_manager.update_from_config(new_config)
        degradation_manager.update_config(new_config.cost)

    config_loader.register_on_reload(on_config_reload)

    # Start file watcher for hot-reload
    config_loader.start_watching()

    # Start health check loop
    health_manager.start()

    # Load service keys (simplified: env-based for now)
    _load_service_keys()

    logger.info(
        "llm_gateway_started",
        agent_port=settings.agent_port,
        admin_port=settings.admin_port,
        tiers=list(config.tiers.keys()),
    )

    yield

    # Shutdown
    health_manager.stop()
    config_loader.stop_watching()
    await budget_tracker.close()
    await request_queue.close()
    await provider_registry.close_all()
    logger.info("llm_gateway_stopped")


def _load_service_keys() -> None:
    """Load service authentication keys from environment.

    Configuration via env vars:
    - LLM_GW_SERVICE_KEYS: comma-separated service_id:key pairs
      Example: "agent-eval:secret1,compliance-assistant:secret2"
    - LLM_GW_DEV_KEY: single shared key for all services (dev/test only)

    Production/staging: LLM_GW_SERVICE_KEYS is required. Fails fast if missing.
    Development: Falls back to LLM_GW_DEV_KEY, then to a default dev key with warning.
    """
    import os

    environment = os.environ.get("APP_ENV", os.environ.get("ENVIRONMENT", "development"))

    # Primary: explicit per-service keys
    raw = os.environ.get("LLM_GW_SERVICE_KEYS", "")
    if raw:
        for pair in raw.split(","):
            if ":" in pair:
                svc_id, svc_key = pair.split(":", 1)
                _SERVICE_KEYS[svc_id.strip()] = svc_key.strip()

    if _SERVICE_KEYS:
        logger.info("service_keys_loaded", count=len(_SERVICE_KEYS), source="LLM_GW_SERVICE_KEYS")
        return

    # Production/staging: refuse to start without explicit keys
    if environment in ("production", "staging", "prod"):
        raise RuntimeError(
            "LLM_GW_SERVICE_KEYS must be configured in production/staging. "
            "Set as comma-separated service_id:key pairs. "
            "Example: LLM_GW_SERVICE_KEYS=agent-eval:key1,compliance-assistant:key2"
        )

    # Development: use configurable shared dev key
    dev_key = os.environ.get("LLM_GW_DEV_KEY", "")
    dev_services = ["agent-eval", "compliance-assistant", "observer", "preprocessor", "memory-service"]

    if dev_key:
        for svc in dev_services:
            _SERVICE_KEYS[svc] = dev_key
        logger.info("service_keys_loaded", count=len(dev_services), source="LLM_GW_DEV_KEY")
    else:
        # Last resort: allow startup with a default dev key + warning
        for svc in dev_services:
            _SERVICE_KEYS[svc] = "onpremai-dev-key-change-me"
        logger.warning(
            "service_keys_using_default_dev_key",
            environment=environment,
            hint="Set LLM_GW_SERVICE_KEYS or LLM_GW_DEV_KEY in environment",
        )


# ---------------------------------------------------------------------------
# App creation
# ---------------------------------------------------------------------------


def create_agent_app() -> FastAPI:
    """Create the agent-facing FastAPI app (port 4000)."""
    app = FastAPI(
        title="LLM Gateway - Agent API",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.include_router(health_router)

    @app.post("/v1/complete", response_model=CompletionResponse)
    async def complete(
        request: Request,
        body: CompletionRequest,
        service_id: str = Depends(verify_service),
    ) -> CompletionResponse:
        """Execute an LLM completion with task-based routing."""
        start_time = time.monotonic()
        trace_id = body.trace_id or str(uuid.uuid4())

        resolver: RouteResolver = request.app.state.resolver
        canary_manager: CanaryManager = request.app.state.canary_manager
        escalation_engine: EscalationEngine = request.app.state.escalation_engine
        provider_registry: ProviderRegistry = request.app.state.provider_registry
        budget_tracker: BudgetTracker = request.app.state.budget_tracker
        degradation_manager: DegradationManager = request.app.state.degradation_manager
        request_queue: RequestQueue = request.app.state.request_queue
        metrics_store: MetricsStore = request.app.state.metrics_store
        config_loader: ConfigLoader = request.app.state.config_loader
        confidence_thresholds: dict[str, float] = request.app.state.confidence_thresholds

        # Check budget and degradation
        daily_spend = await budget_tracker.get_daily_spend(body.tenant_id)
        level = degradation_manager.update_for_spend(body.tenant_id, daily_spend)

        if degradation_manager.should_queue(body.tenant_id):
            queue_id = await request_queue.enqueue(body)
            raise HTTPException(
                status_code=429,
                detail={
                    "error": "budget_exhausted",
                    "message": "Daily budget exhausted. Request queued.",
                    "queue_id": queue_id,
                    "degradation_level": level,
                },
            )

        if degradation_manager.should_reject_llm(body.tenant_id):
            raise HTTPException(
                status_code=429,
                detail={
                    "error": "llm_budget_exhausted",
                    "message": "LLM budget exhausted. Only deterministic operations available.",
                    "degradation_level": level,
                },
            )

        # Increment request count
        await budget_tracker.increment_requests(body.tenant_id)

        # Resolve route
        resolution = resolver.resolve(body.agent, body.task, body.tenant_id)

        # Apply degradation tier cap
        capped_tier = degradation_manager.cap_tier(body.tenant_id, resolution.tier)
        if capped_tier != resolution.tier:
            resolution = RouteResolution(tier=capped_tier, source=resolution.source)

        # Check canary
        use_canary, variant = canary_manager.should_use_canary(body.agent, body.task)
        canary_model_id: str | None = None
        if use_canary:
            canary_model_id = canary_manager.get_canary_model_id(body.agent, body.task)

        # Apply confidence threshold override from admin API
        effective_threshold = body.confidence_threshold
        if body.task in confidence_thresholds:
            effective_threshold = max(effective_threshold, confidence_thresholds[body.task])

        # Execute with escalation loop
        escalation_count = 0
        escalation_path: list[str] = []
        current_tier = resolution.tier
        best_response: NormalizedResponse | None = None
        best_confidence = 0.0
        model_used = ""
        tier_used = ""

        while True:
            # Get models for current tier
            models = resolver.get_models_for_tier(current_tier)

            # If canary, prepend canary model
            target_model_id = canary_model_id if use_canary and canary_model_id else None

            # If resolution specifies a specific model, use it
            if resolution.model_config is not None and escalation_count == 0:
                target_model_id = resolution.model_config.id

            # Try each model in the tier (fallback within tier)
            response = await _try_tier_models(
                models=models,
                target_model_id=target_model_id,
                request=body,
                provider_registry=provider_registry,
            )

            if response is None:
                # All models in tier failed
                if escalation_engine.enabled and escalation_count < escalation_engine.max_escalations:
                    next_tier = escalation_engine.get_next_tier(current_tier)
                    if next_tier and degradation_manager.is_tier_allowed(body.tenant_id, next_tier):
                        escalation_path.append(current_tier)
                        current_tier = next_tier
                        escalation_count += 1
                        continue
                # No more options
                break

            response_data, used_model, used_tier = response
            model_used = used_model
            tier_used = used_tier

            # Check escalation
            decision = escalation_engine.check(response_data, body, escalation_count)

            if decision.confidence > best_confidence:
                best_response = response_data
                best_confidence = decision.confidence

            if not decision.should_escalate:
                best_response = response_data
                best_confidence = decision.confidence
                break

            # Escalate to next tier
            next_tier = escalation_engine.get_next_tier(current_tier)
            if next_tier is None or escalation_count >= escalation_engine.max_escalations:
                break
            if not degradation_manager.is_tier_allowed(body.tenant_id, next_tier):
                break

            escalation_path.append(current_tier)
            current_tier = next_tier
            escalation_count += 1

        # Build response
        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        escalated = escalation_count > 0

        if best_response is None:
            # Total failure
            metrics_store.record({
                "timestamp": time.time(),
                "task": body.task,
                "model_used": "",
                "tier_used": current_tier,
                "latency_ms": elapsed_ms,
                "error": True,
                "escalated": escalated,
                "confidence": 0.0,
                "tenant_id": body.tenant_id,
            })
            raise HTTPException(
                status_code=503,
                detail="All models unavailable. Please retry.",
            )

        # Calculate cost
        adapter = provider_registry.get(model_used)
        cost_usd = 0.0
        if adapter:
            cost_usd = adapter.estimate_cost(
                best_response.usage.input_tokens,
                best_response.usage.output_tokens,
            )

        # Record cost
        await budget_tracker.record_cost(body.tenant_id, cost_usd)

        # Record metrics
        metrics_store.record({
            "timestamp": time.time(),
            "task": body.task,
            "agent": body.agent,
            "model_used": model_used,
            "tier_used": tier_used,
            "latency_ms": elapsed_ms,
            "error": False,
            "escalated": escalated,
            "confidence": best_confidence,
            "tenant_id": body.tenant_id,
            "cost_usd": cost_usd,
            "input_tokens": best_response.usage.input_tokens,
            "output_tokens": best_response.usage.output_tokens,
            "trace_id": trace_id,
            "variant": variant,
        })

        # Record canary metrics
        if use_canary:
            canary_manager.record_result(
                agent=body.agent,
                task=body.task,
                variant=variant,
                confidence=best_confidence,
                latency_ms=elapsed_ms,
                error=False,
                escalated=escalated,
                cost_usd=cost_usd,
            )

        # Log for observer
        logger.info(
            "completion_served",
            trace_id=trace_id,
            agent=body.agent,
            task=body.task,
            tenant_id=body.tenant_id,
            model_used=model_used,
            tier_used=tier_used,
            escalated=escalated,
            escalation_path=escalation_path,
            latency_ms=elapsed_ms,
            confidence=best_confidence,
            cost_usd=cost_usd,
            input_tokens=best_response.usage.input_tokens,
            output_tokens=best_response.usage.output_tokens,
            variant=variant,
        )

        return CompletionResponse(
            content=best_response.content,
            model_used=model_used,
            tier_used=tier_used,
            escalated=escalated,
            escalation_path=escalation_path,
            usage=best_response.usage,
            latency_ms=elapsed_ms,
            confidence=best_confidence,
            tool_calls=best_response.tool_calls,
            cost_usd=cost_usd,
            trace_id=trace_id,
        )

    @app.post("/v1/embed", response_model=EmbedResponse)
    async def embed(
        request: Request,
        body: EmbedRequest,
        service_id: str = Depends(verify_service),
    ) -> EmbedResponse:
        """Generate embeddings for the given texts."""
        start_time = time.monotonic()
        config_loader: ConfigLoader = request.app.state.config_loader
        provider_registry: ProviderRegistry = request.app.state.provider_registry

        config = config_loader.config
        emb_config = config.embedding.model

        # Find or create adapter for embedding model
        adapter: ProviderAdapter | None = None
        # Try to find an existing adapter that supports embeddings
        for tier_config in config.tiers.values():
            for model_config in tier_config.models:
                if model_config.provider == emb_config.provider:
                    adapter = provider_registry.get(model_config.id)
                    if adapter:
                        break
            if adapter:
                break

        if adapter is None:
            # Create a temporary adapter for embedding
            from src.models import ModelConfig

            emb_model_config = ModelConfig(
                id="embedding-model",
                provider=emb_config.provider,
                model=emb_config.model,
                endpoint=emb_config.endpoint,
            )
            adapter = create_provider_adapter(emb_model_config, request.app.state.settings)

        try:
            embeddings = await adapter.embed(body.texts)
        except ProviderError as exc:
            raise HTTPException(status_code=503, detail=str(exc))

        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        return EmbedResponse(
            embeddings=embeddings,
            model_used=emb_config.model,
            latency_ms=elapsed_ms,
        )

    return app


def create_admin_app() -> FastAPI:
    """Create the admin-facing FastAPI app (port 4001)."""
    app = FastAPI(
        title="LLM Gateway - Admin API",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.include_router(admin_router)
    app.include_router(health_router)
    return app


async def _try_tier_models(
    models: list[ModelConfig],
    target_model_id: str | None,
    request: CompletionRequest,
    provider_registry: ProviderRegistry,
) -> tuple[NormalizedResponse, str, str] | None:
    """Try each model in a tier until one succeeds.

    If target_model_id is specified, try that model first.
    Falls back to remaining models in order.

    Returns:
        Tuple of (response, model_id, tier_name) or None if all failed.
    """
    ordered_models = list(models)

    # Move target model to front if specified
    if target_model_id:
        target_models = [m for m in ordered_models if m.id == target_model_id]
        other_models = [m for m in ordered_models if m.id != target_model_id]
        ordered_models = target_models + other_models

    for model_config in ordered_models:
        if not model_config.healthy or not model_config.enabled:
            continue

        adapter = provider_registry.get(model_config.id)
        if adapter is None:
            continue

        # Build normalized request
        normalized = NormalizedRequest(
            messages=request.messages,
            tools=request.tools,
            max_tokens=min(request.max_tokens, model_config.max_tokens),
            temperature=request.temperature,
            response_format=request.response_format,
            stop=request.stop,
            model=model_config.model,
        )

        try:
            response = await adapter.complete(normalized)
            # Find which tier this model belongs to
            tier = "unknown"
            return response, model_config.id, tier
        except ProviderError as exc:
            logger.warning(
                "model_request_failed",
                model_id=model_config.id,
                error=str(exc),
            )
            continue
        except Exception as exc:
            logger.error(
                "model_request_unexpected_error",
                model_id=model_config.id,
                error=str(exc),
            )
            continue

    return None


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Run the LLM Gateway with dual-port serving."""
    settings = get_settings()

    # We run the agent app on the main thread and admin on a separate server
    agent_app = create_agent_app()

    # For dual-port, we use a shared lifespan via the agent app
    # and run admin as a sub-application or on a second uvicorn instance.
    # In production, both are started via the same process with asyncio.

    async def serve() -> None:
        agent_config = uvicorn.Config(
            app=agent_app,
            host="0.0.0.0",
            port=settings.agent_port,
            log_level=settings.log_level.lower(),
        )
        admin_app = create_admin_app()
        admin_config = uvicorn.Config(
            app=admin_app,
            host="0.0.0.0",
            port=settings.admin_port,
            log_level=settings.log_level.lower(),
        )

        agent_server = uvicorn.Server(agent_config)
        admin_server = uvicorn.Server(admin_config)

        await asyncio.gather(
            agent_server.serve(),
            admin_server.serve(),
        )

    asyncio.run(serve())


if __name__ == "__main__":
    main()
