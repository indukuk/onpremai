"""Health and readiness endpoints for compliance-assistant."""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter

from src.config import settings

router = APIRouter(tags=["health"])

_startup_time: float = time.time()
_tools_loaded: bool = False


def mark_tools_loaded() -> None:
    """Called once MCP tools/list completes successfully at startup."""
    global _tools_loaded  # noqa: PLW0603
    _tools_loaded = True


@router.get("/health")
async def health() -> dict[str, Any]:
    """Basic liveness check - always responds if process is running."""
    return {
        "status": "healthy",
        "service": settings.service_name,
        "version": settings.chat_version,
        "uptime_sec": round(time.time() - _startup_time, 1),
    }


@router.get("/ready")
async def ready() -> dict[str, Any]:
    """Readiness check - true once tool registry has been loaded.

    The service is ready to accept traffic only after MCP tools/list
    has been called successfully at least once.
    """
    if _tools_loaded:
        return {"status": "ready", "tools_loaded": True}
    return {"status": "not_ready", "tools_loaded": False}
