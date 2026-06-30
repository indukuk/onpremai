"""End-of-session reflection: distill conversations into structured summaries.

After a session reaches reflection criteria (message_count >= 6 or goodbye
signal), a cheap LLM pass extracts: accomplished, pending, commitments,
preferences. These are stored in memory and merged into the user state doc.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import structlog

from common.clients import LLMClient, MemoryClient
from common.errors import LLMCreditExhaustedError, LLMUnavailableError
from src.config import settings
from src.models import SessionState

logger = structlog.get_logger(__name__)

GOODBYE_SIGNALS = frozenset({
    "bye", "goodbye", "thanks", "done", "that's all",
    "talk later", "see you", "gotta go", "later",
    "thank you", "thx", "cheers",
})

REFLECTION_PROMPT = """Review this conversation between a compliance AI agent and a user.
Extract the following as concise bullet points (max 3 per category):

1. Accomplished: What was completed this session?
2. Pending: What was discussed but not finished or deferred?
3. Commitments: What did the agent promise to do or follow up on?
4. Preferences: Any observed user preferences about communication or work style?

Conversation:
{conversation}

Respond in JSON only:
{{"accomplished": ["..."], "pending": ["..."], "commitments": ["..."], "preferences": ["..."]}}"""


def should_reflect(session: SessionState, message: str = "") -> bool:
    """Determine if a session warrants reflection."""
    if session.message_count < settings.reflection_min_messages:
        return False

    if message:
        normalized = message.lower().strip().rstrip("!.,")
        if normalized in GOODBYE_SIGNALS:
            return True

    return session.message_count >= settings.reflection_min_messages


class SessionReflector:
    """Runs end-of-session reflection and stores results."""

    def __init__(self, llm: LLMClient, memory: MemoryClient) -> None:
        self._llm = llm
        self._memory = memory

    async def reflect(
        self,
        session: SessionState,
        user_id: str,
        tenant_id: str,
    ) -> dict[str, Any] | None:
        """Run reflection on a session. Returns parsed reflection or None."""
        conversation_text = self._format_conversation(session.conversation_history)
        if not conversation_text:
            return None

        prompt = REFLECTION_PROMPT.format(conversation=conversation_text)

        try:
            response = await self._llm.complete(
                messages=[{"role": "user", "content": prompt}],
                task="session_reflection",
                tenant_id=tenant_id,
                trace_id=str(uuid.uuid4()),
                temperature=0.0,
                max_tokens=500,
            )
        except (LLMCreditExhaustedError, LLMUnavailableError):
            logger.warning("reflection_skipped_llm_unavailable", session_id=session.session_id)
            return None

        reflection = self._parse_response(response.content)
        if not reflection:
            return None

        await self._store(reflection, session.session_id, user_id, tenant_id)

        logger.info(
            "session_reflected",
            session_id=session.session_id,
            accomplished=len(reflection.get("accomplished", [])),
            pending=len(reflection.get("pending", [])),
            commitments=len(reflection.get("commitments", [])),
        )

        return reflection

    async def _store(
        self,
        reflection: dict[str, Any],
        session_id: str,
        user_id: str,
        tenant_id: str,
    ) -> None:
        """Store reflection components in memory."""
        summary_parts = []
        if reflection.get("accomplished"):
            summary_parts.append("Done: " + "; ".join(reflection["accomplished"][:3]))
        if reflection.get("pending"):
            summary_parts.append("Pending: " + "; ".join(reflection["pending"][:3]))
        if reflection.get("commitments"):
            summary_parts.append("Committed: " + "; ".join(reflection["commitments"][:2]))

        await self._memory.interaction_store(
            user_id=user_id,
            tenant_id=tenant_id,
            interaction_type="session_reflection",
            data={
                "session_id": session_id,
                "summary": " | ".join(summary_parts),
                **reflection,
            },
        )

        for pref in reflection.get("preferences", [])[:3]:
            await self._memory.user_store(
                user_id=user_id,
                fact=pref,
                category="preference",
            )

    def _format_conversation(self, history: list[dict[str, Any]]) -> str:
        """Format conversation for reflection prompt."""
        lines: list[str] = []
        max_msgs = settings.reflection_max_history

        for msg in history[-max_msgs:]:
            role = msg.get("role", "")
            content = msg.get("content", "")

            if role == "system":
                continue
            if role == "tool":
                content = content[:200] + "..." if len(content) > 200 else content
                lines.append(f"[tool result]: {content}")
            elif role == "user":
                lines.append(f"User: {content}")
            elif role == "assistant":
                if content:
                    lines.append(f"Agent: {content[:500]}")
                tool_calls = msg.get("tool_calls", [])
                if tool_calls:
                    names = [
                        tc.get("name", tc.get("function", {}).get("name", "?"))
                        for tc in tool_calls
                    ]
                    lines.append(f"Agent used tools: {', '.join(names)}")

        return "\n".join(lines)

    def _parse_response(self, content: str) -> dict[str, Any] | None:
        """Parse LLM reflection response."""
        content = content.strip()
        if content.startswith("```"):
            lines = content.split("\n")
            json_lines = [line for line in lines if not line.startswith("```")]
            content = "\n".join(json_lines)

        try:
            data = json.loads(content)
            return {
                "accomplished": data.get("accomplished", [])[:3],
                "pending": data.get("pending", [])[:3],
                "commitments": data.get("commitments", [])[:3],
                "preferences": data.get("preferences", [])[:3],
            }
        except (json.JSONDecodeError, TypeError):
            logger.warning("reflection_parse_failed", content_preview=content[:100])
            return None
