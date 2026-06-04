"""Skill trigger matching using regex and keyword patterns.

Skills are matched against user messages using trigger patterns defined
in the skill configuration. A skill is activated when its trigger pattern
matches the user's message.
"""

from __future__ import annotations

import re
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# Default role-to-skill-prefix mapping
ROLE_SKILL_PREFIXES: dict[str, list[str]] = {
    "admin": ["admin/", "shared/"],
    "compliance_manager": ["cm/", "shared/"],
    "contributor": ["contributor/", "shared/"],
    "auditor": ["auditor/", "shared/"],
    "viewer": ["viewer/", "shared/"],
}


class SkillMatcher:
    """Matches user messages to skills using trigger patterns.

    Skills have trigger lists (keywords and regex patterns). The matcher
    scores each loaded skill against the message and returns the best match.
    """

    def __init__(self) -> None:
        self._skills: list[dict[str, Any]] = []
        self._compiled_patterns: dict[str, list[re.Pattern[str]]] = {}

    def load_skills(self, skills: list[dict[str, Any]]) -> None:
        """Load skills and compile their trigger patterns.

        Args:
            skills: List of skill dicts with 'id', 'triggers', 'role' fields.
        """
        self._skills = skills
        self._compiled_patterns.clear()

        for skill in skills:
            skill_id = skill.get("id", skill.get("skill_name", ""))
            triggers = skill.get("triggers", [])
            patterns: list[re.Pattern[str]] = []

            for trigger in triggers:
                try:
                    # Try as regex first, fall back to word-boundary keyword
                    patterns.append(re.compile(trigger, re.IGNORECASE))
                except re.error:
                    # Treat as a plain keyword with word boundary
                    escaped = re.escape(trigger)
                    patterns.append(re.compile(rf"\b{escaped}\b", re.IGNORECASE))

            self._compiled_patterns[skill_id] = patterns

    def match(
        self,
        message: str,
        role: str,
        active_skill: str | None = None,
    ) -> str | None:
        """Match a user message against loaded skill triggers.

        Returns the skill_id of the best matching skill, or None if no match.
        If an active_skill is already set and still matches, it takes priority.

        Args:
            message: The user's message text.
            role: The user's role (for filtering skills by prefix).
            active_skill: Currently active skill ID (prioritized if still matches).

        Returns:
            The matched skill ID or None.
        """
        if not message.strip():
            return active_skill

        allowed_prefixes = ROLE_SKILL_PREFIXES.get(role, ["shared/"])
        best_skill: str | None = None
        best_score: int = 0

        for skill in self._skills:
            skill_id = skill.get("id", skill.get("skill_name", ""))

            # Filter by role prefix
            if not any(skill_id.startswith(prefix) for prefix in allowed_prefixes):
                continue

            patterns = self._compiled_patterns.get(skill_id, [])
            score = self._score_match(message, patterns)

            if score > best_score:
                best_score = score
                best_skill = skill_id

        # If active skill still has a reasonable match, keep it
        if active_skill and best_skill != active_skill:
            active_patterns = self._compiled_patterns.get(active_skill, [])
            active_score = self._score_match(message, active_patterns)
            # Only switch if new skill scores significantly higher
            if active_score > 0 and best_score < active_score * 2:
                return active_skill

        if best_score > 0:
            logger.debug(
                "skill_matched",
                skill_id=best_skill,
                score=best_score,
                message_excerpt=message[:50],
            )
            return best_skill

        return None

    def _score_match(self, message: str, patterns: list[re.Pattern[str]]) -> int:
        """Score how well a message matches a set of trigger patterns."""
        score = 0
        for pattern in patterns:
            matches = pattern.findall(message)
            score += len(matches)
        return score
