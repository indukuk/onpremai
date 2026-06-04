"""Layer 3: Deterministic scoring node.

Calculates the final weighted score from all criterion results and
applies floor rules. This layer is 100% deterministic: same inputs
always produce the same score.

Floor rules:
- If any policy criterion is FAIL: cap score at 0.84 (partially_compliant max)
- If >25% of implementation criteria FAIL: force non_compliant
- If cannot_assess weight >= 50%: insufficient_evidence
"""

from __future__ import annotations

import time
from typing import Any

import structlog

from src.graph.state import EvalGraphState
from src.models import (
    ComplianceStatus,
    CriterionResult,
    CriterionResultEnum,
    LayerStats,
    TestingCriteria,
    TimingStats,
)

logger = structlog.get_logger(__name__)

# Score values for each result type
SCORE_VALUES: dict[CriterionResultEnum, float] = {
    CriterionResultEnum.PASS: 1.0,
    CriterionResultEnum.PARTIAL: 0.5,
    CriterionResultEnum.FAIL: 0.0,
    CriterionResultEnum.NEEDS_JUDGMENT: 0.0,
    CriterionResultEnum.CANNOT_ASSESS: 0.0,
    CriterionResultEnum.INSUFFICIENT_EVIDENCE: 0.0,
}

# Compliance status thresholds
COMPLIANT_THRESHOLD = 0.85
PARTIAL_THRESHOLD = 0.60


async def scoring_node(state: EvalGraphState) -> dict[str, Any]:
    """Calculate the final compliance score from all criterion results.

    Merges Layer 1 (rule) and Layer 2 (judgment) results, then applies:
    1. Weighted score formula
    2. Floor rules (policy FAIL cap, implementation FAIL force, insufficient evidence)
    3. Threshold mapping to compliance status
    """
    start_time = time.time()

    testing_criteria: TestingCriteria | None = state.get("testing_criteria")
    rule_results: dict[str, CriterionResult] = state.get("rule_results", {})
    judgment_results: dict[str, CriterionResult] = state.get("judgment_results", {})
    partial_evaluation = state.get("partial_evaluation", False)
    trace_id = state.get("trace_id", "")

    if testing_criteria is None:
        return {
            "final_score": 0.0,
            "final_status": ComplianceStatus.INSUFFICIENT_EVIDENCE,
        }

    # Merge all results (judgment results override rule results for same criterion)
    all_results: dict[str, CriterionResult] = {}
    all_results.update(rule_results)
    all_results.update(judgment_results)

    # Calculate score
    score, status = _calculate_score(
        all_results=all_results,
        criteria=testing_criteria,
        partial_evaluation=partial_evaluation,
    )

    elapsed_ms = (time.time() - start_time) * 1000

    logger.info(
        "scoring_complete",
        score=round(score, 4),
        status=status.value,
        partial=partial_evaluation,
        elapsed_ms=round(elapsed_ms, 1),
        trace_id=trace_id,
    )

    # Build timing
    existing_timing = state.get("timing")
    timing_dict: dict[str, float] = {}
    if existing_timing is not None:
        timing_dict["discovery_ms"] = existing_timing.discovery_ms
        timing_dict["extraction_ms"] = existing_timing.extraction_ms
        timing_dict["layer1_ms"] = existing_timing.layer1_ms
        timing_dict["layer2_ms"] = existing_timing.layer2_ms
    timing_dict["layer3_ms"] = elapsed_ms

    return {
        "final_score": score,
        "final_status": status,
        "timing": TimingStats(**timing_dict),
    }


def _calculate_score(
    all_results: dict[str, CriterionResult],
    criteria: TestingCriteria,
    partial_evaluation: bool,
) -> tuple[float, ComplianceStatus]:
    """Core scoring formula with floor rules.

    Returns:
        Tuple of (score, compliance_status).
    """
    # Build criterion lookup
    criteria_map = {c.id: c for c in criteria.criteria}

    # Identify assessable criteria (exclude CANNOT_ASSESS and INSUFFICIENT_EVIDENCE)
    non_assessable_statuses = {
        CriterionResultEnum.CANNOT_ASSESS,
        CriterionResultEnum.INSUFFICIENT_EVIDENCE,
    }

    assessable_weight = 0.0
    total_weight = 0.0
    non_assessable_weight = 0.0

    for criterion in criteria.criteria:
        total_weight += criterion.weight
        result = all_results.get(criterion.id)
        if result is None or result.result in non_assessable_statuses:
            non_assessable_weight += criterion.weight
        else:
            assessable_weight += criterion.weight

    # Floor rule: if cannot_assess weight >= 50% -> insufficient_evidence
    if total_weight > 0 and non_assessable_weight / total_weight >= 0.50:
        return 0.0, ComplianceStatus.INSUFFICIENT_EVIDENCE

    if assessable_weight == 0:
        return 0.0, ComplianceStatus.INSUFFICIENT_EVIDENCE

    # Calculate weighted score
    weighted_sum = 0.0
    for criterion in criteria.criteria:
        result = all_results.get(criterion.id)
        if result is None or result.result in non_assessable_statuses:
            continue
        score_value = SCORE_VALUES.get(result.result, 0.0)
        weighted_sum += criterion.weight * score_value

    raw_score = weighted_sum / assessable_weight

    # Apply floor rules
    final_score = raw_score

    # Floor rule 1: Any policy criterion FAIL caps at 0.84
    policy_fail = _check_policy_fail(all_results, criteria_map)
    if policy_fail and final_score > 0.84:
        final_score = 0.84

    # Floor rule 2: >25% of implementation criteria FAIL forces non_compliant
    impl_fail_ratio = _check_implementation_fail_ratio(all_results, criteria_map)
    if impl_fail_ratio > 0.25:
        return final_score, ComplianceStatus.NON_COMPLIANT

    # Map to compliance status
    if partial_evaluation:
        status = ComplianceStatus.PARTIAL_EVALUATION
    elif final_score >= COMPLIANT_THRESHOLD:
        status = ComplianceStatus.COMPLIANT
    elif final_score >= PARTIAL_THRESHOLD:
        status = ComplianceStatus.PARTIALLY_COMPLIANT
    else:
        status = ComplianceStatus.NON_COMPLIANT

    return final_score, status


def _check_policy_fail(
    all_results: dict[str, CriterionResult],
    criteria_map: dict[str, Any],
) -> bool:
    """Check if any policy-category criterion has FAIL result."""
    for criterion_id, result in all_results.items():
        if result.category == "policy" and result.result == CriterionResultEnum.FAIL:
            return True
    return False


def _check_implementation_fail_ratio(
    all_results: dict[str, CriterionResult],
    criteria_map: dict[str, Any],
) -> float:
    """Calculate the ratio of FAIL results among implementation criteria."""
    impl_total = 0
    impl_fail = 0

    for criterion_id, result in all_results.items():
        if result.category == "implementation":
            impl_total += 1
            if result.result == CriterionResultEnum.FAIL:
                impl_fail += 1

    if impl_total == 0:
        return 0.0

    return impl_fail / impl_total
