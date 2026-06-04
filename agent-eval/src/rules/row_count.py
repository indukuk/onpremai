"""Row count rule check.

Verifies that structured evidence contains at least the minimum
expected number of records. Returns PASS if above threshold, FAIL if below.
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


def check_row_count(
    criterion: Criterion,
    evidence_metadata: list[EvidenceMetadata],
    evidence_files: list[Any],
) -> CriterionResult:
    """Check if structured evidence has at least the minimum required rows.

    Extracts minimum threshold from check_params or pass_condition,
    then sums row counts from structured evidence metadata.
    """
    check_params = criterion.check_params
    pass_condition = criterion.pass_condition.lower()

    # Determine minimum row count
    min_rows = check_params.get("min_rows")
    if min_rows is None:
        min_rows = _extract_min_rows(pass_condition)

    # Default: any records at all means data exists
    if min_rows is None:
        min_rows = 1

    # Sum rows from structured evidence
    total_rows = 0
    matching_files: list[str] = []

    for meta in evidence_metadata:
        if meta.file_type in ("spreadsheet", "csv", "json") and meta.row_count > 0:
            total_rows += meta.row_count
            matching_files.append(meta.storage_key)

    if total_rows == 0 and not matching_files:
        # No structured data found at all
        return CriterionResult(
            criterion_id=criterion.id,
            category=criterion.category,
            result=CriterionResultEnum.FAIL,
            method=EvalMethod.RULE_ROW_COUNT,
            reason="No structured data records found",
        )

    if total_rows >= min_rows:
        return CriterionResult(
            criterion_id=criterion.id,
            category=criterion.category,
            result=CriterionResultEnum.PASS,
            method=EvalMethod.RULE_ROW_COUNT,
            reason=f"{total_rows:,} records found (minimum: {min_rows:,})",
            evidence_used=matching_files[:3],
        )

    return CriterionResult(
        criterion_id=criterion.id,
        category=criterion.category,
        result=CriterionResultEnum.FAIL,
        method=EvalMethod.RULE_ROW_COUNT,
        reason=f"Only {total_rows:,} records found (minimum required: {min_rows:,})",
        evidence_used=matching_files[:3],
    )


def _extract_min_rows(pass_condition: str) -> int | None:
    """Extract minimum row count from pass condition text."""
    # Match patterns like "min: 100", "minimum 50 records", ">= 200"
    patterns = [
        r"min(?:imum)?[:\s]+(\d[\d,]*)",
        r"at\s+least\s+(\d[\d,]*)",
        r">=?\s*(\d[\d,]*)",
        r"(\d[\d,]*)\s*(?:or more|records|rows|entries)",
    ]

    for pattern in patterns:
        match = re.search(pattern, pass_condition)
        if match:
            value_str = match.group(1).replace(",", "")
            try:
                return int(value_str)
            except ValueError:
                continue

    # If "records exist" or "data exists" is mentioned, minimum is 1
    if "exist" in pass_condition or "present" in pass_condition:
        return 1

    return None
