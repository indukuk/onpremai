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
        layer_stats=layer_stats,
        timing=final_timing,
        partial_evaluation=partial_evaluation,
        cached=False,
    )

    # Store in memory service
    memory = MemoryClient()
    try:
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
