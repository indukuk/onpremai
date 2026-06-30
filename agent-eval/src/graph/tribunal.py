"""Adversarial Tribunal: multi-model debate for high-weight criteria.

Uses 3 different LLM roles with distinct model families to evaluate
compliance criteria through structured adversarial argumentation:

- Prosecutor (fast tier): finds ALL reasons evidence FAILS
- Defender (mid tier, different model family): finds ALL reasons evidence PASSES
- Judge (strong tier): weighs both arguments, delivers verdict

Research basis:
- Du et al. 2023: multi-agent debate improves accuracy 7-16pp
- DEI 2025: heterogeneous ensembles outperform homogeneous by 124%
- PoLL 2024: diverse model panels outperform single large judge, 7x cheaper
- Wang et al. 2024 (MoA): heterogeneous configs consistently beat homogeneous

Tier selection ensures model diversity (different providers/sizes per role)
so errors are uncorrelated — the Prosecutor's blind spots differ from
the Defender's, and the Judge synthesizes rather than averaging.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import structlog

from common.clients import LLMClient
from common.errors import LLMCreditExhaustedError, LLMUnavailableError
from src.models import (
    Criterion,
    CriterionResult,
    CriterionResultEnum,
    EvalMethod,
)

logger = structlog.get_logger(__name__)


PROSECUTOR_PROMPT = """You are a strict compliance prosecutor.
Your ONLY job: find reasons this evidence FAILS criterion {criterion_id}.

## Criterion
Question: {question}
Category: {category}
Fail conditions: {fail_condition}

## Evidence
{evidence_text}

## Rules
- Be specific. Cite exact gaps, missing elements, or weaknesses.
- If the evidence is genuinely strong, say "No material weaknesses found" but still note minor concerns.
- Do NOT consider whether it passes. Only look for failures.
- Output 3-5 bullet points.

Respond in JSON:
{{"arguments": ["point 1", "point 2", ...], "severity": "high" | "medium" | "low"}}"""


DEFENDER_PROMPT = """You are a compliance defense advocate.
Your ONLY job: find reasons this evidence SATISFIES criterion {criterion_id}.

## Criterion
Question: {question}
Category: {category}
Pass conditions: {pass_condition}

## Evidence
{evidence_text}

## Rules
- Be specific. Cite exact elements that satisfy requirements.
- If the evidence is genuinely weak, say "Limited supporting evidence" but still note any partial compliance.
- Do NOT consider whether it fails. Only look for passes.
- Output 3-5 bullet points.

Respond in JSON:
{{"arguments": ["point 1", "point 2", ...], "strength": "high" | "medium" | "low"}}"""


JUDGE_PROMPT = """You are an impartial compliance judge. You have heard both sides.

## Criterion
ID: {criterion_id}
Question: {question}
Category: {category}
Weight: {weight}

## Pass Condition
{pass_condition}

## Fail Condition
{fail_condition}

## PROSECUTION ARGUMENT (reasons to FAIL)
{prosecution_argument}

## DEFENSE ARGUMENT (reasons to PASS)
{defense_argument}

## YOUR TASK
1. Identify which prosecution points are valid vs. overstated
2. Identify which defense points are valid vs. overstated
3. Deliver verdict: PASS, PARTIAL, or FAIL
4. Write justification (2-3 sentences) citing the decisive factors
5. Rate your confidence (0.0-1.0)

Respond in JSON:
{{"verdict": "PASS" | "PARTIAL" | "FAIL", "prosecution_points_accepted": ["..."], "prosecution_points_rejected": ["..."], "defense_points_accepted": ["..."], "defense_points_rejected": ["..."], "justification": "2-3 sentences", "confidence": 0.0}}"""


class TribunalResult:
    """Result from a full tribunal evaluation."""

    def __init__(
        self,
        criterion_id: str,
        verdict: CriterionResultEnum,
        confidence: float,
        justification: str,
        prosecution_args: list[str],
        defense_args: list[str],
        prosecution_accepted: list[str],
        prosecution_rejected: list[str],
        defense_accepted: list[str],
        defense_rejected: list[str],
    ) -> None:
        self.criterion_id = criterion_id
        self.verdict = verdict
        self.confidence = confidence
        self.justification = justification
        self.prosecution_args = prosecution_args
        self.defense_args = defense_args
        self.prosecution_accepted = prosecution_accepted
        self.prosecution_rejected = prosecution_rejected
        self.defense_accepted = defense_accepted
        self.defense_rejected = defense_rejected

    def to_criterion_result(self, category: str) -> CriterionResult:
        """Convert to CriterionResult for the pipeline."""
        return CriterionResult(
            criterion_id=self.criterion_id,
            category=category,
            result=self.verdict,
            method=EvalMethod.LLM_JUDGMENT,
            reason=self.justification,
            confidence=self.confidence,
        )

    def to_justification_doc(self) -> dict[str, Any]:
        """Export full tribunal reasoning for justification storage."""
        return {
            "method": "tribunal:adversarial",
            "criterion_id": self.criterion_id,
            "verdict": self.verdict.value,
            "confidence": self.confidence,
            "prosecution": self.prosecution_args,
            "defense": self.defense_args,
            "judge_reasoning": {
                "prosecution_points_accepted": self.prosecution_accepted,
                "prosecution_points_rejected": self.prosecution_rejected,
                "defense_points_accepted": self.defense_accepted,
                "defense_points_rejected": self.defense_rejected,
                "justification": self.justification,
            },
        }


async def run_tribunal(
    llm: LLMClient,
    criterion: Criterion,
    evidence_text: str,
    tenant_id: str,
    trace_id: str,
) -> TribunalResult:
    """Run full adversarial tribunal (3 calls: Prosecutor + Defender + Judge).

    Each role uses a different LLM task routed to a different model tier/family,
    ensuring error decorrelation through model diversity.
    """
    call_trace = f"{trace_id}:tribunal:{criterion.id}"

    # Phase 1: Prosecutor (fast tier — finds failures)
    prosecution_args = await _run_prosecutor(
        llm=llm,
        criterion=criterion,
        evidence_text=evidence_text,
        tenant_id=tenant_id,
        trace_id=call_trace,
    )

    # Phase 2: Defender (mid tier, different model family — finds passes)
    defense_args = await _run_defender(
        llm=llm,
        criterion=criterion,
        evidence_text=evidence_text,
        tenant_id=tenant_id,
        trace_id=call_trace,
    )

    # Phase 3: Judge (strong tier — weighs arguments, delivers verdict)
    judge_result = await _run_judge(
        llm=llm,
        criterion=criterion,
        prosecution_args=prosecution_args,
        defense_args=defense_args,
        tenant_id=tenant_id,
        trace_id=call_trace,
    )

    logger.info(
        "tribunal_complete",
        criterion_id=criterion.id,
        verdict=judge_result.verdict.value,
        confidence=judge_result.confidence,
        prosecution_points=len(prosecution_args),
        defense_points=len(defense_args),
        trace_id=trace_id,
    )

    return judge_result


async def run_simplified_tribunal(
    llm: LLMClient,
    criterion: Criterion,
    evidence_text: str,
    tenant_id: str,
    trace_id: str,
) -> TribunalResult:
    """Run simplified tribunal (2 calls: Prosecutor + Judge).

    For medium-weight criteria (0.10-0.19). The Judge prompt includes
    implicit defense reasoning.
    """
    call_trace = f"{trace_id}:tribunal_simple:{criterion.id}"

    prosecution_args = await _run_prosecutor(
        llm=llm,
        criterion=criterion,
        evidence_text=evidence_text,
        tenant_id=tenant_id,
        trace_id=call_trace,
    )

    # Judge also considers defense implicitly
    judge_result = await _run_judge(
        llm=llm,
        criterion=criterion,
        prosecution_args=prosecution_args,
        defense_args=["(Defense not called — Judge considers both sides)"],
        tenant_id=tenant_id,
        trace_id=call_trace,
    )

    return judge_result


async def _run_prosecutor(
    llm: LLMClient,
    criterion: Criterion,
    evidence_text: str,
    tenant_id: str,
    trace_id: str,
) -> list[str]:
    """Prosecutor: find all reasons evidence FAILS."""
    prompt = PROSECUTOR_PROMPT.format(
        criterion_id=criterion.id,
        question=criterion.question,
        category=criterion.category,
        fail_condition=criterion.fail_condition,
        evidence_text=evidence_text or "No evidence provided.",
    )

    response = await llm.complete(
        messages=[{"role": "user", "content": prompt}],
        task="evaluate_prosecute",
        tenant_id=tenant_id,
        trace_id=trace_id,
        temperature=0.0,
        max_tokens=500,
    )

    return _parse_arguments(response.content)


async def _run_defender(
    llm: LLMClient,
    criterion: Criterion,
    evidence_text: str,
    tenant_id: str,
    trace_id: str,
) -> list[str]:
    """Defender: find all reasons evidence PASSES."""
    prompt = DEFENDER_PROMPT.format(
        criterion_id=criterion.id,
        question=criterion.question,
        category=criterion.category,
        pass_condition=criterion.pass_condition,
        evidence_text=evidence_text or "No evidence provided.",
    )

    response = await llm.complete(
        messages=[{"role": "user", "content": prompt}],
        task="evaluate_defend",
        tenant_id=tenant_id,
        trace_id=trace_id,
        temperature=0.0,
        max_tokens=500,
    )

    return _parse_arguments(response.content)


async def _run_judge(
    llm: LLMClient,
    criterion: Criterion,
    prosecution_args: list[str],
    defense_args: list[str],
    tenant_id: str,
    trace_id: str,
) -> TribunalResult:
    """Judge: weigh arguments and deliver verdict."""
    prosecution_text = "\n".join(f"- {arg}" for arg in prosecution_args)
    defense_text = "\n".join(f"- {arg}" for arg in defense_args)

    prompt = JUDGE_PROMPT.format(
        criterion_id=criterion.id,
        question=criterion.question,
        category=criterion.category,
        weight=criterion.weight,
        pass_condition=criterion.pass_condition,
        fail_condition=criterion.fail_condition,
        prosecution_argument=prosecution_text or "No prosecution arguments.",
        defense_argument=defense_text or "No defense arguments.",
    )

    response = await llm.complete(
        messages=[{"role": "user", "content": prompt}],
        task="evaluate_judge",
        tenant_id=tenant_id,
        trace_id=trace_id,
        temperature=0.0,
        max_tokens=600,
    )

    return _parse_judge_response(
        response.content,
        criterion.id,
        prosecution_args,
        defense_args,
    )


def _parse_arguments(content: str) -> list[str]:
    """Parse prosecutor/defender response into argument list."""
    content = _strip_markdown_fences(content)

    try:
        data = json.loads(content)
        return data.get("arguments", [])
    except (json.JSONDecodeError, TypeError):
        # Fallback: split by bullet points
        lines = [
            line.strip().lstrip("- •*")
            for line in content.split("\n")
            if line.strip() and line.strip()[0] in "-•*"
        ]
        return lines if lines else [content[:300]]


def _parse_judge_response(
    content: str,
    criterion_id: str,
    prosecution_args: list[str],
    defense_args: list[str],
) -> TribunalResult:
    """Parse judge response into TribunalResult."""
    content = _strip_markdown_fences(content)

    verdict_map = {
        "PASS": CriterionResultEnum.PASS,
        "PARTIAL": CriterionResultEnum.PARTIAL,
        "FAIL": CriterionResultEnum.FAIL,
    }

    try:
        data = json.loads(content)

        verdict_str = data.get("verdict", "FAIL").upper()
        verdict = verdict_map.get(verdict_str, CriterionResultEnum.FAIL)
        confidence = min(1.0, max(0.0, float(data.get("confidence", 0.5))))
        justification = data.get("justification", "")

        return TribunalResult(
            criterion_id=criterion_id,
            verdict=verdict,
            confidence=confidence,
            justification=justification,
            prosecution_args=prosecution_args,
            defense_args=defense_args,
            prosecution_accepted=data.get("prosecution_points_accepted", []),
            prosecution_rejected=data.get("prosecution_points_rejected", []),
            defense_accepted=data.get("defense_points_accepted", []),
            defense_rejected=data.get("defense_points_rejected", []),
        )

    except (json.JSONDecodeError, TypeError, ValueError):
        # Fallback: extract verdict from text
        content_lower = content.lower()
        if "pass" in content_lower:
            verdict = CriterionResultEnum.PASS
        elif "partial" in content_lower:
            verdict = CriterionResultEnum.PARTIAL
        else:
            verdict = CriterionResultEnum.FAIL

        return TribunalResult(
            criterion_id=criterion_id,
            verdict=verdict,
            confidence=0.5,
            justification=content[:200],
            prosecution_args=prosecution_args,
            defense_args=defense_args,
            prosecution_accepted=[],
            prosecution_rejected=[],
            defense_accepted=[],
            defense_rejected=[],
        )


def _strip_markdown_fences(content: str) -> str:
    """Strip markdown code fences from LLM response."""
    content = content.strip()
    if content.startswith("```"):
        lines = content.split("\n")
        json_lines = [line for line in lines if not line.startswith("```")]
        content = "\n".join(json_lines).strip()
    return content
