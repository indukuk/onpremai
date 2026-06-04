"""Layer 1: Deterministic rule engine node.

Dispatches each testing criterion to the appropriate rule checker.
Returns PASS, FAIL, or NEEDS_JUDGMENT per criterion. Rules resolve
60-70% of criteria without any LLM cost.
"""

from __future__ import annotations

import time
from typing import Any

import structlog

from src.graph.state import EvalGraphState
from src.models import (
    Criterion,
    CriterionResult,
    CriterionResultEnum,
    EvalMethod,
    EvidenceMetadata,
    LayerStats,
    TestingCriteria,
    TimingStats,
)
from src.rules.engine import dispatch_rule

logger = structlog.get_logger(__name__)


async def rules_engine_node(state: EvalGraphState) -> dict[str, Any]:
    """Apply deterministic rule checks to all criteria.

    For each criterion in the testing criteria:
    1. Select the appropriate rule based on check_type or evidence_type
    2. Apply the rule against the evidence metadata
    3. Record PASS/FAIL/NEEDS_JUDGMENT

    Criteria that cannot be resolved by rules are marked NEEDS_JUDGMENT
    for Layer 2 (LLM).
    """
    start_time = time.time()

    testing_criteria: TestingCriteria | None = state.get("testing_criteria")
    evidence_metadata: list[EvidenceMetadata] = state.get("evidence_metadata", [])
    evidence_files = state.get("evidence_files", [])
    trace_id = state.get("trace_id", "")

    if testing_criteria is None:
        return {
            "rule_results": {},
            "needs_judgment": [],
            "error": "No testing criteria available",
        }

    rule_results: dict[str, CriterionResult] = {}
    needs_judgment: list[str] = []
    layer1_resolved = 0

    for criterion in testing_criteria.criteria:
        result = await _evaluate_criterion_with_rules(
            criterion=criterion,
            evidence_metadata=evidence_metadata,
            evidence_files=evidence_files,
        )

        rule_results[criterion.id] = result

        if result.result == CriterionResultEnum.NEEDS_JUDGMENT:
            needs_judgment.append(criterion.id)
        else:
            layer1_resolved += 1

    elapsed_ms = (time.time() - start_time) * 1000

    logger.info(
        "rules_engine_complete",
        total_criteria=len(testing_criteria.criteria),
        layer1_resolved=layer1_resolved,
        needs_judgment=len(needs_judgment),
        elapsed_ms=round(elapsed_ms, 1),
        trace_id=trace_id,
    )

    # Build timing/stats
    existing_timing = state.get("timing")
    timing_dict: dict[str, float] = {}
    if existing_timing is not None:
        timing_dict["discovery_ms"] = existing_timing.discovery_ms
        timing_dict["extraction_ms"] = existing_timing.extraction_ms
    timing_dict["layer1_ms"] = elapsed_ms

    return {
        "rule_results": rule_results,
        "needs_judgment": needs_judgment,
        "timing": TimingStats(**timing_dict),
        "layer_stats": LayerStats(
            layer1_resolved=layer1_resolved,
            total_criteria=len(testing_criteria.criteria),
        ),
    }


async def _evaluate_criterion_with_rules(
    criterion: Criterion,
    evidence_metadata: list[EvidenceMetadata],
    evidence_files: list[Any],
) -> CriterionResult:
    """Evaluate a single criterion using deterministic rules.

    Selects the rule based on criterion's check_type or infers from
    evidence_type. Returns NEEDS_JUDGMENT if no rule can determine the result.
    """
    check_type = criterion.check_type

    # If no explicit check_type, infer from evidence_type and pass_condition
    if not check_type:
        check_type = _infer_check_type(criterion)

    if not check_type:
        return CriterionResult(
            criterion_id=criterion.id,
            category=criterion.category,
            result=CriterionResultEnum.NEEDS_JUDGMENT,
            method=EvalMethod.LLM_JUDGMENT,
            reason="No deterministic rule available for this criterion",
        )

    # Dispatch to the appropriate rule handler
    result = dispatch_rule(
        check_type=check_type,
        criterion=criterion,
        evidence_metadata=evidence_metadata,
        evidence_files=evidence_files,
    )

    return result


def _infer_check_type(criterion: Criterion) -> str | None:
    """Infer which rule check to apply based on criterion properties."""
    evidence_type = criterion.evidence_type.lower()
    pass_cond = criterion.pass_condition.lower()

    # Document-type criteria often need keyword presence or file existence
    if evidence_type == "document":
        if "exists" in pass_cond or "policy" in pass_cond.split()[:3]:
            return "file_existence"
        if "reviewed within" in pass_cond or "months" in pass_cond:
            return "freshness"
        if "mentions" in pass_cond or "contains" in pass_cond or "covers" in pass_cond:
            return "keyword_presence"
        return None

    # Structured data criteria can use row count, null rate, schema, cross-ref
    if evidence_type == "structured_data":
        if "count" in pass_cond or "records exist" in pass_cond:
            return "row_count"
        if "populated" in pass_cond or "null" in pass_cond:
            return "null_rate"
        if "cross-reference" in pass_cond or "no active" in pass_cond:
            return "cross_reference"
        if "columns" in pass_cond or "fields" in pass_cond:
            return "schema_presence"
        if any(word in pass_cond for word in ("threshold", "within", "max", "minimum")):
            return "quantitative"
        return "row_count"

    # Unstructured evidence typically needs LLM judgment
    return None
