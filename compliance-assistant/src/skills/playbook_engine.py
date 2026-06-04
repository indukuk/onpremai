"""Multi-step playbook engine: step tracking, resume, branching.

Playbooks are step-by-step procedures loaded from memory-service. The engine
tracks current step, provides step prompts to the LLM, handles skip_if
conditions, branching, and looping.
"""

from __future__ import annotations

from typing import Any

import structlog

from common.clients import MemoryClient
from src.models import SessionState

logger = structlog.get_logger(__name__)

# Built-in playbook definitions (fallback when memory unavailable)
DEFAULT_PLAYBOOKS: dict[str, dict[str, Any]] = {
    "playbook/evidence_collection": {
        "id": "playbook/evidence_collection",
        "name": "Evidence Collection for a Control",
        "role": ["contributor", "compliance_manager"],
        "steps": [
            {
                "step": 1,
                "name": "Identify Control",
                "instruction": "Confirm which control needs evidence. If ambiguous, ask.",
                "tool": None,
            },
            {
                "step": 2,
                "name": "Explain Requirements",
                "instruction": (
                    "Show what evidence is needed based on control definition "
                    "and assessment objectives."
                ),
                "tool": "evidence.check_coverage",
                "guidance": (
                    "For access controls (CC6.x): access review logs, user lists, termination records\n"
                    "For change management (CC8.x): change tickets, approval records, deployment logs\n"
                    "For monitoring (CC7.x): alert configurations, incident reports, log samples\n"
                    "Always show: file format expected, time period covered, minimum data points"
                ),
            },
            {
                "step": 3,
                "name": "Show Example",
                "instruction": "Show an example of good evidence for this control type from patterns.",
                "tool": None,
            },
            {
                "step": 4,
                "name": "Assist Upload",
                "instruction": "Provide upload link. Guide through file selection.",
                "tool": "evidence.upload_url",
            },
            {
                "step": 5,
                "name": "Verify & Evaluate",
                "instruction": "Confirm file received. Offer to run evaluation.",
                "tool": "evaluation.start_eval",
                "success": "evaluation complete",
                "on_fail": "If evaluation finds gaps, show them and suggest fixes",
            },
        ],
        "on_stuck": "If user doesn't respond or says 'later', save progress and resume next session.",
        "on_complete": "Confirm evidence is uploaded and evaluated. Show impact on readiness.",
    },
    "playbook/escalation_handling": {
        "id": "playbook/escalation_handling",
        "name": "Handle Overdue Evidence",
        "role": ["compliance_manager"],
        "steps": [
            {
                "step": 1,
                "name": "Assess Situation",
                "instruction": "Show overdue items with days overdue, assignee, and control impact.",
                "tool": "escalation.check_overdue",
            },
            {
                "step": 2,
                "name": "Determine Action",
                "instruction": "Based on days overdue, recommend action.",
                "guidance": (
                    "1-7 days: suggest gentle reminder\n"
                    "7-14 days: suggest firm reminder with deadline\n"
                    "14+ days: suggest escalation to manager\n"
                    "If audit <30 days away AND control critical: escalate immediately"
                ),
                "decision_point": "Ask user: remind, escalate, or reassign?",
            },
            {
                "step": 3,
                "name": "Execute Action",
                "instruction": "Execute the chosen action (remind, escalate, or reassign).",
                "tool": "escalation.send_reminder",
                "confirmation_required": True,
            },
            {
                "step": 4,
                "name": "Record & Schedule Follow-up",
                "instruction": "Update task, set follow-up reminder.",
                "tool": "escalation.set_due_dates",
            },
        ],
        "on_stuck": "Save progress. Note which overdue items were reviewed.",
        "on_complete": "Confirm actions taken. Show updated overdue list.",
    },
    "playbook/audit_testing": {
        "id": "playbook/audit_testing",
        "name": "Test a Control During Audit",
        "role": ["auditor"],
        "steps": [
            {
                "step": 1,
                "name": "Select Control",
                "instruction": "Show untested controls. Let auditor pick or go in order.",
                "tool": "audit.generate_checklist",
            },
            {
                "step": 2,
                "name": "Present Evidence",
                "instruction": "Show all evidence for this control - files, AI evaluation, history.",
                "tool": "evidence.check_coverage",
            },
            {
                "step": 3,
                "name": "Present AI Assessment",
                "instruction": "Show prior AI evaluation result as reference (not as the audit opinion).",
                "guidance": (
                    "Present as: 'AI assessment found: [status] with [confidence]%'\n"
                    "Clarify: 'This is AI analysis, not the audit opinion. You decide.'\n"
                    "Show: gaps found, evidence reviewed, testing procedures used"
                ),
            },
            {
                "step": 4,
                "name": "Record Test Result",
                "instruction": "Ask auditor for their test result and notes.",
                "tool": "audit.test_control",
            },
            {
                "step": 5,
                "name": "Log Findings",
                "instruction": "Help auditor document the finding with severity and remediation.",
                "tool": "audit.create_finding",
                "condition": "result is fail or partial",
            },
            {
                "step": 6,
                "name": "Next Control",
                "instruction": "Show progress (X/Y tested). Offer next control.",
                "loop_to": 1,
            },
        ],
        "on_stuck": "Save which control was being tested and resume there.",
        "on_complete": "Show final audit progress. All controls tested.",
    },
}


class PlaybookEngine:
    """Manages playbook execution: step tracking, prompts, branching, resume."""

    def __init__(self, memory: MemoryClient) -> None:
        self._memory = memory
        self._cache: dict[str, dict[str, Any]] = {}

    async def get_step_prompt(
        self,
        playbook_id: str,
        step: int,
        data: dict[str, Any],
        tenant_id: str,
    ) -> str:
        """Get the prompt text for the current playbook step.

        This is injected into the system prompt so the LLM knows what step
        it's on and what to do.

        Args:
            playbook_id: The playbook identifier.
            step: Current step number (1-indexed).
            data: Accumulated playbook data from prior steps.
            tenant_id: Tenant context.

        Returns:
            Formatted prompt text for the current step.
        """
        playbook = await self._load_playbook(playbook_id, tenant_id)
        if not playbook:
            return ""

        steps = playbook.get("steps", [])
        total_steps = len(steps)

        # Find the current step
        current_step: dict[str, Any] | None = None
        for s in steps:
            if s.get("step") == step:
                current_step = s
                break

        if not current_step:
            return ""

        # Build the step prompt
        lines: list[str] = [
            f"Playbook: {playbook.get('name', playbook_id)}",
            f"Step {step}/{total_steps}: {current_step.get('name', '')}",
            "",
            f"Instruction: {current_step.get('instruction', '')}",
        ]

        if current_step.get("guidance"):
            lines.append(f"\nGuidance:\n{current_step['guidance']}")

        if current_step.get("tool"):
            lines.append(f"\nUse tool: {current_step['tool']}")

        if current_step.get("success"):
            lines.append(f"Success criteria: {current_step['success']}")

        if current_step.get("decision_point"):
            lines.append(f"\nDecision point: {current_step['decision_point']}")

        if current_step.get("condition"):
            lines.append(f"Condition: {current_step['condition']}")

        if current_step.get("skip_if"):
            lines.append(f"Skip if: {current_step['skip_if']}")

        if current_step.get("confirmation_required"):
            lines.append("Note: This action requires user confirmation before executing.")

        if current_step.get("on_fail"):
            lines.append(f"On failure: {current_step['on_fail']}")

        # Add context from prior steps
        if data:
            lines.append("\nContext from prior steps:")
            for key, value in data.items():
                lines.append(f"- {key}: {value}")

        # Add on_stuck guidance
        if playbook.get("on_stuck"):
            lines.append(f"\nIf stuck: {playbook['on_stuck']}")

        return "\n".join(lines)

    async def advance_step(self, session: SessionState) -> None:
        """Advance the playbook to the next step.

        Handles step progression, looping, and completion.
        Updates session state in place.
        """
        if not session.active_playbook:
            return

        playbook = await self._load_playbook(
            session.active_playbook,
            session.tenant_id,
        )
        if not playbook:
            return

        steps = playbook.get("steps", [])
        current_step_data: dict[str, Any] | None = None

        for s in steps:
            if s.get("step") == session.playbook_step:
                current_step_data = s
                break

        if not current_step_data:
            # Step not found - playbook may be complete
            self._complete_playbook(session)
            return

        # Check for loop_to
        if current_step_data.get("loop_to"):
            session.playbook_step = current_step_data["loop_to"]
            return

        # Advance to next step
        next_step = session.playbook_step + 1
        max_step = max(s.get("step", 0) for s in steps) if steps else 0

        if next_step > max_step:
            # Playbook complete
            self._complete_playbook(session)
        else:
            session.playbook_step = next_step

    async def skip_step(self, session: SessionState) -> None:
        """Skip the current step and advance to the next one."""
        await self.advance_step(session)

    def _complete_playbook(self, session: SessionState) -> None:
        """Mark playbook as complete and clear session state."""
        logger.info(
            "playbook_completed",
            playbook_id=session.active_playbook,
            session_id=session.session_id,
        )
        session.active_playbook = None
        session.playbook_step = 0
        session.playbook_data = {}

    async def _load_playbook(
        self,
        playbook_id: str,
        tenant_id: str,
    ) -> dict[str, Any]:
        """Load a playbook definition from cache, memory, or defaults."""
        # Check cache
        if playbook_id in self._cache:
            return self._cache[playbook_id]

        # Try memory service
        results = await self._memory.skill_recall(
            tenant_id=tenant_id,
            skill_name=playbook_id,
        )
        if results:
            playbook_data = results[0] if isinstance(results, list) else results
            # The playbook might be nested in skill_data
            if "steps" not in playbook_data and "skill_data" in playbook_data:
                playbook_data = playbook_data["skill_data"]
            self._cache[playbook_id] = playbook_data
            return playbook_data

        # Fall back to defaults
        if playbook_id in DEFAULT_PLAYBOOKS:
            self._cache[playbook_id] = DEFAULT_PLAYBOOKS[playbook_id]
            return DEFAULT_PLAYBOOKS[playbook_id]

        logger.warning("playbook_not_found", playbook_id=playbook_id)
        return {}
