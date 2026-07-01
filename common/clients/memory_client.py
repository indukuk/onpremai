"""Memory service client with graceful degradation.

All methods wrap calls in try/except and return empty results on ANY failure.
Memory being down reduces quality but never crashes agents.

Usage:
    from common.clients import MemoryClient

    memory = MemoryClient()
    facts = await memory.tenant_recall(tenant_id="t-123", query="SOC2 controls")
    # Returns [] if memory is down -- agent proceeds with reduced context
"""

from __future__ import annotations

import os
from typing import Any

import httpx
import structlog

logger = structlog.get_logger(__name__)


class MemoryClient:
    """Async client for the Memory Service.

    Every method guarantees graceful degradation: on any failure (network,
    timeout, 5xx, invalid response), the method logs a warning and returns
    an empty/neutral value. Agents should always handle empty results.
    """

    def __init__(
        self,
        memory_url: str | None = None,
        timeout: float = 5.0,
        service_id: str | None = None,
        service_key: str | None = None,
    ) -> None:
        self._memory_url = (
            memory_url or os.environ.get("MEMORY_URL", "http://memory-service:5000")
        ).rstrip("/")
        self._timeout = timeout
        sid = service_id or os.environ.get("SERVICE_ID", "")
        skey = service_key or os.environ.get("SERVICE_KEY", "")
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if sid and skey:
            headers["X-Service-Id"] = sid
            headers["X-Service-Key"] = skey
        self._http = httpx.AsyncClient(
            base_url=self._memory_url,
            timeout=httpx.Timeout(timeout, connect=3.0),
            headers=headers,
        )

    # --- Session Memory ---

    async def session_store(
        self,
        session_id: str,
        messages: list[dict],
        metadata: dict | None = None,
    ) -> bool:
        """Store session messages. Returns True on success, False on failure."""
        payload: dict[str, Any] = {
            "session_id": session_id,
            "messages": messages,
        }
        if metadata is not None:
            payload["metadata"] = metadata
        return await self._post("/v1/session/store", payload)

    async def session_recall(
        self,
        session_id: str,
        limit: int = 50,
    ) -> list[dict]:
        """Recall session messages. Returns empty list on failure."""
        payload = {"session_id": session_id, "limit": limit}
        result = await self._post_json("/v1/session/recall", payload)
        if isinstance(result, list):
            return result
        return result.get("messages", []) if isinstance(result, dict) else []

    # --- User Memory ---

    async def user_store(
        self,
        user_id: str,
        fact: str,
        category: str = "general",
        metadata: dict | None = None,
    ) -> bool:
        """Store a user-level fact. Returns True on success."""
        payload: dict[str, Any] = {
            "user_id": user_id,
            "fact": fact,
            "category": category,
        }
        if metadata is not None:
            payload["metadata"] = metadata
        return await self._post("/v1/user/store", payload)

    async def user_recall(
        self,
        user_id: str,
        query: str,
        top_k: int = 5,
        category: str | None = None,
    ) -> list[dict]:
        """Recall user-level facts by semantic similarity. Returns [] on failure."""
        payload: dict[str, Any] = {
            "user_id": user_id,
            "query": query,
            "top_k": top_k,
        }
        if category is not None:
            payload["category"] = category
        result = await self._post_json("/v1/user/recall", payload)
        if isinstance(result, list):
            return result
        return result.get("facts", []) if isinstance(result, dict) else []

    # --- Tenant Memory ---

    async def tenant_store(
        self,
        tenant_id: str,
        fact: str,
        category: str = "general",
        metadata: dict | None = None,
    ) -> bool:
        """Store a tenant-level fact. Returns True on success."""
        payload: dict[str, Any] = {
            "tenant_id": tenant_id,
            "fact": fact,
            "category": category,
        }
        if metadata is not None:
            payload["metadata"] = metadata
        return await self._post("/v1/tenant/store", payload)

    async def tenant_recall(
        self,
        tenant_id: str,
        query: str,
        top_k: int = 5,
        category: str | None = None,
    ) -> list[dict]:
        """Recall tenant-level facts. Returns [] on failure."""
        payload: dict[str, Any] = {
            "tenant_id": tenant_id,
            "query": query,
            "top_k": top_k,
        }
        if category is not None:
            payload["category"] = category
        result = await self._post_json("/v1/tenant/recall", payload)
        if isinstance(result, list):
            return result
        return result.get("facts", []) if isinstance(result, dict) else []

    # --- Task Memory ---

    async def task_store(
        self,
        task_id: str,
        tenant_id: str,
        data: dict,
        metadata: dict | None = None,
    ) -> bool:
        """Store task-level state. Returns True on success."""
        payload: dict[str, Any] = {
            "task_id": task_id,
            "tenant_id": tenant_id,
            "data": data,
        }
        if metadata is not None:
            payload["metadata"] = metadata
        return await self._post("/v1/task/store", payload)

    async def task_recall(
        self,
        task_id: str,
        tenant_id: str,
    ) -> dict:
        """Recall task state. Returns empty dict on failure."""
        payload = {"task_id": task_id, "tenant_id": tenant_id}
        result = await self._post_json("/v1/task/recall", payload)
        return result if isinstance(result, dict) else {}

    # --- Eval Memory ---

    async def eval_store(
        self,
        tenant_id: str,
        framework: str,
        control_id: str,
        result: dict,
        metadata: dict | None = None,
    ) -> bool:
        """Store an evaluation result. Returns True on success."""
        payload: dict[str, Any] = {
            "tenant_id": tenant_id,
            "framework": framework,
            "control_id": control_id,
            "result": result,
        }
        if metadata is not None:
            payload["metadata"] = metadata
        return await self._post("/v1/eval/store", payload)

    async def eval_recall(
        self,
        tenant_id: str,
        framework: str,
        control_id: str | None = None,
        limit: int = 10,
    ) -> list[dict]:
        """Recall evaluation results. Returns [] on failure."""
        payload: dict[str, Any] = {
            "tenant_id": tenant_id,
            "framework": framework,
            "limit": limit,
        }
        if control_id is not None:
            payload["control_id"] = control_id
        result = await self._post_json("/v1/eval/recall", payload)
        if isinstance(result, list):
            return result
        return result.get("results", []) if isinstance(result, dict) else []

    # --- Pattern Memory ---

    async def pattern_store(
        self,
        tenant_id: str,
        pattern_type: str,
        pattern: dict,
        metadata: dict | None = None,
    ) -> bool:
        """Store a detected pattern. Returns True on success."""
        payload: dict[str, Any] = {
            "tenant_id": tenant_id,
            "pattern_type": pattern_type,
            "pattern": pattern,
        }
        if metadata is not None:
            payload["metadata"] = metadata
        return await self._post("/v1/pattern/store", payload)

    async def pattern_recall(
        self,
        tenant_id: str,
        pattern_type: str | None = None,
        limit: int = 10,
    ) -> list[dict]:
        """Recall patterns. Returns [] on failure."""
        payload: dict[str, Any] = {
            "tenant_id": tenant_id,
            "limit": limit,
        }
        if pattern_type is not None:
            payload["pattern_type"] = pattern_type
        result = await self._post_json("/v1/pattern/recall", payload)
        if isinstance(result, list):
            return result
        return result.get("patterns", []) if isinstance(result, dict) else []

    # --- Skill Memory ---

    async def skill_store(
        self,
        tenant_id: str,
        skill_name: str,
        skill_data: dict,
        metadata: dict | None = None,
    ) -> bool:
        """Store skill configuration/state. Returns True on success."""
        payload: dict[str, Any] = {
            "tenant_id": tenant_id,
            "skill_name": skill_name,
            "skill_data": skill_data,
        }
        if metadata is not None:
            payload["metadata"] = metadata
        return await self._post("/v1/skill/store", payload)

    async def skill_recall(
        self,
        tenant_id: str,
        skill_name: str | None = None,
    ) -> list[dict]:
        """Recall skill data. Returns [] on failure."""
        payload: dict[str, Any] = {"tenant_id": tenant_id}
        if skill_name is not None:
            payload["skill_name"] = skill_name
        result = await self._post_json("/v1/skill/recall", payload)
        if isinstance(result, list):
            return result
        return result.get("skills", []) if isinstance(result, dict) else []

    # --- Interaction Memory ---

    async def interaction_store(
        self,
        user_id: str,
        tenant_id: str,
        interaction_type: str,
        data: dict,
        metadata: dict | None = None,
    ) -> bool:
        """Store a user interaction record. Returns True on success."""
        payload: dict[str, Any] = {
            "user_id": user_id,
            "tenant_id": tenant_id,
            "interaction_type": interaction_type,
            "data": data,
        }
        if metadata is not None:
            payload["metadata"] = metadata
        return await self._post("/v1/interaction/store", payload)

    async def interaction_recall(
        self,
        user_id: str,
        tenant_id: str,
        interaction_type: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """Recall user interactions. Returns [] on failure."""
        payload: dict[str, Any] = {
            "user_id": user_id,
            "tenant_id": tenant_id,
            "limit": limit,
        }
        if interaction_type is not None:
            payload["interaction_type"] = interaction_type
        result = await self._post_json("/v1/interaction/recall", payload)
        if isinstance(result, list):
            return result
        return result.get("interactions", []) if isinstance(result, dict) else []

    # --- User State Document ---

    async def user_state_get(self, user_id: str, tenant_id: str) -> dict:
        """Read user state document. Returns empty dict if not found or on failure."""
        payload = {"user_id": user_id, "tenant_id": tenant_id}
        result = await self._post_json("/v1/user-state/get", payload)
        return result if isinstance(result, dict) else {}

    async def user_state_put(self, user_id: str, tenant_id: str, data: dict) -> bool:
        """Write user state document. Returns True on success."""
        payload = {"user_id": user_id, "tenant_id": tenant_id, "data": data}
        return await self._post("/v1/user-state/put", payload)

    # --- Event Queue ---

    async def event_queue_push(
        self,
        user_id: str,
        tenant_id: str,
        event_type: str,
        summary: str,
        priority: str = "medium",
        source_service: str = "",
        metadata: dict | None = None,
    ) -> bool:
        """Push an event to a user's queue. Returns True on success."""
        payload: dict[str, Any] = {
            "user_id": user_id,
            "tenant_id": tenant_id,
            "event_type": event_type,
            "summary": summary,
            "priority": priority,
            "source_service": source_service,
        }
        if metadata is not None:
            payload["metadata"] = metadata
        return await self._post("/v1/event/push", payload)

    async def event_queue_drain(self, user_id: str, tenant_id: str) -> list[dict]:
        """Read and clear all events for a user. Returns [] on failure."""
        payload = {"user_id": user_id, "tenant_id": tenant_id}
        result = await self._post_json("/v1/event/drain", payload)
        if isinstance(result, list):
            return result
        return result.get("events", []) if isinstance(result, dict) else []

    # --- Evaluation Decisions (R7e) ---

    async def eval_decision_create(
        self,
        evaluation_id: str,
        tenant_id: str,
        control_id: str,
        framework: str,
        ai_score: float,
        ai_status: str,
    ) -> bool:
        """Create an evaluation decision record (draft status). Returns True on success."""
        payload = {
            "evaluation_id": evaluation_id,
            "tenant_id": tenant_id,
            "control_id": control_id,
            "framework": framework,
            "ai_score": ai_score,
            "ai_status": ai_status,
        }
        return await self._post("/v1/evaluation-decisions/create", payload)

    async def eval_decision_get(
        self,
        evaluation_id: str,
        tenant_id: str,
    ) -> dict:
        """Get evaluation decision record. Returns empty dict on failure."""
        payload = {"evaluation_id": evaluation_id, "tenant_id": tenant_id}
        result = await self._post_json("/v1/evaluation-decisions/get", payload)
        return result if isinstance(result, dict) else {}

    async def eval_decision_override(
        self,
        evaluation_id: str,
        tenant_id: str,
        criterion_id: str,
        ai_result: str,
        user_result: str,
        reason: str,
        overridden_by: str,
    ) -> bool:
        """Override a criterion in an evaluation decision. Returns True on success."""
        payload = {
            "evaluation_id": evaluation_id,
            "tenant_id": tenant_id,
            "criterion_id": criterion_id,
            "ai_result": ai_result,
            "user_result": user_result,
            "reason": reason,
            "overridden_by": overridden_by,
        }
        return await self._post("/v1/evaluation-decisions/override", payload)

    async def eval_decision_approve(
        self,
        evaluation_id: str,
        tenant_id: str,
        approved_by: str,
        notes: str = "",
    ) -> bool:
        """Approve an evaluation decision. Returns True on success."""
        payload = {
            "evaluation_id": evaluation_id,
            "tenant_id": tenant_id,
            "approved_by": approved_by,
            "notes": notes,
        }
        return await self._post("/v1/evaluation-decisions/approve", payload)

    # --- Evaluation Comments (R7g) ---

    async def eval_comments_add(
        self,
        evaluation_id: str,
        tenant_id: str,
        author_id: str,
        author_role: str,
        content: str,
        criterion_id: str | None = None,
        parent_comment_id: str | None = None,
    ) -> bool:
        """Add a comment to an evaluation. Returns True on success."""
        payload: dict[str, Any] = {
            "evaluation_id": evaluation_id,
            "tenant_id": tenant_id,
            "author_id": author_id,
            "author_role": author_role,
            "content": content,
        }
        if criterion_id is not None:
            payload["criterion_id"] = criterion_id
        if parent_comment_id is not None:
            payload["parent_comment_id"] = parent_comment_id
        return await self._post("/v1/evaluation-comments/add", payload)

    async def eval_comments_list(
        self,
        evaluation_id: str,
        tenant_id: str,
    ) -> list[dict]:
        """List comments for an evaluation. Returns [] on failure."""
        payload = {"evaluation_id": evaluation_id, "tenant_id": tenant_id}
        result = await self._post_json("/v1/evaluation-comments/list", payload)
        if isinstance(result, list):
            return result
        return result.get("comments", []) if isinstance(result, dict) else []

    # --- Internal Helpers ---

    async def _post(self, path: str, payload: dict) -> bool:
        """POST and return True/False success indicator."""
        try:
            response = await self._http.post(path, json=payload)
            if response.status_code >= 400:
                logger.warning(
                    "memory_request_failed",
                    path=path,
                    status=response.status_code,
                )
                return False
            return True
        except Exception as exc:
            logger.warning(
                "memory_request_error",
                path=path,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return False

    async def _post_json(self, path: str, payload: dict) -> Any:
        """POST and return parsed JSON response, or empty dict/list on failure."""
        try:
            response = await self._http.post(path, json=payload)
            if response.status_code >= 400:
                logger.warning(
                    "memory_recall_failed",
                    path=path,
                    status=response.status_code,
                )
                return {}
            return response.json()
        except Exception as exc:
            logger.warning(
                "memory_recall_error",
                path=path,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return {}

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._http.aclose()
