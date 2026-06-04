"""Health and readiness endpoints for the observer service.

Provides:
- GET /health — basic liveness check (always returns 200 if process is alive)
- GET /ready — readiness check (verifies scheduler is running and dependencies reachable)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx
import structlog
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from observer.src.config import ObserverSettings

logger = structlog.get_logger(__name__)

health_router = APIRouter(tags=["health"])


@health_router.get("/health")
async def health_check(request: Request) -> dict[str, str]:
    """Liveness probe — returns 200 if the process is alive."""
    return {
        "status": "healthy",
        "service": "observer",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@health_router.get("/ready")
async def readiness_check(request: Request) -> JSONResponse:
    """Readiness probe — verifies scheduler and dependencies are operational.

    Checks:
    1. Scheduler is running
    2. LLM Gateway admin API is reachable
    3. Memory service is reachable
    """
    state = request.app.state
    settings: ObserverSettings = state.settings
    checks: dict[str, Any] = {}
    all_ready = True

    # Check scheduler
    scheduler_running = state.scheduler.is_running if hasattr(state, "scheduler") else False
    checks["scheduler"] = {"ready": scheduler_running}
    if not scheduler_running:
        all_ready = False

    # Check LLM Gateway admin API
    gateway_ready = await _check_endpoint(
        settings.llm_gateway_admin_url + "/health"
    )
    checks["llm_gateway_admin"] = {"ready": gateway_ready, "url": settings.llm_gateway_admin_url}
    if not gateway_ready:
        all_ready = False

    # Check Memory Service
    memory_ready = await _check_endpoint(settings.memory_url + "/health")
    checks["memory_service"] = {"ready": memory_ready, "url": settings.memory_url}
    if not memory_ready:
        all_ready = False

    status_code = 200 if all_ready else 503
    response_body = {
        "status": "ready" if all_ready else "not_ready",
        "service": "observer",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
    }

    return JSONResponse(content=response_body, status_code=status_code)


async def _check_endpoint(url: str) -> bool:
    """Check if an HTTP endpoint is reachable and healthy."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
            response = await client.get(url)
            return response.status_code == 200
    except (httpx.HTTPError, OSError):
        return False
