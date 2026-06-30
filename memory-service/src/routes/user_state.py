from __future__ import annotations

import json
from typing import Any

import structlog
from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter(prefix="/v1/user-state", tags=["user-state"])

logger = structlog.get_logger(__name__)


class UserStateGetBody(BaseModel):
    user_id: str
    tenant_id: str


class UserStatePutBody(BaseModel):
    user_id: str
    tenant_id: str
    data: dict[str, Any]


def _redis_key(tenant_id: str, user_id: str) -> str:
    return f"user_state:{tenant_id}:{user_id}"


@router.post("/get")
async def get_user_state(body: UserStateGetBody, request: Request) -> dict[str, Any]:
    """Retrieve user state document from Redis."""
    redis = request.app.state.redis
    key = _redis_key(body.tenant_id, body.user_id)
    raw = await redis.get(key)

    if raw is None:
        logger.debug("user_state_not_found", user_id=body.user_id, tenant_id=body.tenant_id)
        return {}

    logger.debug("user_state_retrieved", user_id=body.user_id, tenant_id=body.tenant_id)
    return json.loads(raw)


@router.post("/put")
async def put_user_state(body: UserStatePutBody, request: Request) -> dict[str, str]:
    """Upsert (create or replace) user state document in Redis."""
    redis = request.app.state.redis
    key = _redis_key(body.tenant_id, body.user_id)
    payload = json.dumps(body.data)

    await redis.set(key, payload)
    logger.info("user_state_stored", user_id=body.user_id, tenant_id=body.tenant_id)
    return {"status": "ok"}
