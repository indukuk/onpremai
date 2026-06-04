"""Health and readiness endpoints for agent-eval.

/health returns immediately for liveness probes.
/ready gates traffic until the RAG index is loaded.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["health"])

# Module-level flag set by main.py after RAG index loads
_rag_ready: bool = False


def set_rag_ready(ready: bool) -> None:
    """Mark the RAG index as loaded (or unloaded)."""
    global _rag_ready
    _rag_ready = ready


def is_rag_ready() -> bool:
    """Check if the RAG index is loaded."""
    return _rag_ready


@router.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe: always returns healthy if the process is running."""
    return {"status": "healthy"}


@router.get("/ready")
async def ready() -> dict[str, bool]:
    """Readiness probe: true only when RAG index is loaded and service can accept work."""
    return {"ready": _rag_ready}
