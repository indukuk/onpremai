"""Load skills from memory-service (with built-in fallbacks).

Skills are versioned configuration stored in memory-service. The loader
fetches them at session start and provides prompt text for active skills.
"""

from __future__ import annotations

from typing import Any

import structlog

from common.clients import MemoryClient

logger = structlog.get_logger(__name__)

# Built-in default skills (used when memory service is unavailable)
DEFAULT_SKILLS: dict[str, dict[str, Any]] = {
    "admin/dashboard": {
        "id": "admin/dashboard",
        "role": "admin",
        "triggers": ["dashboard", "overview", "status", "readiness"],
        "system_prompt": (
            "Show the executive a high-level compliance dashboard.\n"
            "Include: overall readiness %, top risks, team bottlenecks, "
            "days to audit.\nKeep it concise and actionable."
        ),
        "tools_needed": ["evidence.check_coverage", "audit.get_readiness"],
        "playbook_id": None,
    },
    "admin/escalation_review": {
        "id": "admin/escalation_review",
        "role": "admin",
        "triggers": ["escalat", "overdue", "blocked", "stuck"],
        "system_prompt": (
            "Review escalated items and overdue controls.\n"
            "Show who is blocking, how long overdue, and impact on readiness.\n"
            "Offer to send reminders or reassign."
        ),
        "tools_needed": ["escalation.check_overdue", "escalation.send_reminder"],
        "playbook_id": None,
    },
    "cm/program_status": {
        "id": "cm/program_status",
        "role": "compliance_manager",
        "triggers": ["status", "progress", "where are we", "how are we doing"],
        "system_prompt": (
            "Show program status: controls by status, recent completions, "
            "upcoming deadlines, and blockers.\n"
            "Prioritize: overdue > due this week > upcoming."
        ),
        "tools_needed": ["evidence.check_coverage", "escalation.check_overdue"],
        "playbook_id": None,
    },
    "cm/gap_analysis": {
        "id": "cm/gap_analysis",
        "role": "compliance_manager",
        "triggers": ["gap", "missing", "what's needed", "coverage"],
        "system_prompt": (
            "Analyze gaps in evidence coverage and control compliance.\n"
            "Show which controls lack evidence, which evaluations are stale, "
            "and prioritize by audit impact."
        ),
        "tools_needed": ["evidence.check_coverage"],
        "playbook_id": None,
    },
    "cm/escalation": {
        "id": "cm/escalation",
        "role": "compliance_manager",
        "triggers": ["escalat", "remind", "overdue", "follow up"],
        "system_prompt": (
            "Handle overdue evidence and escalation.\n"
            "Show days overdue, assignee, and control impact.\n"
            "Recommend action based on severity."
        ),
        "tools_needed": ["escalation.check_overdue", "escalation.send_reminder"],
        "playbook_id": "playbook/escalation_handling",
    },
    "contributor/my_tasks": {
        "id": "contributor/my_tasks",
        "role": "contributor",
        "triggers": ["my tasks", "what do i need", "to do", "assigned", "my controls"],
        "system_prompt": (
            "Show this user their assigned controls and tasks.\n"
            "Prioritize by urgency. Show one task at a time.\n"
            "For each: what's needed, deadline, example of good evidence."
        ),
        "tools_needed": [],
        "playbook_id": None,
    },
    "contributor/upload_guidance": {
        "id": "contributor/upload_guidance",
        "role": "contributor",
        "triggers": ["upload", "evidence", "how do i", "what do you need", "file"],
        "system_prompt": (
            "The user needs to upload evidence for a control.\n"
            "1. Check which control they're asking about (or show their assigned list)\n"
            "2. Tell them exactly what evidence is needed (from control definition)\n"
            "3. Show an example of good evidence for this control type\n"
            "4. Provide the upload steps\n"
            "5. After upload: offer to run evaluation"
        ),
        "tools_needed": ["evidence.upload_url", "evidence.bind_to_control", "evidence.check_coverage"],
        "playbook_id": "playbook/evidence_collection",
    },
    "auditor/testing_workflow": {
        "id": "auditor/testing_workflow",
        "role": "auditor",
        "triggers": ["test", "audit", "check", "verify", "examine"],
        "system_prompt": (
            "Guide the auditor through testing a control.\n"
            "Show evidence, prior AI assessment, and let them record results.\n"
            "Be objective - present facts, don't advocate."
        ),
        "tools_needed": ["audit.generate_checklist", "evidence.check_coverage", "audit.test_control"],
        "playbook_id": "playbook/audit_testing",
    },
    "auditor/finding_entry": {
        "id": "auditor/finding_entry",
        "role": "auditor",
        "triggers": ["finding", "fail", "issue", "deficiency", "observation"],
        "system_prompt": (
            "Help the auditor document a finding.\n"
            "Collect: control, severity, description, evidence, remediation.\n"
            "Be thorough but efficient."
        ),
        "tools_needed": ["audit.create_finding"],
        "playbook_id": None,
    },
    "viewer/status_report": {
        "id": "viewer/status_report",
        "role": "viewer",
        "triggers": ["status", "readiness", "how", "report", "progress"],
        "system_prompt": (
            "Provide read-only status information.\n"
            "Show readiness %, timeline, control status.\n"
            "Do NOT offer to take actions."
        ),
        "tools_needed": ["evidence.check_coverage", "audit.get_readiness"],
        "playbook_id": None,
    },
    "shared/evidence_summarization": {
        "id": "shared/evidence_summarization",
        "role": "shared",
        "triggers": ["summarize", "what does this show", "explain this evidence", "evidence summary"],
        "system_prompt": (
            "Summarize evidence documents for the user. Focus on:\n"
            "1. What the document proves (which control requirements it addresses)\n"
            "2. Key data points (dates, counts, coverage)\n"
            "3. Gaps or weaknesses the auditor would notice\n"
            "4. Freshness (is this evidence current enough?)"
        ),
        "tools_needed": ["evidence.get_metadata", "evidence.get_content", "preprocessor.summarize"],
        "playbook_id": None,
    },
}


class SkillLoader:
    """Loads skills from memory-service with fallback to built-in defaults."""

    def __init__(self, memory: MemoryClient) -> None:
        self._memory = memory
        self._cache: dict[str, dict[str, Any]] = {}

    async def load_for_role(
        self,
        role: str,
        tenant_id: str,
    ) -> list[dict[str, Any]]:
        """Load all skills applicable to a role.

        Fetches from memory-service first. Falls back to DEFAULT_SKILLS
        if memory is unavailable.

        Returns:
            List of skill configuration dicts.
        """
        # Try memory service
        skills_from_memory = await self._memory.skill_recall(
            tenant_id=tenant_id,
            skill_name=None,  # Get all skills
        )

        if skills_from_memory:
            # Filter by role
            role_skills = [
                s for s in skills_from_memory
                if self._skill_matches_role(s, role)
            ]
            if role_skills:
                for skill in role_skills:
                    skill_id = skill.get("id", skill.get("skill_name", ""))
                    self._cache[skill_id] = skill
                return role_skills

        # Fallback to built-in defaults
        logger.info("skills_using_defaults", role=role)
        from src.skills.matcher import ROLE_SKILL_PREFIXES

        prefixes = ROLE_SKILL_PREFIXES.get(role, ["shared/"])
        role_skills = [
            skill for skill_id, skill in DEFAULT_SKILLS.items()
            if any(skill_id.startswith(p) for p in prefixes)
        ]

        for skill in role_skills:
            self._cache[skill["id"]] = skill

        return role_skills

    async def get_skill_prompt(self, skill_id: str, tenant_id: str) -> str:
        """Get the system_prompt for a specific skill.

        Args:
            skill_id: The skill identifier.
            tenant_id: Tenant context for memory lookup.

        Returns:
            The skill's system_prompt text, or empty string if not found.
        """
        # Check cache first
        if skill_id in self._cache:
            return self._cache[skill_id].get("system_prompt", "")

        # Try memory
        results = await self._memory.skill_recall(
            tenant_id=tenant_id,
            skill_name=skill_id,
        )
        if results:
            skill_data = results[0] if isinstance(results, list) else results
            self._cache[skill_id] = skill_data
            return skill_data.get("system_prompt", skill_data.get("skill_data", {}).get("system_prompt", ""))

        # Check defaults
        if skill_id in DEFAULT_SKILLS:
            return DEFAULT_SKILLS[skill_id].get("system_prompt", "")

        return ""

    async def get_skill_playbook(self, skill_id: str, tenant_id: str) -> str | None:
        """Get the playbook_id associated with a skill.

        Returns:
            The playbook ID string or None if no playbook.
        """
        if skill_id in self._cache:
            return self._cache[skill_id].get("playbook_id")

        if skill_id in DEFAULT_SKILLS:
            return DEFAULT_SKILLS[skill_id].get("playbook_id")

        # Try memory
        results = await self._memory.skill_recall(
            tenant_id=tenant_id,
            skill_name=skill_id,
        )
        if results:
            skill_data = results[0] if isinstance(results, list) else results
            return skill_data.get("playbook_id")

        return None

    def _skill_matches_role(self, skill: dict[str, Any], role: str) -> bool:
        """Check if a skill is applicable to a given role."""
        skill_role = skill.get("role", "")
        skill_id = skill.get("id", skill.get("skill_name", ""))

        # Direct role match
        if isinstance(skill_role, str):
            if skill_role == role or skill_role == "shared":
                return True
        elif isinstance(skill_role, list):
            if role in skill_role or "shared" in skill_role:
                return True

        # Prefix match
        from src.skills.matcher import ROLE_SKILL_PREFIXES
        prefixes = ROLE_SKILL_PREFIXES.get(role, ["shared/"])
        return any(skill_id.startswith(p) for p in prefixes)
