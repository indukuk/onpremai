"""Session manager backed by Redis via memory-service.

Sessions store conversation history, active skill/playbook state, and
pending confirmations. TTL is enforced by the memory service.
"""

from __future__ import annotations

from typing import Any

import structlog

from common.clients import MemoryClient
from src.config import settings
from src.models import PendingConfirmation, SessionState

logger = structlog.get_logger(__name__)


class SessionManager:
    """Manages session lifecycle via memory-service session endpoints.

    Session data is stored as JSON in memory-service which uses Redis
    for hot session state. If memory is unavailable, creates ephemeral
    in-memory session (reduced quality, not crash).
    """

    def __init__(self, memory: MemoryClient) -> None:
        self._memory = memory
        self._fallback_sessions: dict[str, SessionState] = {}

    async def get_or_create(
        self,
        session_id: str,
        tenant_id: str,
        user_id: str,
        role: str,
    ) -> SessionState:
        """Load existing session or create a new one.

        If memory-service is down, creates a local in-memory session.
        """
        messages = await self._memory.session_recall(session_id, limit=1)
        if messages:
            # Existing session - try to parse metadata
            for msg in messages:
                if msg.get("role") == "system" and msg.get("metadata"):
                    return self._parse_state(msg["metadata"], session_id)

        # Check fallback cache
        if session_id in self._fallback_sessions:
            return self._fallback_sessions[session_id]

        # New session
        state = SessionState(
            session_id=session_id,
            tenant_id=tenant_id,
            user_id=user_id,
            role=role,
        )
        return state

    async def save(self, state: SessionState) -> bool:
        """Persist session state to memory-service.

        Returns True on success, False if memory is unavailable (state
        is cached locally as fallback).
        """
        metadata = state.model_dump(exclude={"conversation_history"})
        messages_to_store = [
            {"role": "system", "metadata": metadata},
            *state.conversation_history[-50:],  # Keep last 50 messages
        ]

        success = await self._memory.session_store(
            session_id=state.session_id,
            messages=messages_to_store,
            metadata={"ttl_hours": settings.session_ttl_hours},
        )

        if not success:
            logger.warning(
                "session_save_fallback",
                session_id=state.session_id,
            )
            self._fallback_sessions[state.session_id] = state

        return success

    async def set_pending_confirmation(
        self,
        state: SessionState,
        confirmation: PendingConfirmation,
    ) -> None:
        """Store a pending confirmation in session state."""
        state.pending_confirmation = confirmation
        await self.save(state)

    async def clear_pending_confirmation(self, state: SessionState) -> None:
        """Clear the pending confirmation from session state."""
        state.pending_confirmation = None
        await self.save(state)

    def _parse_state(self, metadata: dict[str, Any], session_id: str) -> SessionState:
        """Parse session state from stored metadata dict."""
        try:
            metadata["session_id"] = session_id
            # Re-parse pending_confirmation if it's a dict
            if "pending_confirmation" in metadata and isinstance(
                metadata["pending_confirmation"], dict
            ):
                metadata["pending_confirmation"] = PendingConfirmation(
                    **metadata["pending_confirmation"]
                )
            return SessionState(**metadata)
        except Exception as exc:
            logger.warning(
                "session_parse_failed",
                session_id=session_id,
                error=str(exc),
            )
            return SessionState(
                session_id=session_id,
                tenant_id=metadata.get("tenant_id", ""),
                user_id=metadata.get("user_id", ""),
                role=metadata.get("role", "viewer"),
            )
