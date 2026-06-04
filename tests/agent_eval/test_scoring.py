"""Tests for Layer 3: Deterministic scoring node.

Tests the weighted score formula, compliance status thresholds, and
floor rules:
- Policy FAIL caps score at 0.84
- >25% implementation FAIL forces non_compliant
- Non-assessable weight >= 50% forces insufficient_evidence
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "agent-eval"))

from src.graph.scoring import (
    COMPLIANT_THRESHOLD,
    PARTIAL_THRESHOLD,
    SCORE_VALUES,
    _calculate_score,
    _check_implementation_fail_ratio,
    _check_policy_fail,
    scoring_node,
)
from src.models import (
    ComplianceStatus,
    Criterion,
    CriterionResult,
    CriterionResultEnum,
    EvalMethod,
    LayerStats,
    TestingCriteria,
    TimingStats,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _criterion(id: str, category: str, weight: float) -> Criterion:
    return Criterion(
        id=id,
        category=category,
        question="Test question",
        evidence_type="document",
        pass_condition="Test",
        fail_condition="Test",
        weight=weight,
    )


def _result(
    criterion_id: str, category: str, result: CriterionResultEnum
) -> CriterionResult:
    return CriterionResult(
        criterion_id=criterion_id,
        category=category,
        result=result,
        method=EvalMethod.LLM_JUDGMENT,
        reason="Test",
    )


def _testing_criteria(criteria: list[Criterion]) -> TestingCriteria:
    return TestingCriteria(
        control_id="CC6.1",
        framework="SOC2",
        control_objective="Test",
        criteria=criteria,
    )


# ---------------------------------------------------------------------------
# WEIGHTED FORMULA TESTS
# ---------------------------------------------------------------------------


class TestWeightedScoreFormula:
    """Tests for the core weighted scoring calculation."""

    def test_all_pass_scores_1_0(self):
        """Score is 1.0 when all criteria PASS."""
        criteria = [
            _criterion("C1", "policy", 0.3),
            _criterion("C2", "implementation", 0.4),
            _criterion("C3", "implementation", 0.3),
        ]
        results = {
            "C1": _result("C1", "policy", CriterionResultEnum.PASS),
            "C2": _result("C2", "implementation", CriterionResultEnum.PASS),
            "C3": _result("C3", "implementation", CriterionResultEnum.PASS),
        }

        score, status = _calculate_score(results, _testing_criteria(criteria), False)

        assert score == 1.0
        assert status == ComplianceStatus.COMPLIANT

    def test_all_fail_scores_0_0(self):
        """Score is 0.0 when all criteria FAIL."""
        criteria = [
            _criterion("C1", "implementation", 0.5),
            _criterion("C2", "implementation", 0.5),
        ]
        results = {
            "C1": _result("C1", "implementation", CriterionResultEnum.FAIL),
            "C2": _result("C2", "implementation", CriterionResultEnum.FAIL),
        }

        score, status = _calculate_score(results, _testing_criteria(criteria), False)

        assert score == 0.0
        assert status == ComplianceStatus.NON_COMPLIANT

    def test_partial_results_half_score(self):
        """Score is 0.5 when all criteria are PARTIAL."""
        criteria = [
            _criterion("C1", "implementation", 0.5),
            _criterion("C2", "implementation", 0.5),
        ]
        results = {
            "C1": _result("C1", "implementation", CriterionResultEnum.PARTIAL),
            "C2": _result("C2", "implementation", CriterionResultEnum.PARTIAL),
        }

        score, status = _calculate_score(results, _testing_criteria(criteria), False)

        assert score == 0.5
        assert status == ComplianceStatus.NON_COMPLIANT

    def test_weighted_calculation_correct(self):
        """Score correctly weights different criteria."""
        criteria = [
            _criterion("C1", "implementation", 0.6),  # PASS -> 0.6 * 1.0 = 0.6
            _criterion("C2", "implementation", 0.4),  # FAIL -> 0.4 * 0.0 = 0.0
        ]
        results = {
            "C1": _result("C1", "implementation", CriterionResultEnum.PASS),
            "C2": _result("C2", "implementation", CriterionResultEnum.FAIL),
        }

        score, status = _calculate_score(results, _testing_criteria(criteria), False)

        # (0.6*1.0 + 0.4*0.0) / (0.6+0.4) = 0.6
        assert abs(score - 0.6) < 0.001
        assert status == ComplianceStatus.PARTIALLY_COMPLIANT

    def test_mixed_pass_partial_fail_weights(self):
        """Complex mix of results produces correct weighted score."""
        criteria = [
            _criterion("C1", "implementation", 0.3),  # PASS -> 0.3
            _criterion("C2", "implementation", 0.3),  # PARTIAL -> 0.15
            _criterion("C3", "implementation", 0.4),  # PASS -> 0.4
        ]
        results = {
            "C1": _result("C1", "implementation", CriterionResultEnum.PASS),
            "C2": _result("C2", "implementation", CriterionResultEnum.PARTIAL),
            "C3": _result("C3", "implementation", CriterionResultEnum.PASS),
        }

        score, status = _calculate_score(results, _testing_criteria(criteria), False)

        # (0.3*1.0 + 0.3*0.5 + 0.4*1.0) / 1.0 = 0.85
        assert abs(score - 0.85) < 0.001
        assert status == ComplianceStatus.COMPLIANT


# ---------------------------------------------------------------------------
# COMPLIANCE STATUS THRESHOLD TESTS
# ---------------------------------------------------------------------------


class TestComplianceStatusThresholds:
    """Tests for threshold-based status determination."""

    def test_compliant_at_threshold(self):
        """Status is COMPLIANT when score is at 0.85 threshold."""
        criteria = [_criterion("C1", "implementation", 1.0)]
        results = {
            "C1": _result("C1", "implementation", CriterionResultEnum.PASS),
        }

        score, status = _calculate_score(results, _testing_criteria(criteria), False)

        assert score >= COMPLIANT_THRESHOLD
        assert status == ComplianceStatus.COMPLIANT

    def test_partially_compliant_range(self):
        """Status is PARTIALLY_COMPLIANT between 0.60 and 0.85."""
        criteria = [
            _criterion("C1", "implementation", 0.5),
            _criterion("C2", "implementation", 0.5),
        ]
        results = {
            "C1": _result("C1", "implementation", CriterionResultEnum.PASS),
            "C2": _result("C2", "implementation", CriterionResultEnum.PARTIAL),
        }

        score, status = _calculate_score(results, _testing_criteria(criteria), False)

        # (0.5*1.0 + 0.5*0.5) / 1.0 = 0.75
        assert PARTIAL_THRESHOLD <= score < COMPLIANT_THRESHOLD
        assert status == ComplianceStatus.PARTIALLY_COMPLIANT

    def test_non_compliant_below_060(self):
        """Status is NON_COMPLIANT when score is below 0.60."""
        criteria = [
            _criterion("C1", "implementation", 0.5),
            _criterion("C2", "implementation", 0.5),
        ]
        results = {
            "C1": _result("C1", "implementation", CriterionResultEnum.FAIL),
            "C2": _result("C2", "implementation", CriterionResultEnum.PARTIAL),
        }

        score, status = _calculate_score(results, _testing_criteria(criteria), False)

        # (0.5*0.0 + 0.5*0.5) / 1.0 = 0.25
        assert score < PARTIAL_THRESHOLD
        assert status == ComplianceStatus.NON_COMPLIANT

    def test_partial_evaluation_flag(self):
        """Status is PARTIAL_EVALUATION when partial_evaluation is True."""
        criteria = [_criterion("C1", "implementation", 1.0)]
        results = {
            "C1": _result("C1", "implementation", CriterionResultEnum.PASS),
        }

        score, status = _calculate_score(results, _testing_criteria(criteria), True)

        assert score == 1.0
        assert status == ComplianceStatus.PARTIAL_EVALUATION


# ---------------------------------------------------------------------------
# FLOOR RULE 1: POLICY FAIL CAPS AT 0.84
# ---------------------------------------------------------------------------


class TestPolicyFailFloorRule:
    """Tests for the policy FAIL floor rule (caps at 0.84)."""

    def test_policy_fail_caps_score(self):
        """Score capped at 0.84 when any policy criterion FAILs."""
        criteria = [
            _criterion("C1", "policy", 0.1),
            _criterion("C2", "implementation", 0.45),
            _criterion("C3", "implementation", 0.45),
        ]
        results = {
            "C1": _result("C1", "policy", CriterionResultEnum.FAIL),
            "C2": _result("C2", "implementation", CriterionResultEnum.PASS),
            "C3": _result("C3", "implementation", CriterionResultEnum.PASS),
        }

        score, status = _calculate_score(results, _testing_criteria(criteria), False)

        # Raw: (0.1*0 + 0.45*1 + 0.45*1) / 1.0 = 0.9 -> capped at 0.84
        assert score == 0.84
        assert status == ComplianceStatus.PARTIALLY_COMPLIANT

    def test_policy_pass_no_cap(self):
        """Score NOT capped when all policy criteria pass."""
        criteria = [
            _criterion("C1", "policy", 0.1),
            _criterion("C2", "implementation", 0.45),
            _criterion("C3", "implementation", 0.45),
        ]
        results = {
            "C1": _result("C1", "policy", CriterionResultEnum.PASS),
            "C2": _result("C2", "implementation", CriterionResultEnum.PASS),
            "C3": _result("C3", "implementation", CriterionResultEnum.PASS),
        }

        score, status = _calculate_score(results, _testing_criteria(criteria), False)

        assert score == 1.0
        assert status == ComplianceStatus.COMPLIANT

    def test_policy_fail_does_not_cap_when_already_below(self):
        """Policy FAIL does not reduce score if already below 0.84."""
        criteria = [
            _criterion("C1", "policy", 0.5),
            _criterion("C2", "implementation", 0.5),
        ]
        results = {
            "C1": _result("C1", "policy", CriterionResultEnum.FAIL),
            "C2": _result("C2", "implementation", CriterionResultEnum.PARTIAL),
        }

        score, status = _calculate_score(results, _testing_criteria(criteria), False)

        # (0.5*0.0 + 0.5*0.5) / 1.0 = 0.25 (below 0.84, no cap applied)
        assert score == 0.25


# ---------------------------------------------------------------------------
# FLOOR RULE 2: >25% IMPLEMENTATION FAIL FORCES NON_COMPLIANT
# ---------------------------------------------------------------------------


class TestImplementationFailFloorRule:
    """Tests for the >25% implementation FAIL floor rule."""

    def test_over_25_pct_impl_fail_forces_non_compliant(self):
        """Status forced to NON_COMPLIANT when >25% implementation criteria FAIL."""
        criteria = [
            _criterion("C1", "policy", 0.1),
            _criterion("C2", "implementation", 0.3),
            _criterion("C3", "implementation", 0.3),
            _criterion("C4", "implementation", 0.3),
        ]
        # 2 of 3 impl criteria FAIL = 66% > 25%
        results = {
            "C1": _result("C1", "policy", CriterionResultEnum.PASS),
            "C2": _result("C2", "implementation", CriterionResultEnum.FAIL),
            "C3": _result("C3", "implementation", CriterionResultEnum.FAIL),
            "C4": _result("C4", "implementation", CriterionResultEnum.PASS),
        }

        score, status = _calculate_score(results, _testing_criteria(criteria), False)

        assert status == ComplianceStatus.NON_COMPLIANT

    def test_exactly_25_pct_impl_fail_not_forced(self):
        """Status NOT forced when exactly 25% implementation criteria FAIL."""
        criteria = [
            _criterion("C1", "implementation", 0.25),
            _criterion("C2", "implementation", 0.25),
            _criterion("C3", "implementation", 0.25),
            _criterion("C4", "implementation", 0.25),
        ]
        # 1 of 4 impl criteria FAIL = 25% (not > 25%)
        results = {
            "C1": _result("C1", "implementation", CriterionResultEnum.FAIL),
            "C2": _result("C2", "implementation", CriterionResultEnum.PASS),
            "C3": _result("C3", "implementation", CriterionResultEnum.PASS),
            "C4": _result("C4", "implementation", CriterionResultEnum.PASS),
        }

        score, status = _calculate_score(results, _testing_criteria(criteria), False)

        # 25% is not > 25%, so floor rule does NOT apply
        assert status != ComplianceStatus.NON_COMPLIANT or score < PARTIAL_THRESHOLD

    def test_no_implementation_criteria_no_floor(self):
        """Floor rule does not trigger when no implementation criteria exist."""
        criteria = [
            _criterion("C1", "policy", 0.5),
            _criterion("C2", "policy", 0.5),
        ]
        results = {
            "C1": _result("C1", "policy", CriterionResultEnum.PASS),
            "C2": _result("C2", "policy", CriterionResultEnum.PASS),
        }

        score, status = _calculate_score(results, _testing_criteria(criteria), False)

        assert score == 1.0
        assert status == ComplianceStatus.COMPLIANT


# ---------------------------------------------------------------------------
# FLOOR RULE 3: INSUFFICIENT EVIDENCE (>= 50% NON-ASSESSABLE)
# ---------------------------------------------------------------------------


class TestInsufficientEvidenceFloorRule:
    """Tests for the insufficient_evidence floor rule."""

    def test_insufficient_evidence_when_half_cannot_assess(self):
        """Status is INSUFFICIENT_EVIDENCE when >= 50% weight is non-assessable."""
        criteria = [
            _criterion("C1", "implementation", 0.5),
            _criterion("C2", "implementation", 0.5),
        ]
        results = {
            "C1": _result("C1", "implementation", CriterionResultEnum.CANNOT_ASSESS),
            "C2": _result("C2", "implementation", CriterionResultEnum.PASS),
        }

        score, status = _calculate_score(results, _testing_criteria(criteria), False)

        assert status == ComplianceStatus.INSUFFICIENT_EVIDENCE
        assert score == 0.0

    def test_insufficient_evidence_missing_results(self):
        """INSUFFICIENT_EVIDENCE when results are entirely missing (None)."""
        criteria = [
            _criterion("C1", "implementation", 0.5),
            _criterion("C2", "implementation", 0.5),
        ]
        # No results at all
        results: dict[str, CriterionResult] = {}

        score, status = _calculate_score(results, _testing_criteria(criteria), False)

        assert status == ComplianceStatus.INSUFFICIENT_EVIDENCE

    def test_below_50_pct_non_assessable_still_scores(self):
        """Normal scoring when non-assessable weight < 50%."""
        criteria = [
            _criterion("C1", "implementation", 0.3),
            _criterion("C2", "implementation", 0.3),
            _criterion("C3", "implementation", 0.4),
        ]
        results = {
            "C1": _result("C1", "implementation", CriterionResultEnum.CANNOT_ASSESS),
            "C2": _result("C2", "implementation", CriterionResultEnum.PASS),
            "C3": _result("C3", "implementation", CriterionResultEnum.PASS),
        }

        score, status = _calculate_score(results, _testing_criteria(criteria), False)

        # 0.3/1.0 = 30% non-assessable, so normal scoring applies
        # Assessable: C2(0.3*1.0) + C3(0.4*1.0) / 0.7 = 1.0
        assert score == 1.0
        assert status == ComplianceStatus.COMPLIANT


# ---------------------------------------------------------------------------
# SCORING NODE (GRAPH NODE)
# ---------------------------------------------------------------------------


class TestScoringNode:
    """Tests for the scoring_node graph node function."""

    @pytest.mark.asyncio
    async def test_scoring_node_basic(self, sample_testing_criteria):
        """Scoring node produces final_score and final_status."""
        tc = sample_testing_criteria()
        rule_results = {
            "C1": _result("C1", "policy", CriterionResultEnum.PASS),
            "C2": _result("C2", "implementation", CriterionResultEnum.PASS),
            "C3": _result("C3", "implementation", CriterionResultEnum.PASS),
            "C4": _result("C4", "implementation", CriterionResultEnum.PASS),
        }

        state = {
            "testing_criteria": tc,
            "rule_results": rule_results,
            "judgment_results": {},
            "partial_evaluation": False,
            "trace_id": "t1",
            "timing": TimingStats(layer1_ms=10.0, layer2_ms=5.0),
        }

        result = await scoring_node(state)

        assert result["final_score"] == 1.0
        assert result["final_status"] == ComplianceStatus.COMPLIANT
        assert result["timing"].layer3_ms > 0

    @pytest.mark.asyncio
    async def test_scoring_node_no_criteria_returns_insufficient(self):
        """Returns INSUFFICIENT_EVIDENCE when no testing criteria."""
        state = {
            "testing_criteria": None,
            "rule_results": {},
            "judgment_results": {},
            "trace_id": "t1",
        }

        result = await scoring_node(state)

        assert result["final_score"] == 0.0
        assert result["final_status"] == ComplianceStatus.INSUFFICIENT_EVIDENCE

    @pytest.mark.asyncio
    async def test_judgment_results_override_rule_results(self, sample_testing_criteria):
        """Judgment results take precedence over rule results for same criterion."""
        tc = sample_testing_criteria()
        rule_results = {
            "C1": _result("C1", "policy", CriterionResultEnum.NEEDS_JUDGMENT),
            "C2": _result("C2", "implementation", CriterionResultEnum.PASS),
            "C3": _result("C3", "implementation", CriterionResultEnum.PASS),
            "C4": _result("C4", "implementation", CriterionResultEnum.PASS),
        }
        judgment_results = {
            "C1": _result("C1", "policy", CriterionResultEnum.PASS),
        }

        state = {
            "testing_criteria": tc,
            "rule_results": rule_results,
            "judgment_results": judgment_results,
            "partial_evaluation": False,
            "trace_id": "t1",
        }

        result = await scoring_node(state)

        # C1 should use judgment PASS, not rule NEEDS_JUDGMENT
        assert result["final_score"] == 1.0
        assert result["final_status"] == ComplianceStatus.COMPLIANT


# ---------------------------------------------------------------------------
# HELPER FUNCTION TESTS
# ---------------------------------------------------------------------------


class TestHelperFunctions:
    """Tests for internal helper functions."""

    def test_check_policy_fail_true(self):
        results = {
            "C1": _result("C1", "policy", CriterionResultEnum.FAIL),
            "C2": _result("C2", "implementation", CriterionResultEnum.PASS),
        }
        assert _check_policy_fail(results, {}) is True

    def test_check_policy_fail_false(self):
        results = {
            "C1": _result("C1", "policy", CriterionResultEnum.PASS),
            "C2": _result("C2", "implementation", CriterionResultEnum.FAIL),
        }
        assert _check_policy_fail(results, {}) is False

    def test_check_implementation_fail_ratio(self):
        results = {
            "C1": _result("C1", "implementation", CriterionResultEnum.FAIL),
            "C2": _result("C2", "implementation", CriterionResultEnum.PASS),
            "C3": _result("C3", "implementation", CriterionResultEnum.PASS),
            "C4": _result("C4", "implementation", CriterionResultEnum.PASS),
        }
        ratio = _check_implementation_fail_ratio(results, {})
        assert ratio == 0.25

    def test_implementation_fail_ratio_no_impl_criteria(self):
        results = {
            "C1": _result("C1", "policy", CriterionResultEnum.FAIL),
        }
        ratio = _check_implementation_fail_ratio(results, {})
        assert ratio == 0.0
