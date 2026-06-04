"""Unit tests for persona selection.

Covers:
- Correct persona selected for each of the 5 roles
- Unknown role falls back to REPORTER (most restrictive)
- Persona attributes are correctly populated
- Persona data_scope and skill_prefixes are role-appropriate
"""

from __future__ import annotations

import pytest

from src.agent.personas import (
    AUDIT_ASSISTANT,
    EXECUTIVE_ADVISOR,
    PERSONA_MAP,
    PROGRAM_MANAGER,
    REPORTER,
    TASK_COACH,
    Persona,
    select_persona,
)


# ---------------------------------------------------------------------------
# Test: All 5 roles mapped correctly
# ---------------------------------------------------------------------------


class TestPersonaSelection:
    """Tests for select_persona function and PERSONA_MAP."""

    def test_admin_returns_executive_advisor(self) -> None:
        """Admin role selects Executive Advisor persona."""
        persona = select_persona("admin")
        assert persona is EXECUTIVE_ADVISOR
        assert persona.role == "admin"
        assert persona.agent_name == "Executive Advisor"

    def test_compliance_manager_returns_program_manager(self) -> None:
        """Compliance manager role selects Program Manager persona."""
        persona = select_persona("compliance_manager")
        assert persona is PROGRAM_MANAGER
        assert persona.role == "compliance_manager"
        assert persona.agent_name == "Program Manager"

    def test_contributor_returns_task_coach(self) -> None:
        """Contributor role selects Task Coach persona."""
        persona = select_persona("contributor")
        assert persona is TASK_COACH
        assert persona.role == "contributor"
        assert persona.agent_name == "Task Coach"

    def test_auditor_returns_audit_assistant(self) -> None:
        """Auditor role selects Audit Assistant persona."""
        persona = select_persona("auditor")
        assert persona is AUDIT_ASSISTANT
        assert persona.role == "auditor"
        assert persona.agent_name == "Audit Assistant"

    def test_viewer_returns_reporter(self) -> None:
        """Viewer role selects Reporter persona."""
        persona = select_persona("viewer")
        assert persona is REPORTER
        assert persona.role == "viewer"
        assert persona.agent_name == "Reporter"

    def test_unknown_role_fallback_to_reporter(self) -> None:
        """Unknown role falls back to Reporter (most restrictive)."""
        persona = select_persona("unknown_role")
        assert persona is REPORTER

    def test_empty_role_fallback_to_reporter(self) -> None:
        """Empty string role falls back to Reporter."""
        persona = select_persona("")
        assert persona is REPORTER

    def test_none_like_role_fallback(self) -> None:
        """Arbitrary junk role falls back to Reporter."""
        persona = select_persona("superuser")
        assert persona is REPORTER


# ---------------------------------------------------------------------------
# Test: Persona attributes
# ---------------------------------------------------------------------------


class TestPersonaAttributes:
    """Tests for persona attribute correctness."""

    def test_all_personas_have_system_template(self) -> None:
        """Every persona has a non-empty system_template."""
        for role, persona in PERSONA_MAP.items():
            assert persona.system_template, f"{role} persona has empty system_template"

    def test_all_personas_have_behavior_rules(self) -> None:
        """Every persona has at least one behavior rule."""
        for role, persona in PERSONA_MAP.items():
            assert len(persona.behavior_rules) > 0, f"{role} has no behavior_rules"

    def test_all_personas_have_data_scope(self) -> None:
        """Every persona has at least one data_scope entry."""
        for role, persona in PERSONA_MAP.items():
            assert len(persona.data_scope) > 0, f"{role} has no data_scope"

    def test_all_personas_have_skill_prefixes(self) -> None:
        """Every persona has skill_prefixes defining allowed skills."""
        for role, persona in PERSONA_MAP.items():
            assert len(persona.skill_prefixes) > 0, f"{role} has no skill_prefixes"

    def test_executive_has_full_data_access(self) -> None:
        """Admin persona has broadest data scope including escalation."""
        scope = EXECUTIVE_ADVISOR.data_scope
        assert "overall_readiness" in scope
        assert "all_controls" in scope
        assert "full_escalation" in scope

    def test_contributor_has_limited_scope(self) -> None:
        """Contributor persona only sees own controls/tasks."""
        scope = TASK_COACH.data_scope
        assert "own_controls" in scope
        assert "own_tasks" in scope
        # Should NOT have all_controls
        assert "all_controls" not in scope

    def test_viewer_has_minimal_scope(self) -> None:
        """Viewer has read-only, minimal data scope."""
        scope = REPORTER.data_scope
        assert "overall_readiness" in scope
        assert "audit_timeline" in scope
        # Should not have write-capable scopes
        assert "all_tasks" not in scope
        assert "full_escalation" not in scope

    def test_personas_are_frozen(self) -> None:
        """Persona dataclass is frozen (immutable)."""
        persona = select_persona("admin")
        with pytest.raises(Exception):
            persona.role = "hacked"  # type: ignore[misc]

    def test_persona_map_has_5_entries(self) -> None:
        """PERSONA_MAP has exactly 5 role entries."""
        assert len(PERSONA_MAP) == 5

    def test_persona_tones_are_distinct(self) -> None:
        """Each persona has a distinct tone."""
        tones = {p.tone for p in PERSONA_MAP.values()}
        assert len(tones) == 5, "All personas should have unique tones"

    def test_persona_agent_names_are_distinct(self) -> None:
        """Each persona has a unique agent_name."""
        names = {p.agent_name for p in PERSONA_MAP.values()}
        assert len(names) == 5, "All personas should have unique agent names"
