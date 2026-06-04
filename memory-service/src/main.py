from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator
from typing import Any

import redis.asyncio as aioredis
import structlog
import uvicorn
from fastapi import APIRouter, Depends, FastAPI

from common.auth.service_auth import verify_service
from src.config import settings
from src.db import dispose_engine, engine
from src.health import router as health_router
from src.routes import register_routes

logger = structlog.get_logger(__name__)


async def _run_migrations() -> None:
    """Run Alembic migrations on startup."""
    from alembic import command
    from alembic.config import Config

    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", settings.database_url)

    # Run migrations in a thread to avoid blocking the event loop
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, command.upgrade, alembic_cfg, "head")
    logger.info("migrations_applied")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: startup and shutdown logic."""
    # Startup
    logger.info("memory_service_starting", port=settings.PORT)

    # Run database migrations
    try:
        await _run_migrations()
    except Exception as exc:
        logger.error("migration_failed", error=str(exc))
        raise

    # Initialize Redis connection
    app.state.redis = aioredis.from_url(
        settings.REDIS_URL,
        decode_responses=True,
    )

    logger.info("memory_service_ready")
    yield

    # Shutdown
    logger.info("memory_service_shutting_down")
    await app.state.redis.close()
    await dispose_engine()
    logger.info("memory_service_stopped")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Memory Service",
        description="Shared memory layer for all compliance agents",
        version="1.0.0",
        lifespan=lifespan,
    )

    # Health endpoints (no prefix)
    app.include_router(health_router)

    # All other routes (S2S auth required)
    api_router = APIRouter(dependencies=[Depends(verify_service)])
    register_routes(api_router)
    app.include_router(api_router)

    return app


app = create_app()


if __name__ == "__main__":
    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=settings.PORT,
        log_level=settings.LOG_LEVEL,
    )
