"""Schema presence rule check.

Verifies that required columns/fields exist in structured evidence data.
Returns PASS if all required columns are present, FAIL if missing.
"""

from __future__ import annotations

from typing import Any

from src.models import (
    Criterion,
    CriterionResult,
    CriterionResultEnum,
    EvalMethod,
    EvidenceMetadata,
)


def check_schema_presence(
    criterion: Criterion,
    evidence_metadata: list[EvidenceMetadata],
    evidence_files: list[Any],
) -> CriterionResult:
    """Check if required columns/fields exist in structured evidence.

    Extracts expected column names from check_params or pass_condition,
    then checks if those columns appear in any evidence metadata.
    """
    check_params = criterion.check_params
    pass_condition = criterion.pass_condition.lower()

    # Determine required columns
    required_columns = check_params.get("required_columns", [])
    if not required_columns:
        required_columns = _extract_required_columns(pass_condition)

    if not required_columns:
        return CriterionResult(
            criterion_id=criterion.id,
            category=criterion.category,
            result=CriterionResultEnum.NEEDS_JUDGMENT,
            method=EvalMethod.LLM_JUDGMENT,
            reason="Cannot determine required columns from criterion definition",
        )

    # Collect all columns from structured evidence
    all_columns: set[str] = set()
    matching_files: list[str] = []

    for meta in evidence_metadata:
        if meta.file_type in ("spreadsheet", "csv", "json") and meta.columns:
            normalized_columns = {col.lower().strip() for col in meta.columns}
            all_columns.update(normalized_columns)
            matching_files.append(meta.storage_key)

    if not all_columns:
        return CriterionResult(
            criterion_id=criterion.id,
            category=criterion.category,
            result=CriterionResultEnum.NEEDS_JUDGMENT,
            method=EvalMethod.LLM_JUDGMENT,
            reason="No structured evidence with column information available",
        )

    # Check which required columns are present
    required_normalized = [col.lower().strip() for col in required_columns]
    found: list[str] = []
    missing: list[str] = []

    for col in required_normalized:
        # Allow fuzzy matching (contain check)
        if col in all_columns or any(col in existing for existing in all_columns):
            found.append(col)
        else:
            missing.append(col)

    if not missing:
        return CriterionResult(
            criterion_id=criterion.id,
            category=criterion.category,
            result=CriterionResultEnum.PASS,
            method=EvalMethod.RULE_SCHEMA_PRESENCE,
            reason=f"All {len(required_columns)} required columns present: {', '.join(found)}",
            evidence_used=matching_files[:3],
        )

    if not found:
        return CriterionResult(
            criterion_id=criterion.id,
            category=criterion.category,
            result=CriterionResultEnum.FAIL,
            method=EvalMethod.RULE_SCHEMA_PRESENCE,
            reason=f"Missing all required columns: {', '.join(missing)}",
            evidence_used=matching_files[:3],
        )

    # Some found, some missing
    return CriterionResult(
        criterion_id=criterion.id,
        category=criterion.category,
        result=CriterionResultEnum.FAIL,
        method=EvalMethod.RULE_SCHEMA_PRESENCE,
        reason=f"Missing columns: {', '.join(missing)} (found: {', '.join(found)})",
        evidence_used=matching_files[:3],
    )


def _extract_required_columns(pass_condition: str) -> list[str]:
    """Extract required column names from pass condition text.

    Looks for patterns like 'columns: X, Y, Z present' or
    'contains fields: A, B, C'.
    """
    import re

    # Pattern: "columns: reviewer, date, outcome"
    col_match = re.search(r"columns?[:\s]+([^.]+)", pass_condition)
    if col_match:
        raw = col_match.group(1)
        parts = [p.strip() for p in raw.split(",")]
        return [p for p in parts if p and len(p) < 30]

    # Pattern: keywords commonly required in compliance data
    common_fields = [
        "reviewer",
        "date",
        "outcome",
        "user",
        "action",
        "approval",
        "status",
        "timestamp",
    ]

    found = [field for field in common_fields if field in pass_condition]
    return found
