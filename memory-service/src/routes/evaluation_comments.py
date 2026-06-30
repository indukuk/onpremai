"""Evaluation comments endpoints (R7g).

Supports threaded comments on evaluations, optionally scoped to
specific criteria. Storage: Redis list at eval_comments:{tenant_id}:{evaluation_id}.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

import structlog
from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter(prefix="/v1/evaluation-comments", tags=["evaluation-comments"])

logger = structlog.get_logger(__name__)


# --- Request Bodies ---


class CommentAddBody(BaseModel):
    evaluation_id: str
    tenant_id: str
    author_id: str
    author_role: str
    content: str
    criterion_id: str | None = None
    parent_comment_id: str | None = None


class CommentListBody(BaseModel):
    evaluation_id: str
    tenant_id: str


# --- Helpers ---


def _comments_key(tenant_id: str, evaluation_id: str) -> str:
    return f"eval_comments:{tenant_id}:{evaluation_id}"


# --- Endpoints ---


@router.post("/add")
async def add_comment(body: CommentAddBody, request: Request) -> dict[str, Any]:
    """Add a comment to an evaluation."""
    redis = request.app.state.redis
    key = _comments_key(body.tenant_id, body.evaluation_id)

    comment = {
        "comment_id": str(uuid.uuid4()),
        "evaluation_id": body.evaluation_id,
        "tenant_id": body.tenant_id,
        "criterion_id": body.criterion_id,
        "author_id": body.author_id,
        "author_role": body.author_role,
        "content": body.content,
        "parent_comment_id": body.parent_comment_id,
        "created_at": time.time(),
    }

    await redis.rpush(key, json.dumps(comment))

    logger.info(
        "evaluation_comment_added",
        evaluation_id=body.evaluation_id,
        tenant_id=body.tenant_id,
        author_id=body.author_id,
        criterion_id=body.criterion_id,
        parent_comment_id=body.parent_comment_id,
    )
    return {"status": "ok", "comment": comment}


@router.post("/list")
async def list_comments(body: CommentListBody, request: Request) -> dict[str, Any]:
    """List all comments for an evaluation (threaded)."""
    redis = request.app.state.redis
    key = _comments_key(body.tenant_id, body.evaluation_id)

    raw_comments = await redis.lrange(key, 0, -1)
    comments = [json.loads(raw) for raw in raw_comments]

    logger.debug(
        "evaluation_comments_listed",
        evaluation_id=body.evaluation_id,
        tenant_id=body.tenant_id,
        count=len(comments),
    )
    return {"comments": comments}
