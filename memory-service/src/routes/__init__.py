from __future__ import annotations

from fastapi import APIRouter

from src.routes.session import router as session_router
from src.routes.tenant import router as tenant_router
from src.routes.user import router as user_router
from src.routes.tasks import router as tasks_router
from src.routes.eval import router as eval_router
from src.routes.patterns import router as patterns_router
from src.routes.skills import router as skills_router
from src.routes.interactions import router as interactions_router
from src.routes.audit import router as audit_router
from src.routes.registry import router as registry_router
from src.routes.jobs import router as jobs_router


def register_routes(app_router: APIRouter) -> None:
    """Register all route modules on the main application router."""
    app_router.include_router(session_router)
    app_router.include_router(tenant_router)
    app_router.include_router(user_router)
    app_router.include_router(tasks_router)
    app_router.include_router(eval_router)
    app_router.include_router(patterns_router)
    app_router.include_router(skills_router)
    app_router.include_router(interactions_router)
    app_router.include_router(audit_router)
    app_router.include_router(registry_router)
    app_router.include_router(jobs_router)
