"""Evaluation decision lifecycle endpoints (R7e).

Manages the draft → approved lifecycle for evaluation results.
Decisions are separate from evaluation results (which are immutable).
Storage: Redis with key pattern eval_decision:{tenant_id}:{evaluation_id}.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter(prefix="/v1/evaluation-decisions", tags=["evaluation-decisions"])

logger = structlog.get_logger(__name__)


# --- Request Bodies ---


class DecisionCreateBody(BaseModel):
    evaluation_id: str
    tenant_id: str
    control_id: str
    framework: str
    ai_score: float
    ai_status: str


class DecisionGetBody(BaseModel):
    evaluation_id: str
    tenant_id: str


class DecisionOverrideBody(BaseModel):
    evaluation_id: str
    tenant_id: str
    criterion_id: str
    ai_result: str
    user_result: str
    reason: str
    overridden_by: str


class DecisionApproveBody(BaseModel):
    evaluation_id: str
    tenant_id: str
    approved_by: str
    notes: str = ""


class DecisionListBody(BaseModel):
    tenant_id: str
    framework: str | None = None
    status: str | None = None
    limit: int = 50


# --- Helpers ---


def _decision_key(tenant_id: str, evaluation_id: str) -> str:
    return f"eval_decision:{tenant_id}:{evaluation_id}"


def _tenant_index_key(tenant_id: str) -> str:
    return f"eval_decision_index:{tenant_id}"


# --- Endpoints ---


@router.post("/create")
async def create_decision(body: DecisionCreateBody, request: Request) -> dict[str, Any]:
    """Create a decision record when evaluation completes (status: draft)."""
    redis = request.app.state.redis
    key = _decision_key(body.tenant_id, body.evaluation_id)

    decision = {
        "evaluation_id": body.evaluation_id,
        "tenant_id": body.tenant_id,
        "control_id": body.control_id,
        "framework": body.framework,
        "ai_score": body.ai_score,
        "ai_status": body.ai_status,
        "final_score": body.ai_score,
        "final_status": body.ai_status,
        "status": "draft",
        "overrides": [],
        "approved_by": None,
        "approved_at": None,
        "notes": None,
        "created_at": time.time(),
        "updated_at": time.time(),
    }

    await redis.set(key, json.dumps(decision))

    # Add to tenant index for listing
    index_key = _tenant_index_key(body.tenant_id)
    await redis.sadd(index_key, body.evaluation_id)

    logger.info(
        "evaluation_decision_created",
        evaluation_id=body.evaluation_id,
        tenant_id=body.tenant_id,
        control_id=body.control_id,
        framework=body.framework,
    )
    return {"status": "ok", "decision": decision}


@router.post("/get")
async def get_decision(body: DecisionGetBody, request: Request) -> dict[str, Any]:
    """Get decision record for an evaluation."""
    redis = request.app.state.redis
    key = _decision_key(body.tenant_id, body.evaluation_id)

    raw = await redis.get(key)
    if raw is None:
        return {}

    return json.loads(raw)


@router.post("/override")
async def override_criterion(body: DecisionOverrideBody, request: Request) -> dict[str, Any]:
    """Override a criterion result with human judgment."""
    if not body.reason.strip():
        raise HTTPException(status_code=422, detail="Override reason is required")

    redis = request.app.state.redis
    key = _decision_key(body.tenant_id, body.evaluation_id)

    raw = await redis.get(key)
    if raw is None:
        raise HTTPException(status_code=404, detail="Decision not found")

    decision = json.loads(raw)

    override_entry = {
        "id": str(uuid.uuid4()),
        "criterion_id": body.criterion_id,
        "ai_result": body.ai_result,
        "user_result": body.user_result,
        "reason": body.reason,
        "overridden_by": body.overridden_by,
        "overridden_at": time.time(),
    }

    decision["overrides"].append(override_entry)
    decision["updated_at"] = time.time()

    await redis.set(key, json.dumps(decision))

    logger.info(
        "evaluation_criterion_overridden",
        evaluation_id=body.evaluation_id,
        tenant_id=body.tenant_id,
        criterion_id=body.criterion_id,
        ai_result=body.ai_result,
        user_result=body.user_result,
        overridden_by=body.overridden_by,
    )
    return {"status": "ok", "override": override_entry}


@router.post("/approve")
async def approve_decision(body: DecisionApproveBody, request: Request) -> dict[str, Any]:
    """Approve an evaluation decision."""
    redis = request.app.state.redis
    key = _decision_key(body.tenant_id, body.evaluation_id)

    raw = await redis.get(key)
    if raw is None:
        raise HTTPException(status_code=404, detail="Decision not found")

    decision = json.loads(raw)
    decision["status"] = "approved"
    decision["approved_by"] = body.approved_by
    decision["approved_at"] = time.time()
    decision["notes"] = body.notes
    decision["updated_at"] = time.time()

    await redis.set(key, json.dumps(decision))

    logger.info(
        "evaluation_decision_approved",
        evaluation_id=body.evaluation_id,
        tenant_id=body.tenant_id,
        approved_by=body.approved_by,
    )
    return {"status": "ok", "decision": decision}


@router.post("/list")
async def list_decisions(body: DecisionListBody, request: Request) -> dict[str, Any]:
    """List decisions for a tenant, optionally filtered by framework/status."""
    redis = request.app.state.redis
    index_key = _tenant_index_key(body.tenant_id)

    # Get all evaluation IDs for this tenant
    evaluation_ids = await redis.smembers(index_key)
    if not evaluation_ids:
        return {"decisions": []}

    decisions: list[dict[str, Any]] = []

    for eval_id in evaluation_ids:
        if isinstance(eval_id, bytes):
            eval_id = eval_id.decode("utf-8")
        key = _decision_key(body.tenant_id, eval_id)
        raw = await redis.get(key)
        if raw is None:
            continue

        decision = json.loads(raw)

        # Apply filters
        if body.framework and decision.get("framework") != body.framework:
            continue
        if body.status and decision.get("status") != body.status:
            continue

        decisions.append(decision)

        if len(decisions) >= body.limit:
            break

    # Sort by created_at descending (newest first)
    decisions.sort(key=lambda d: d.get("created_at", 0), reverse=True)

    return {"decisions": decisions}
