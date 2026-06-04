"""Sandbox Service - FastAPI application entry point.

Provides:
- POST /execute  : Run Python code in an isolated container
- GET  /health   : Liveness probe
- GET  /ready    : Readiness probe (storage + Docker + runtime image)
- GET  /metrics  : Operational metrics dashboard
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

import structlog
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from common.auth.service_auth import verify_service
from src.config import SandboxSettings, get_settings
from src.execution.manager import ExecutionManager, QueueFullError
from src.health import HealthChecker
from src.models import (
    ExecutionRequest,
    ExecutionResult,
    HealthResponse,
    MetricsResponse,
)
from src.storage import StorageDownloadError

logger = structlog.get_logger(__name__)

# Module-level references set during lifespan
_manager: ExecutionManager | None = None
_health_checker: HealthChecker | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage application startup and shutdown."""
    global _manager, _health_checker

    settings = get_settings()

    # Configure structlog
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer()
            if settings.log_level == "debug"
            else structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            structlog.get_level_from_name(settings.log_level)
        ),
    )

    _manager = ExecutionManager(settings)
    _health_checker = HealthChecker(settings)

    logger.info(
        "sandbox_service_started",
        port=settings.port,
        backend=settings.execution_backend,
        max_concurrent=settings.max_concurrent_executions,
        queue_size=settings.queue_size,
        runtime_image=settings.runtime_image,
    )

    yield

    # Shutdown
    _manager.close()
    _health_checker.close()
    logger.info("sandbox_service_stopped")


app = FastAPI(
    title="Sandbox Service",
    description="Isolated code execution engine for compliance agents",
    version="1.0.0",
    lifespan=lifespan,
)


@app.post("/execute", response_model=ExecutionResult)
async def execute_code(
    request: ExecutionRequest,
    service_id: str = Depends(verify_service),
) -> ExecutionResult:
    """Execute Python code in an isolated ephemeral container.

    The code is pre-validated for blocked imports, files are downloaded
    from storage, a preamble is generated with standard imports and
    DataFrame loading, and the combined code runs in a Docker container
    with no network access and strict resource limits.

    Returns 200 for both successful and failed executions (the service
    operated correctly; user code may have errored). HTTP errors indicate
    service-level failures.
    """
    assert _manager is not None, "Service not initialized"

    settings = get_settings()

    # Validate file count
    if len(request.files) > settings.max_file_count:
        raise HTTPException(
            status_code=400,
            detail=f"Too many files: {len(request.files)} exceeds max of {settings.max_file_count}",
        )

    # Validate timeout
    if request.timeout_sec > settings.max_timeout_sec:
        raise HTTPException(
            status_code=400,
            detail=f"Timeout {request.timeout_sec}s exceeds max of {settings.max_timeout_sec}s",
        )

    # Validate memory
    if request.memory_limit_mb > settings.max_memory_mb:
        raise HTTPException(
            status_code=400,
            detail=f"Memory {request.memory_limit_mb}MB exceeds max of {settings.max_memory_mb}MB",
        )

    try:
        result = await _manager.execute(request)
        return result
    except QueueFullError:
        raise HTTPException(
            status_code=429,
            detail="Service at capacity. All execution slots and queue positions are occupied.",
            headers={"Retry-After": "10"},
        )
    except StorageDownloadError as exc:
        if exc.status_code == 404:
            raise HTTPException(
                status_code=404,
                detail=f"File not found in storage: {exc.storage_key}",
            )
        elif exc.status_code == 413:
            raise HTTPException(
                status_code=413,
                detail=str(exc),
            )
        else:
            raise HTTPException(
                status_code=502,
                detail=f"Storage backend error: {exc}",
            )
    except Exception as exc:
        logger.error("unhandled_execution_error", error=str(exc), exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Internal error during code execution",
        )


@app.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Liveness probe - service process is alive."""
    return HealthResponse(status="ok", service="sandbox-service")


@app.get("/ready")
async def readiness_check() -> JSONResponse:
    """Readiness probe - checks storage, Docker, and runtime image availability."""
    assert _health_checker is not None, "Service not initialized"

    status = await _health_checker.check_ready()

    if status.ready:
        return JSONResponse(
            content={"status": "ready", "checks": status.details},
            status_code=200,
        )
    else:
        return JSONResponse(
            content={"status": "not_ready", "checks": status.details},
            status_code=503,
        )


@app.get("/metrics", response_model=MetricsResponse)
async def metrics(service_id: str = Depends(verify_service)) -> MetricsResponse:
    """Return operational metrics for monitoring dashboards."""
    assert _manager is not None, "Service not initialized"

    return MetricsResponse(
        total_executions=_manager.total_executions,
        success_rate=round(_manager.success_rate, 4),
        avg_duration_ms=round(_manager.avg_duration_ms, 1),
        active_executions=_manager.active_executions,
        queued=_manager.queued_requests,
        timeouts_last_hour=_manager.timeouts_last_hour,
        oom_kills_last_hour=_manager.oom_kills_last_hour,
    )


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=settings.port,
        log_level=settings.log_level,
    )
