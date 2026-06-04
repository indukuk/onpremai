from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Request
from sqlalchemy import text

from src.db import engine

router = APIRouter(tags=["health"])

_start_time: float = time.time()


@router.get("/health")
async def health() -> dict[str, Any]:
    """Liveness check - returns 200 if process is running."""
    uptime = time.time() - _start_time
    return {"status": "ok", "uptime_seconds": round(uptime, 1)}


@router.get("/ready")
async def ready(request: Request) -> dict[str, Any]:
    """Readiness check - verifies DB and Redis connectivity."""
    results: dict[str, str] = {}

    # Check PostgreSQL
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        results["postgres"] = "connected"
    except Exception:
        results["postgres"] = "disconnected"

    # Check Redis
    try:
        redis = request.app.state.redis
        await redis.ping()
        results["redis"] = "connected"
    except Exception:
        results["redis"] = "disconnected"

    all_connected = all(v == "connected" for v in results.values())
    if not all_connected:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=503, content=results)

    return results
