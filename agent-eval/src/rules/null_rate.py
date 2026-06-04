"""Null rate rule check.

Verifies that key columns in structured evidence have a null/empty
percentage below the acceptable threshold. Returns PASS if populated
above threshold, FAIL if too many nulls.
"""

from __future__ import annotations

import re
from typing import Any

from src.models import (
    Criterion,
    CriterionResult,
    CriterionResultEnum,
    EvalMethod,
    EvidenceMetadata,
)


def check_null_rate(
    criterion: Criterion,
    evidence_metadata: list[EvidenceMetadata],
    evidence_files: list[Any],
) -> CriterionResult:
    """Check if key columns meet the minimum populated percentage.

    Extracts the threshold from check_params or pass_condition.
    Uses schema_info from metadata which may contain null_rates.
    """
    check_params = criterion.check_params
    pass_condition = criterion.pass_condition.lower()

    # Determine threshold (as a fraction, e.g., 0.95 means 95% populated)
    min_populated = check_params.get("min_populated_rate")
    if min_populated is None:
        min_populated = _extract_threshold(pass_condition)
    if min_populated is None:
        min_populated = 0.95  # Default: 95% populated

    # Target columns to check
    target_columns = check_params.get("columns", [])
    if not target_columns:
        target_columns = _extract_target_columns(pass_condition)

    # Check schema_info for null rate data
    for meta in evidence_metadata:
        if meta.file_type not in ("spreadsheet", "csv", "json"):
            continue

        schema_info = meta.schema_info
        null_rates = schema_info.get("null_rates", {})

        if null_rates:
            return _evaluate_null_rates(
                criterion=criterion,
                null_rates=null_rates,
                target_columns=target_columns,
                min_populated=min_populated,
                storage_key=meta.storage_key,
            )

        # If we have row_count and columns but no null_rates,
        # we can only check schema presence (defer to NEEDS_JUDGMENT)
        if meta.row_count > 0 and meta.columns:
            # If specific null rates are not available, we cannot determine
            return CriterionResult(
                criterion_id=criterion.id,
                category=criterion.category,
                result=CriterionResultEnum.NEEDS_JUDGMENT,
                method=EvalMethod.LLM_JUDGMENT,
                reason="Structured data exists but null rate statistics not available in metadata",
            )

    # No structured data with null rate info
    return CriterionResult(
        criterion_id=criterion.id,
        category=criterion.category,
        result=CriterionResultEnum.NEEDS_JUDGMENT,
        method=EvalMethod.LLM_JUDGMENT,
        reason="No structured evidence with null rate statistics available",
    )


def _evaluate_null_rates(
    criterion: Criterion,
    null_rates: dict[str, float],
    target_columns: list[str],
    min_populated: float,
    storage_key: str,
) -> CriterionResult:
    """Evaluate null rates against threshold for target columns."""
    # If specific target columns are given, check those
    columns_to_check = target_columns if target_columns else list(null_rates.keys())

    violations: list[str] = []
    passes: list[str] = []

    for col in columns_to_check:
        col_lower = col.lower()
        # Find matching column in null_rates (case-insensitive)
        matched_rate = None
        for null_col, rate in null_rates.items():
            if null_col.lower() == col_lower or col_lower in null_col.lower():
                matched_rate = rate
                break

        if matched_rate is None:
            continue

        populated_rate = 1.0 - matched_rate
        if populated_rate >= min_populated:
            passes.append(f"{col}: {populated_rate*100:.1f}% populated")
        else:
            violations.append(f"{col}: {populated_rate*100:.1f}% populated (need {min_populated*100:.0f}%)")

    if violations:
        return CriterionResult(
            criterion_id=criterion.id,
            category=criterion.category,
            result=CriterionResultEnum.FAIL,
            method=EvalMethod.RULE_NULL_RATE,
            reason=f"Columns below threshold: {'; '.join(violations)}",
            evidence_used=[storage_key],
        )

    if passes:
        return CriterionResult(
            criterion_id=criterion.id,
            category=criterion.category,
            result=CriterionResultEnum.PASS,
            method=EvalMethod.RULE_NULL_RATE,
            reason=f"All checked columns meet threshold: {'; '.join(passes)}",
            evidence_used=[storage_key],
        )

    return CriterionResult(
        criterion_id=criterion.id,
        category=criterion.category,
        result=CriterionResultEnum.NEEDS_JUDGMENT,
        method=EvalMethod.LLM_JUDGMENT,
        reason="Target columns not found in null rate statistics",
    )


def _extract_threshold(pass_condition: str) -> float | None:
    """Extract populated percentage threshold from pass condition."""
    # Match "99%", "95% populated", ">= 90%"
    match = re.search(r"(\d+(?:\.\d+)?)\s*%", pass_condition)
    if match:
        pct = float(match.group(1))
        if pct > 1:
            return pct / 100.0
        return pct
    return None


def _extract_target_columns(pass_condition: str) -> list[str]:
    """Extract target column names from pass condition."""
    # Look for column names mentioned in the pass condition
    # Pattern: "X column" or "X field"
    matches = re.findall(r"(\w+)\s+(?:column|field)", pass_condition)
    return matches
