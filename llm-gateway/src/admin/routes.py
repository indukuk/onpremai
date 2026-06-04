from __future__ import annotations

import hmac
import os
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from src.models import BudgetStatus, CanaryStatus, ModelHealth

logger = structlog.get_logger(__name__)


async def verify_admin_key(x_admin_key: str = Header(..., alias="X-Admin-Key")) -> str:
    """Verify admin API key from X-Admin-Key header.

    Compares against the LLM_GW_ADMIN_KEY environment variable.
    Raises 401 if missing or invalid.
    """
    expected = os.environ.get("LLM_GW_ADMIN_KEY", "")
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="Admin API key not configured (LLM_GW_ADMIN_KEY not set)",
        )
    if not hmac.compare_digest(x_admin_key, expected):
        raise HTTPException(status_code=401, detail="Invalid admin key")
    return x_admin_key


router = APIRouter(prefix="/admin", dependencies=[Depends(verify_admin_key)])


class RoutingUpdateRequest(BaseModel):
    """Request body for POST /admin/routing."""

    task_routing: dict[str, str] | None = None
    agent_routing: dict[str, Any] | None = None
    tenant_routing: dict[str, Any] | None = None


class ThresholdUpdateRequest(BaseModel):
    """Request body for POST /admin/threshold."""

    task: str
    confidence_threshold: float = Field(ge=0.0, le=1.0)


class CanarySetRequest(BaseModel):
    """Request body for POST /admin/canary/{task}/set."""

    model: str
    traffic_pct: int = Field(default=20, ge=1, le=100)
    min_samples: int = Field(default=30, ge=1)


class MetricsResponse(BaseModel):
    """Response from GET /admin/metrics."""

    window: str = "1h"
    total_requests: int = 0
    by_task: dict[str, int] = Field(default_factory=dict)
    by_model: dict[str, int] = Field(default_factory=dict)
    by_tier: dict[str, int] = Field(default_factory=dict)
    avg_latency_ms: float = 0.0
    error_rate: float = 0.0
    escalation_rate: float = 0.0


@router.get("/metrics")
async def get_metrics(request: Request, window: str = "1h") -> MetricsResponse:
    """Get aggregated metrics for the given time window."""
    metrics_store = request.app.state.metrics_store
    return metrics_store.get_summary(window)


@router.get("/metrics/{task}")
async def get_task_metrics(request: Request, task: str) -> dict[str, Any]:
    """Get metrics for a specific task."""
    metrics_store = request.app.state.metrics_store
    return metrics_store.get_task_metrics(task)


@router.post("/routing")
async def update_routing(request: Request, body: RoutingUpdateRequest) -> dict[str, Any]:
    """Update routing configuration programmatically."""
    config_loader = request.app.state.config_loader
    updates: dict[str, Any] = {}

    if body.task_routing is not None:
        updates["task_routing"] = body.task_routing
    if body.agent_routing is not None:
        updates["agent_routing"] = body.agent_routing
    if body.tenant_routing is not None:
        updates["tenant_routing"] = body.tenant_routing

    if not updates:
        raise HTTPException(status_code=400, detail="No routing updates provided")

    new_config = config_loader.update_routing(updates)

    # Notify resolver of config change
    resolver = request.app.state.resolver
    resolver.update_config(new_config)

    logger.info("routing_updated_via_admin", updates=list(updates.keys()))
    return {"status": "applied", "updates": list(updates.keys())}


@router.post("/threshold")
async def update_threshold(request: Request, body: ThresholdUpdateRequest) -> dict[str, Any]:
    """Update confidence threshold for a specific task."""
    # Store threshold override in app state
    thresholds = request.app.state.confidence_thresholds
    previous = thresholds.get(body.task)
    thresholds[body.task] = body.confidence_threshold

    logger.info(
        "threshold_updated",
        task=body.task,
        new_threshold=body.confidence_threshold,
        previous=previous,
    )
    return {
        "status": "applied",
        "task": body.task,
        "threshold": body.confidence_threshold,
        "previous": previous,
    }


@router.post("/reload")
async def reload_config(request: Request) -> dict[str, Any]:
    """Force hot-reload of routing config from file."""
    config_loader = request.app.state.config_loader
    new_config = config_loader.reload()

    # Update all components that depend on config
    resolver = request.app.state.resolver
    resolver.update_config(new_config)

    canary_manager = request.app.state.canary_manager
    canary_manager.update_from_config(new_config)

    health_manager = request.app.state.health_manager
    health_manager.update_from_config(new_config)

    logger.info("config_reloaded_via_admin")
    return {"status": "reloaded", "tiers": list(new_config.tiers.keys())}


@router.get("/canary/{task}/metrics")
async def get_canary_metrics(request: Request, task: str) -> CanaryStatus:
    """Get canary experiment metrics for a task."""
    canary_manager = request.app.state.canary_manager
    status = canary_manager.get_status(task)
    if status is None:
        raise HTTPException(status_code=404, detail=f"No canary experiment for task: {task}")
    return status


@router.post("/canary/{task}/set")
async def set_canary(request: Request, task: str, body: CanarySetRequest) -> CanaryStatus:
    """Start or update a canary experiment for a task."""
    canary_manager = request.app.state.canary_manager
    status = canary_manager.set_canary(
        task_key=task,
        model=body.model,
        traffic_pct=body.traffic_pct,
        min_samples=body.min_samples,
    )
    return status


@router.post("/canary/{task}/promote")
async def promote_canary(request: Request, task: str) -> dict[str, Any]:
    """Promote canary to primary (100% traffic)."""
    canary_manager = request.app.state.canary_manager
    success = canary_manager.promote_canary(task)
    if not success:
        raise HTTPException(status_code=404, detail=f"No canary experiment for task: {task}")
    return {"status": "promoted", "task": task}


@router.post("/canary/{task}/rollback")
async def rollback_canary(request: Request, task: str) -> dict[str, Any]:
    """Rollback canary experiment (remove, revert to control)."""
    canary_manager = request.app.state.canary_manager
    success = canary_manager.rollback_canary(task)
    if not success:
        raise HTTPException(status_code=404, detail=f"No canary experiment for task: {task}")
    return {"status": "rolled_back", "task": task}


@router.get("/models")
async def list_models(request: Request) -> list[ModelHealth]:
    """List all configured models and their health status."""
    health_manager = request.app.state.health_manager
    return health_manager.get_model_health()


@router.post("/models/{model_id}/disable")
async def disable_model(request: Request, model_id: str) -> dict[str, Any]:
    """Temporarily disable a model (remove from rotation)."""
    health_manager = request.app.state.health_manager
    success = health_manager.disable_model(model_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Model not found: {model_id}")
    return {"status": "disabled", "model_id": model_id}


@router.get("/budget/{tenant_id}")
async def get_budget(request: Request, tenant_id: str) -> BudgetStatus:
    """Get budget status for a tenant."""
    budget_tracker = request.app.state.budget_tracker
    degradation_manager = request.app.state.degradation_manager
    request_queue = request.app.state.request_queue

    daily_spend = await budget_tracker.get_daily_spend(tenant_id)
    requests_today = await budget_tracker.get_request_count(tenant_id)
    queued = await request_queue.queue_length(tenant_id)
    level = degradation_manager.get_level(tenant_id)

    config = request.app.state.config_loader.config
    daily_limit = config.cost.max_per_tenant_per_day_usd

    return BudgetStatus(
        tenant_id=tenant_id,
        daily_spend_usd=daily_spend,
        daily_limit_usd=daily_limit,
        degradation_level=level,
        requests_today=requests_today,
        queued_requests=queued,
    )
