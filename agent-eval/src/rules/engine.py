"""Rule dispatch engine.

Maps check_type strings to handler functions and dispatches evaluation
to the appropriate rule implementation.
"""

from __future__ import annotations

from typing import Any, Callable

from src.models import (
    Criterion,
    CriterionResult,
    CriterionResultEnum,
    EvalMethod,
    EvidenceMetadata,
)
from src.rules.cross_reference import check_cross_reference
from src.rules.file_existence import check_file_existence
from src.rules.freshness import check_freshness
from src.rules.keyword_presence import check_keyword_presence
from src.rules.null_rate import check_null_rate
from src.rules.quantitative import check_quantitative
from src.rules.row_count import check_row_count
from src.rules.schema_presence import check_schema_presence

# Registry mapping check_type -> handler function
RULE_HANDLERS: dict[
    str,
    Callable[
        [Criterion, list[EvidenceMetadata], list[Any]],
        CriterionResult,
    ],
] = {
    "file_existence": check_file_existence,
    "freshness": check_freshness,
    "schema_presence": check_schema_presence,
    "row_count": check_row_count,
    "null_rate": check_null_rate,
    "cross_reference": check_cross_reference,
    "quantitative": check_quantitative,
    "keyword_presence": check_keyword_presence,
}


def dispatch_rule(
    check_type: str,
    criterion: Criterion,
    evidence_metadata: list[EvidenceMetadata],
    evidence_files: list[Any],
) -> CriterionResult:
    """Dispatch a criterion to the appropriate rule handler.

    Args:
        check_type: The type of rule check to perform.
        criterion: The criterion to evaluate.
        evidence_metadata: Metadata extracted from evidence files.
        evidence_files: Raw evidence file info.

    Returns:
        CriterionResult with PASS, FAIL, or NEEDS_JUDGMENT.
    """
    handler = RULE_HANDLERS.get(check_type)

    if handler is None:
        return CriterionResult(
            criterion_id=criterion.id,
            category=criterion.category,
            result=CriterionResultEnum.NEEDS_JUDGMENT,
            method=EvalMethod.LLM_JUDGMENT,
            reason=f"No rule handler for check_type: {check_type}",
        )

    try:
        return handler(criterion, evidence_metadata, evidence_files)
    except Exception as exc:
        # If a rule fails unexpectedly, fall through to LLM
        return CriterionResult(
            criterion_id=criterion.id,
            category=criterion.category,
            result=CriterionResultEnum.NEEDS_JUDGMENT,
            method=EvalMethod.LLM_JUDGMENT,
            reason=f"Rule execution error: {type(exc).__name__}: {exc}",
        )
