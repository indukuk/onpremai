"""User State Document: structured per-user model replacing scattered vector queries.

The user state doc is a single JSON record per user-tenant pair that provides
deterministic, complete context for the shadow agent. Updated at end of each
reflected session via merge (not overwrite).
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

import structlog
from pydantic import BaseModel, Field

from common.clients import MemoryClient
from src.config import settings

logger = structlog.get_logger(__name__)


class PendingAction(BaseModel):
    action: str
    created: str
    source: str  # "user_deferred" | "agent_committed"
    due_date: str | None = None


class LastSession(BaseModel):
    date: str
    summary: str


class WorkingPatterns(BaseModel):
    avg_session_length: int = 0
    typical_session_time: str = ""
    skills_most_used: list[str] = Field(default_factory=list)


class UserStateDoc(BaseModel):
    user_id: str
    tenant_id: str
    updated_at: str = ""
    agent_name: str = ""
    current_focus: str = ""
    last_session: LastSession | None = None
    pending_actions: list[PendingAction] = Field(default_factory=list)
    preferences: list[str] = Field(default_factory=list)
    working_patterns: WorkingPatterns = Field(default_factory=WorkingPatterns)


class UserStateManager:
    """Manages the user state document lifecycle: load, save, merge."""

    def __init__(self, memory: MemoryClient) -> None:
        self._memory = memory

    async def load(self, user_id: str, tenant_id: str) -> UserStateDoc | None:
        """Load user state doc from memory-service.

        Returns None if no doc exists or memory is unavailable.
        """
        data = await self._memory.user_state_get(user_id, tenant_id)
        if not data:
            return None

        try:
            return UserStateDoc(**data)
        except Exception as exc:
            logger.warning(
                "user_state_parse_failed",
                user_id=user_id,
                error=str(exc),
            )
            return None

    async def save(self, doc: UserStateDoc) -> bool:
        """Persist user state doc to memory-service."""
        doc.updated_at = date.today().isoformat()
        data = doc.model_dump(mode="json")

        serialized = json.dumps(data)
        if len(serialized) > settings.user_state_max_chars:
            doc = self._compact(doc)
            data = doc.model_dump(mode="json")

        return await self._memory.user_state_put(
            user_id=doc.user_id,
            tenant_id=doc.tenant_id,
            data=data,
        )

    async def set_agent_name(
        self, user_id: str, tenant_id: str, name: str
    ) -> bool:
        """Set the agent name, creating the doc if needed."""
        doc = await self.load(user_id, tenant_id)
        if doc is None:
            doc = UserStateDoc(user_id=user_id, tenant_id=tenant_id)

        doc.agent_name = name[:30].strip()
        return await self.save(doc)

    def merge_reflection(
        self,
        doc: UserStateDoc,
        reflection: dict[str, Any],
        active_skill: str | None = None,
        message_count: int = 0,
    ) -> UserStateDoc:
        """Merge reflection output into user state doc.

        Deterministic logic — no LLM involved:
        - Replace last_session with new summary
        - Append pending items with source tags
        - Append preferences (deduplicate, cap at max)
        - Update working patterns
        """
        today = date.today().isoformat()

        accomplished = reflection.get("accomplished", [])
        pending = reflection.get("pending", [])
        commitments = reflection.get("commitments", [])
        new_prefs = reflection.get("preferences", [])

        # Update last_session
        summary_parts = []
        if accomplished:
            summary_parts.append("; ".join(accomplished[:3]))
        if pending:
            summary_parts.append("Deferred: " + "; ".join(pending[:2]))
        doc.last_session = LastSession(
            date=today,
            summary=". ".join(summary_parts) if summary_parts else "Brief session.",
        )

        # Update current_focus from accomplished items
        if accomplished:
            doc.current_focus = accomplished[0]

        # Append pending actions
        for item in pending[:5]:
            doc.pending_actions.append(
                PendingAction(action=item, created=today, source="user_deferred")
            )
        for item in commitments[:3]:
            doc.pending_actions.append(
                PendingAction(action=item, created=today, source="agent_committed")
            )

        # Remove accomplished items from pending
        accomplished_lower = {a.lower() for a in accomplished}
        doc.pending_actions = [
            pa for pa in doc.pending_actions
            if pa.action.lower() not in accomplished_lower
        ]

        # Append preferences (deduplicate, cap)
        existing_lower = {p.lower() for p in doc.preferences}
        for pref in new_prefs[:3]:
            if pref.lower() not in existing_lower:
                doc.preferences.append(pref)
                existing_lower.add(pref.lower())
        doc.preferences = doc.preferences[:settings.max_preferences]

        # Update working patterns
        patterns = doc.working_patterns
        if message_count > 0:
            if patterns.avg_session_length == 0:
                patterns.avg_session_length = message_count
            else:
                patterns.avg_session_length = (
                    patterns.avg_session_length + message_count
                ) // 2
        if active_skill and active_skill not in patterns.skills_most_used:
            patterns.skills_most_used.append(active_skill)
            patterns.skills_most_used = patterns.skills_most_used[-5:]

        doc.updated_at = today
        return self._compact(doc)

    def _compact(self, doc: UserStateDoc) -> UserStateDoc:
        """Evict oldest entries if doc exceeds max size."""
        serialized = json.dumps(doc.model_dump(mode="json"))
        while len(serialized) > settings.user_state_max_chars and doc.pending_actions:
            doc.pending_actions.pop(0)
            serialized = json.dumps(doc.model_dump(mode="json"))
        return doc
