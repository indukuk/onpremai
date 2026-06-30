"""Layer 2: LLM judgment node for NEEDS_JUDGMENT criteria.

Uses tiered evaluation based on criterion weight:
- weight >= 0.20: Full Adversarial Tribunal (Prosecutor + Defender + Judge)
  using 3 different model families for error decorrelation
- weight 0.10-0.19: Simplified Tribunal (Prosecutor + Judge)
- weight < 0.10: Single structured call with rubric

Research basis for multi-model tribunal:
- Du et al. 2023: multi-agent debate improves accuracy 7-16pp
- DEI 2025: heterogeneous model ensembles outperform homogeneous by 124%
- PoLL 2024: diverse smaller model panels outperform single large judge, 7x cheaper
- Wang et al. 2024 (MoA): heterogeneous configs consistently beat homogeneous

Handles LLMCreditExhaustedError gracefully by marking remaining criteria
as INSUFFICIENT_EVIDENCE and setting partial_evaluation=True.
"""

from __future__ import annotations

import json
import time
from typing import Any

import structlog

from common.clients import LLMClient, MemoryClient
from common.errors import LLMCreditExhaustedError, LLMUnavailableError

from src.config import get_settings
from src.graph.state import EvalGraphState
from src.graph.tribunal import TribunalResult, run_simplified_tribunal, run_tribunal
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

logger = structlog.get_logger(__name__)

JUDGMENT_PROMPT = """You are a compliance auditor evaluating a specific criterion.

## Criterion
ID: {criterion_id}
Category: {category}
Question: {question}

## Pass Condition
{pass_condition}

## Fail Condition
{fail_condition}

## Evidence Provided
{evidence_text}

## Instructions
Evaluate whether the evidence satisfies the pass condition.

PASS example: Evidence clearly demonstrates the requirement is met.
FAIL example: Evidence shows the requirement is not met or contradicts it.
PARTIAL example: Evidence partially meets the requirement but has gaps.

Respond in JSON format only:
{{"result": "PASS" | "PARTIAL" | "FAIL", "reason": "one sentence explanation"}}"""


async def evaluation_node(state: EvalGraphState) -> dict[str, Any]:
    """Evaluate NEEDS_JUDGMENT criteria using LLM.

    Steps:
    1. Get list of criteria needing judgment
    2. For each, extract relevant evidence slice
    3. Send bounded question to LLM with rubric
    4. Parse categorical response
    5. Handle credit exhaustion gracefully

    High-weight criteria (>0.20) use 3-sample consensus for reliability.
    """
    start_time = time.time()

    needs_judgment: list[str] = state.get("needs_judgment", [])
    testing_criteria: TestingCriteria | None = state.get("testing_criteria")
    evidence_metadata: list[EvidenceMetadata] = state.get("evidence_metadata", [])
    rule_results: dict[str, CriterionResult] = state.get("rule_results", {})
    tenant_id = state.get("tenant_id", "")
    trace_id = state.get("trace_id", "")
    existing_stats: LayerStats | None = state.get("layer_stats")

    if not needs_judgment or testing_criteria is None:
        elapsed_ms = (time.time() - start_time) * 1000
        return _build_response(state, {}, {}, elapsed_ms, existing_stats, False, 0)

    settings = get_settings()
    llm = LLMClient()
    memory = MemoryClient()

    judgment_results: dict[str, CriterionResult] = {}
    tribunal_justifications: dict[str, dict[str, Any]] = {}
    llm_calls = 0
    partial_evaluation = False

    try:
        # Build criterion lookup
        criteria_map: dict[str, Criterion] = {
            c.id: c for c in testing_criteria.criteria
        }

        for criterion_id in needs_judgment:
            criterion = criteria_map.get(criterion_id)
            if criterion is None:
                continue

            try:
                result, justification_doc = await _judge_single_criterion(
                    llm=llm,
                    criterion=criterion,
                    evidence_metadata=evidence_metadata,
                    tenant_id=tenant_id,
                    trace_id=trace_id,
                    settings=settings,
                )
                judgment_results[criterion_id] = result
                if justification_doc is not None:
                    tribunal_justifications[criterion_id] = justification_doc
                llm_calls += 1

            except LLMCreditExhaustedError as exc:
                logger.warning(
                    "credit_exhausted_during_judgment",
                    criterion_id=criterion_id,
                    degradation_level=exc.degradation_level,
                    remaining=len(needs_judgment) - len(judgment_results),
                    trace_id=trace_id,
                )
                # Mark remaining criteria as insufficient evidence
                partial_evaluation = True
                for remaining_id in needs_judgment:
                    if remaining_id not in judgment_results:
                        judgment_results[remaining_id] = CriterionResult(
                            criterion_id=remaining_id,
                            category=criteria_map[remaining_id].category
                            if remaining_id in criteria_map
                            else "unknown",
                            result=CriterionResultEnum.INSUFFICIENT_EVIDENCE,
                            method=EvalMethod.DEGRADED,
                            reason="LLM budget exhausted - queued for full evaluation",
                        )
                break

            except LLMUnavailableError:
                logger.warning(
                    "llm_unavailable_during_judgment",
                    criterion_id=criterion_id,
                    trace_id=trace_id,
                )
                judgment_results[criterion_id] = CriterionResult(
                    criterion_id=criterion_id,
                    category=criterion.category,
                    result=CriterionResultEnum.CANNOT_ASSESS,
                    method=EvalMethod.DEGRADED,
                    reason="LLM unavailable - cannot assess",
                )

    finally:
        await llm.close()
        await memory.close()

    elapsed_ms = (time.time() - start_time) * 1000

    logger.info(
        "evaluation_complete",
        judged=len(judgment_results),
        llm_calls=llm_calls,
        partial=partial_evaluation,
        elapsed_ms=round(elapsed_ms, 1),
        trace_id=trace_id,
    )

    return _build_response(
        state, judgment_results, tribunal_justifications, elapsed_ms, existing_stats, partial_evaluation, llm_calls
    )


async def _judge_single_criterion(
    llm: LLMClient,
    criterion: Criterion,
    evidence_metadata: list[EvidenceMetadata],
    tenant_id: str,
    trace_id: str,
    settings: Any,
) -> tuple[CriterionResult, dict[str, Any] | None]:
    """Evaluate a single criterion using tiered LLM judgment.

    Dispatch by criterion weight:
    - >= 0.20: Full Adversarial Tribunal (3 diverse models)
    - 0.10-0.19: Simplified Tribunal (Prosecutor + Judge)
    - < 0.10: Single structured call

    Returns:
        Tuple of (CriterionResult, justification_doc or None).
        justification_doc is populated for tribunal evaluations.
    """
    evidence_text = _extract_relevant_evidence(criterion, evidence_metadata)

    # High-weight: Full tribunal with 3 different model families
    if criterion.weight >= settings.consensus_weight_threshold:
        tribunal_result = await run_tribunal(
            llm=llm,
            criterion=criterion,
            evidence_text=evidence_text or "No relevant evidence text available.",
            tenant_id=tenant_id,
            trace_id=trace_id,
        )

        # Confidence-based escalation: retry if Judge is uncertain
        if (
            tribunal_result.confidence < settings.tribunal_confidence_threshold
            and settings.tribunal_max_retries > 0
        ):
            logger.info(
                "tribunal_low_confidence_retry",
                criterion_id=criterion.id,
                confidence=tribunal_result.confidence,
                trace_id=trace_id,
            )
            retry_result = await run_tribunal(
                llm=llm,
                criterion=criterion,
                evidence_text=evidence_text or "No relevant evidence text available.",
                tenant_id=tenant_id,
                trace_id=f"{trace_id}:retry",
            )

            # If both agree, use that verdict (average confidence)
            if retry_result.verdict == tribunal_result.verdict:
                tribunal_result.confidence = (
                    tribunal_result.confidence + retry_result.confidence
                ) / 2
            # If they disagree, mark as CANNOT_ASSESS
            elif retry_result.confidence > tribunal_result.confidence:
                tribunal_result = retry_result
            else:
                return (
                    CriterionResult(
                        criterion_id=criterion.id,
                        category=criterion.category,
                        result=CriterionResultEnum.CANNOT_ASSESS,
                        method=EvalMethod.LLM_JUDGMENT,
                        reason=(
                            f"Two tribunals disagreed: {tribunal_result.verdict.value} vs "
                            f"{retry_result.verdict.value}. Needs human review."
                        ),
                        confidence=0.0,
                    ),
                    None,
                )

        return tribunal_result.to_criterion_result(criterion.category), tribunal_result.to_justification_doc()

    # Medium-weight: Simplified tribunal (Prosecutor + Judge only)
    if criterion.weight >= 0.10:
        tribunal_result = await run_simplified_tribunal(
            llm=llm,
            criterion=criterion,
            evidence_text=evidence_text or "No relevant evidence text available.",
            tenant_id=tenant_id,
            trace_id=trace_id,
        )
        return tribunal_result.to_criterion_result(criterion.category), tribunal_result.to_justification_doc()

    # Low-weight: Single structured call (cheapest, fastest)
    prompt = JUDGMENT_PROMPT.format(
        criterion_id=criterion.id,
        category=criterion.category,
        question=criterion.question,
        pass_condition=criterion.pass_condition,
        fail_condition=criterion.fail_condition,
        evidence_text=evidence_text if evidence_text else "No relevant evidence text available.",
    )

    response = await llm.complete(
        messages=[{"role": "user", "content": prompt}],
        task="evaluate_control",
        tenant_id=tenant_id,
        trace_id=trace_id,
        temperature=0.0,
        max_tokens=200,
    )

    return _parse_judgment_response(response.content, criterion), None


def _parse_judgment_response(content: str, criterion: Criterion) -> CriterionResult:
    """Parse the LLM's JSON response into a CriterionResult."""
    try:
        # Try to extract JSON from the response
        content_stripped = content.strip()
        if content_stripped.startswith("```"):
            lines = content_stripped.split("\n")
            json_lines = [
                line for line in lines if not line.startswith("```")
            ]
            content_stripped = "\n".join(json_lines)

        data = json.loads(content_stripped)
        result_str = data.get("result", "FAIL").upper()
        reason = data.get("reason", "")

        result_map = {
            "PASS": CriterionResultEnum.PASS,
            "PARTIAL": CriterionResultEnum.PARTIAL,
            "FAIL": CriterionResultEnum.FAIL,
        }

        result = result_map.get(result_str, CriterionResultEnum.FAIL)

        return CriterionResult(
            criterion_id=criterion.id,
            category=criterion.category,
            result=result,
            method=EvalMethod.LLM_JUDGMENT,
            reason=reason,
        )

    except (json.JSONDecodeError, KeyError, TypeError):
        # If we cannot parse, try to extract intent from text
        content_lower = content.lower()
        if "pass" in content_lower:
            result = CriterionResultEnum.PASS
        elif "partial" in content_lower:
            result = CriterionResultEnum.PARTIAL
        else:
            result = CriterionResultEnum.FAIL

        return CriterionResult(
            criterion_id=criterion.id,
            category=criterion.category,
            result=result,
            method=EvalMethod.LLM_JUDGMENT,
            reason=content[:200] if content else "Unable to parse LLM response",
        )


def _extract_relevant_evidence(
    criterion: Criterion,
    evidence_metadata: list[EvidenceMetadata],
) -> str:
    """Extract evidence text relevant to a specific criterion."""
    relevant_parts: list[str] = []

    for meta in evidence_metadata:
        # Match evidence by type
        if criterion.evidence_type == "document" and meta.file_type in (
            "pdf",
            "document",
            "text",
        ):
            if meta.text_content:
                relevant_parts.append(
                    f"[{meta.storage_key}]\n{meta.text_content[:3000]}"
                )

        elif criterion.evidence_type == "structured_data" and meta.file_type in (
            "spreadsheet",
            "csv",
            "json",
        ):
            info_parts = []
            if meta.columns:
                info_parts.append(f"Columns: {', '.join(meta.columns)}")
            if meta.row_count:
                info_parts.append(f"Row count: {meta.row_count}")
            if meta.schema_info:
                info_parts.append(f"Schema: {json.dumps(meta.schema_info)}")
            if info_parts:
                relevant_parts.append(
                    f"[{meta.storage_key}]\n" + "\n".join(info_parts)
                )

        elif criterion.evidence_type == "unstructured":
            if meta.text_content:
                relevant_parts.append(
                    f"[{meta.storage_key}]\n{meta.text_content[:2000]}"
                )

    return "\n\n".join(relevant_parts[:5])  # Limit to 5 evidence pieces


def _build_response(
    state: EvalGraphState,
    judgment_results: dict[str, CriterionResult],
    tribunal_justifications: dict[str, dict[str, Any]],
    elapsed_ms: float,
    existing_stats: LayerStats | None,
    partial_evaluation: bool,
    llm_calls: int,
) -> dict[str, Any]:
    """Build the response dict for this node."""
    existing_timing = state.get("timing")
    timing_dict: dict[str, float] = {}
    if existing_timing is not None:
        timing_dict["discovery_ms"] = existing_timing.discovery_ms
        timing_dict["extraction_ms"] = existing_timing.extraction_ms
        timing_dict["layer1_ms"] = existing_timing.layer1_ms
    timing_dict["layer2_ms"] = elapsed_ms

    stats_dict: dict[str, int] = {}
    if existing_stats is not None:
        stats_dict["layer1_resolved"] = existing_stats.layer1_resolved
        stats_dict["total_criteria"] = existing_stats.total_criteria
    stats_dict["layer2_resolved"] = len(judgment_results)
    stats_dict["llm_calls"] = llm_calls

    return {
        "judgment_results": judgment_results,
        "tribunal_justifications": tribunal_justifications,
        "partial_evaluation": partial_evaluation,
        "timing": TimingStats(**timing_dict),
        "layer_stats": LayerStats(**stats_dict),
    }
