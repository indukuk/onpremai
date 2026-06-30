"""Output formatting node.

Assembles the final EvalResult from all accumulated state. This is the
terminal node that produces the structured evaluation output consumed
by the API response.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Any

import structlog

from common.clients import MemoryClient

from src.graph.state import EvalGraphState
from src.models import (
    ComplianceStatus,
    CriterionResult,
    CriterionResultEnum,
    EvalMethod,
    EvalResult,
    LayerStats,
    TestingCriteria,
    TimingStats,
)

logger = structlog.get_logger(__name__)


async def formatter_node(state: EvalGraphState) -> dict[str, Any]:
    """Format the final evaluation result from accumulated graph state.

    Merges all criterion results, attaches timing and layer stats,
    stores the result in memory service, and produces the final
    EvalResult object.
    """
    start_time = time.time()

    control_id = state.get("control_id", "")
    framework = state.get("framework", "")
    tenant_id = state.get("tenant_id", "")
    trace_id = state.get("trace_id", "")
    evidence_hash = state.get("evidence_hash", "")
    final_score = state.get("final_score", 0.0)
    final_status = state.get("final_status", ComplianceStatus.INSUFFICIENT_EVIDENCE)
    partial_evaluation = state.get("partial_evaluation", False)
    timing = state.get("timing", TimingStats())
    layer_stats = state.get("layer_stats", LayerStats())
    error = state.get("error")

    # Check for cached result
    cached_result = state.get("cached_result")
    if cached_result is not None:
        return {"evaluation_result": cached_result}

    # If there was an error before scoring (e.g., no evidence)
    if error and final_score == 0.0:
        eval_result = EvalResult(
            evaluation_id=str(uuid.uuid4()),
            control_id=control_id,
            framework=framework,
            tenant_id=tenant_id,
            score=0.0,
            status=ComplianceStatus.INSUFFICIENT_EVIDENCE,
            evidence_hash=evidence_hash,
            criteria_results=[],
            layer_stats=layer_stats,
            timing=timing,
            partial_evaluation=partial_evaluation,
            metadata={"error": error},
        )
        return {"evaluation_result": eval_result}

    # Merge all criterion results
    rule_results: dict[str, CriterionResult] = state.get("rule_results", {})
    judgment_results: dict[str, CriterionResult] = state.get("judgment_results", {})
    tribunal_justifications: dict[str, dict[str, Any]] = state.get("tribunal_justifications", {})

    all_results: dict[str, CriterionResult] = {}
    all_results.update(rule_results)
    all_results.update(judgment_results)

    # Order by testing criteria order
    testing_criteria: TestingCriteria | None = state.get("testing_criteria")
    ordered_results: list[CriterionResult] = []

    if testing_criteria is not None:
        for criterion in testing_criteria.criteria:
            result = all_results.get(criterion.id)
            if result is not None:
                ordered_results.append(result)
    else:
        ordered_results = list(all_results.values())

    # Compute total timing
    elapsed_ms = (time.time() - start_time) * 1000
    total_ms = (
        timing.discovery_ms
        + timing.extraction_ms
        + timing.layer1_ms
        + timing.layer2_ms
        + timing.layer3_ms
        + timing.sandbox_ms
        + elapsed_ms
    )

    final_timing = TimingStats(
        total_ms=total_ms,
        discovery_ms=timing.discovery_ms,
        extraction_ms=timing.extraction_ms,
        layer1_ms=timing.layer1_ms,
        layer2_ms=timing.layer2_ms,
        layer3_ms=timing.layer3_ms,
        sandbox_ms=timing.sandbox_ms,
    )

    # Assemble justification document
    layer1_count = len(rule_results)
    layer2_count = len(judgment_results)

    # Determine floor rules applied
    floor_rules_applied: list[str] = []
    policy_fail = any(
        r.category == "policy" and r.result == CriterionResultEnum.FAIL
        for r in all_results.values()
    )
    if policy_fail and final_score <= 0.84:
        floor_rules_applied.append("policy_fail_cap_0.84")

    impl_total = sum(1 for r in all_results.values() if r.category == "implementation")
    impl_fail = sum(
        1 for r in all_results.values()
        if r.category == "implementation" and r.result == CriterionResultEnum.FAIL
    )
    if impl_total > 0 and impl_fail / impl_total > 0.25:
        floor_rules_applied.append("implementation_fail_ratio_gt_25pct")

    justification: dict[str, Any] = {
        "summary": (
            f"Control {control_id} is {final_status.value}. "
            f"{layer1_count} criteria resolved by rules, "
            f"{layer2_count} by tribunal."
        ),
        "layer1_justification": {
            "method": "deterministic_rules",
            "resolved_count": layer1_count,
            "criteria": [
                {
                    "criterion_id": cid,
                    "result": result.result.value,
                    "method": result.method.value,
                    "reason": result.reason,
                    "evidence_cited": result.evidence_used,
                }
                for cid, result in rule_results.items()
            ],
        },
        "layer2_justification": {
            "method": "adversarial_tribunal",
            "resolved_count": layer2_count,
            "criteria": tribunal_justifications,
        },
        "layer3_justification": {
            "method": "deterministic_scoring",
            "score": round(final_score, 4),
            "status": final_status.value,
            "floor_rules_applied": floor_rules_applied,
        },
    }

    # Build final result
    eval_result = EvalResult(
        evaluation_id=str(uuid.uuid4()),
        control_id=control_id,
        framework=framework,
        tenant_id=tenant_id,
        score=round(final_score, 4),
        status=final_status,
        evidence_hash=evidence_hash,
        criteria_results=ordered_results,
        justification=justification,
        layer_stats=layer_stats,
        timing=final_timing,
        partial_evaluation=partial_evaluation,
        cached=False,
    )

    # Store in memory service and publish events
    memory = MemoryClient()
    try:
        # Fetch previous evaluation to detect status changes
        previous_status: ComplianceStatus | None = None
        previous_score: float | None = None
        try:
            prev_results = await memory.eval_recall(
                tenant_id=tenant_id,
                framework=framework,
                control_id=control_id,
                limit=1,
            )
            if prev_results:
                prev = prev_results[0]
                prev_status_raw = prev.get("result", {}).get("status")
                if prev_status_raw:
                    previous_status = ComplianceStatus(prev_status_raw)
                    previous_score = prev.get("result", {}).get("score")
        except Exception as exc:
            logger.warning(
                "eval_recall_for_diff_failed",
                error=str(exc),
                trace_id=trace_id,
            )

        await memory.eval_store(
            tenant_id=tenant_id,
            framework=framework,
            control_id=control_id,
            result=eval_result.model_dump(mode="json"),
            metadata={
                "evidence_hash": evidence_hash,
                "partial": partial_evaluation,
                "trace_id": trace_id,
            },
        )

        # Create evaluation decision record (fire-and-forget)
        try:
            await memory.eval_decision_create(
                evaluation_id=eval_result.evaluation_id,
                tenant_id=tenant_id,
                control_id=control_id,
                framework=framework,
                ai_score=round(final_score, 4),
                ai_status=final_status.value,
            )
        except Exception as exc:
            logger.warning(
                "eval_decision_create_failed",
                error=str(exc),
                trace_id=trace_id,
            )

        # Publish evaluation_completed event
        try:
            await memory.event_queue_push(
                user_id="__all__",
                tenant_id=tenant_id,
                event_type="evaluation_completed",
                summary=f"{control_id} evaluated: {final_status.value}",
                priority="medium",
                source_service="agent-eval",
                metadata={
                    "control_id": control_id,
                    "framework": framework,
                    "status": final_status.value,
                    "score": round(final_score, 4),
                    "trace_id": trace_id,
                },
            )
        except Exception as exc:
            logger.warning(
                "event_push_failed",
                event_type="evaluation_completed",
                error=str(exc),
                trace_id=trace_id,
            )

        # Publish readiness_changed event if status differs from previous evaluation
        if previous_status is not None and previous_status != final_status:
            try:
                await memory.event_queue_push(
                    user_id="__all__",
                    tenant_id=tenant_id,
                    event_type="readiness_changed",
                    summary=(
                        f"{control_id} status changed: "
                        f"{previous_status.value} -> {final_status.value}"
                    ),
                    priority="high",
                    source_service="agent-eval",
                    metadata={
                        "control_id": control_id,
                        "framework": framework,
                        "previous_status": previous_status.value,
                        "new_status": final_status.value,
                        "previous_score": round(previous_score, 4) if previous_score is not None else None,
                        "new_score": round(final_score, 4),
                        "trace_id": trace_id,
                    },
                )
            except Exception as exc:
                logger.warning(
                    "event_push_failed",
                    event_type="readiness_changed",
                    error=str(exc),
                    trace_id=trace_id,
                )

    except Exception as exc:
        logger.warning(
            "eval_store_failed",
            error=str(exc),
            trace_id=trace_id,
        )
    finally:
        await memory.close()

    logger.info(
        "evaluation_formatted",
        control_id=control_id,
        framework=framework,
        score=eval_result.score,
        status=eval_result.status.value,
        criteria_count=len(ordered_results),
        total_ms=round(total_ms, 1),
        trace_id=trace_id,
    )

    return {"evaluation_result": eval_result}
