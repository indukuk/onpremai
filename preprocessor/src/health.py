"""Health check endpoint for the preprocessor service.

Provides GET /health and GET /ready endpoints following the standard
pattern used by all services in this system.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter

from src.config import PreprocessorSettings

router = APIRouter()

# Module-level mutable state for health reporting
_stats: dict[str, Any] = {
    "files_processed": 0,
    "last_processed_at": None,
    "errors_count": 0,
    "started_at": datetime.now(timezone.utc).isoformat(),
}


def record_processing(success: bool) -> None:
    """Record a file processing event in health stats."""
    _stats["files_processed"] += 1
    _stats["last_processed_at"] = datetime.now(timezone.utc).isoformat()
    if not success:
        _stats["errors_count"] += 1


def get_stats() -> dict[str, Any]:
    """Return current health stats (read-only copy)."""
    return dict(_stats)


@router.get("/health")
async def health(settings: PreprocessorSettings | None = None) -> dict[str, Any]:
    """Health check endpoint.

    Returns service status, configuration summary, and processing stats.
    Used by Docker HEALTHCHECK and load balancers.
    """
    from src.config import get_settings

    cfg = settings or get_settings()
    return {
        "status": "healthy",
        "trigger_mode": cfg.trigger_mode.value,
        "ocr_backend": cfg.ocr_backend.value,
        "pdf_backend": cfg.pdf_backend.value,
        "files_processed": _stats["files_processed"],
        "last_processed_at": _stats["last_processed_at"],
        "errors_count": _stats["errors_count"],
        "started_at": _stats["started_at"],
    }


@router.get("/ready")
async def ready() -> dict[str, str]:
    """Readiness probe.

    Returns 200 when the service is ready to accept work.
    Could be extended to verify storage connectivity.
    """
    return {"status": "ready"}
