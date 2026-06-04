"""Preprocessor service entry point.

FastAPI application that provides:
- Health check endpoints (GET /health, GET /ready)
- Webhook endpoint for S3/MinIO notifications (POST /notify)
- Background polling trigger for new file detection

The service starts the appropriate trigger mode based on configuration
and processes files through the extraction pipeline.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator

import structlog
import uvicorn
from fastapi import FastAPI

from src.config import PreprocessorSettings, TriggerMode, get_settings
from src.health import router as health_router
from src.idempotency import IdempotencyTracker
from src.processing.pipeline import ProcessingPipeline
from src.trigger.poller import Poller
from src.trigger.webhook import router as webhook_router, set_pipeline

logger = structlog.get_logger(__name__)

# Module-level references for graceful shutdown
_poller: Poller | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan handler - starts/stops background tasks."""
    global _poller  # noqa: PLW0603

    settings = get_settings()
    tracker = IdempotencyTracker()
    pipeline = ProcessingPipeline(settings=settings, tracker=tracker)

    # Wire pipeline into webhook handler
    set_pipeline(pipeline)

    # Start the appropriate trigger
    if settings.trigger_mode == TriggerMode.POLL:
        _poller = Poller(settings=settings, pipeline=pipeline, tracker=tracker)
        await _poller.start()
        logger.info(
            "preprocessor_started",
            trigger_mode="poll",
            interval_sec=settings.poll_interval_sec,
            watch_prefix=settings.watch_prefix,
            ocr_backend=settings.ocr_backend.value,
            pdf_backend=settings.pdf_backend.value,
        )
    elif settings.trigger_mode == TriggerMode.WEBHOOK:
        logger.info(
            "preprocessor_started",
            trigger_mode="webhook",
            ocr_backend=settings.ocr_backend.value,
            pdf_backend=settings.pdf_backend.value,
        )
    else:
        logger.info(
            "preprocessor_started",
            trigger_mode=settings.trigger_mode.value,
            ocr_backend=settings.ocr_backend.value,
            pdf_backend=settings.pdf_backend.value,
        )

    yield

    # Shutdown
    if _poller is not None:
        await _poller.stop()
    logger.info("preprocessor_stopped")


def create_app(settings: PreprocessorSettings | None = None) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        settings: Optional settings override (for testing).

    Returns:
        Configured FastAPI application instance.
    """
    app = FastAPI(
        title="Preprocessor Service",
        description="File ingestion and metadata extraction for compliance evidence",
        version="1.0.0",
        lifespan=lifespan,
    )

    # Register routers
    app.include_router(health_router, tags=["health"])
    app.include_router(webhook_router, tags=["trigger"])

    return app


# Application instance
app = create_app()


def main() -> None:
    """Run the preprocessor service."""
    settings = get_settings()

    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(
            structlog.get_level_from_name(settings.log_level)
        ),
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer()
            if settings.log_level == "debug"
            else structlog.processors.JSONRenderer(),
        ],
    )

    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=settings.port,
        log_level=settings.log_level,
        access_log=False,
    )


if __name__ == "__main__":
    main()
