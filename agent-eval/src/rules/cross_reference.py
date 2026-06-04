"""Cross-reference rule check.

Verifies that a join between two datasets produces expected results.
For example: no terminated users should appear in the active access list.
Returns PASS if zero violations found, FAIL if violations exist,
NEEDS_JUDGMENT if datasets cannot be joined (schema mismatch).
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


def check_cross_reference(
    criterion: Criterion,
    evidence_metadata: list[EvidenceMetadata],
    evidence_files: list[Any],
) -> CriterionResult:
    """Check cross-references between datasets.

    This rule checks if related datasets have the expected relationship.
    Since actual data joining requires code execution (sandbox), this rule
    performs a preliminary check:
    1. Verify both required datasets exist
    2. Verify they share join-compatible columns
    3. If schema check passes, mark as NEEDS_JUDGMENT for sandbox execution

    Full cross-reference analysis happens in the sandbox node.
    """
    check_params = criterion.check_params
    pass_condition = criterion.pass_condition.lower()

    # Identify datasets needed for cross-reference
    source_dataset = check_params.get("source_dataset", "")
    target_dataset = check_params.get("target_dataset", "")
    join_column = check_params.get("join_column", "")

    # Find structured data files
    structured_files: list[EvidenceMetadata] = [
        meta
        for meta in evidence_metadata
        if meta.file_type in ("spreadsheet", "csv", "json") and meta.columns
    ]

    if len(structured_files) < 2:
        # Cross-reference requires at least 2 datasets
        if len(structured_files) == 0:
            return CriterionResult(
                criterion_id=criterion.id,
                category=criterion.category,
                result=CriterionResultEnum.FAIL,
                method=EvalMethod.RULE_CROSS_REFERENCE,
                reason="No structured datasets available for cross-reference",
            )
        return CriterionResult(
            criterion_id=criterion.id,
            category=criterion.category,
            result=CriterionResultEnum.NEEDS_JUDGMENT,
            method=EvalMethod.LLM_JUDGMENT,
            reason="Only one structured dataset found; need at least two for cross-reference",
        )

    # Check if datasets can be joined (share common columns)
    if join_column:
        joinable = _check_joinability_by_column(structured_files, join_column)
    else:
        joinable = _check_joinability_auto(structured_files)

    if not joinable:
        return CriterionResult(
            criterion_id=criterion.id,
            category=criterion.category,
            result=CriterionResultEnum.NEEDS_JUDGMENT,
            method=EvalMethod.LLM_JUDGMENT,
            reason="Datasets exist but cannot determine join compatibility from metadata alone",
        )

    # Check if schema_info contains pre-computed cross-reference results
    for meta in structured_files:
        xref_results = meta.schema_info.get("cross_reference_results")
        if xref_results is not None:
            violations = xref_results.get("violations", 0)
            total_checked = xref_results.get("total_checked", 0)

            if violations == 0:
                return CriterionResult(
                    criterion_id=criterion.id,
                    category=criterion.category,
                    result=CriterionResultEnum.PASS,
                    method=EvalMethod.RULE_CROSS_REFERENCE,
                    reason=f"0 violations found across {total_checked:,} cross-referenced records",
                    evidence_used=[m.storage_key for m in structured_files[:3]],
                )
            else:
                return CriterionResult(
                    criterion_id=criterion.id,
                    category=criterion.category,
                    result=CriterionResultEnum.FAIL,
                    method=EvalMethod.RULE_CROSS_REFERENCE,
                    reason=f"{violations} violation(s) found in {total_checked:,} cross-referenced records",
                    evidence_used=[m.storage_key for m in structured_files[:3]],
                )

    # Datasets exist and appear joinable but need actual execution
    # This will be handled by sandbox node
    return CriterionResult(
        criterion_id=criterion.id,
        category=criterion.category,
        result=CriterionResultEnum.NEEDS_JUDGMENT,
        method=EvalMethod.LLM_JUDGMENT,
        reason="Datasets joinable but cross-reference requires code execution",
        evidence_used=[m.storage_key for m in structured_files[:3]],
    )


def _check_joinability_by_column(
    files: list[EvidenceMetadata],
    join_column: str,
) -> bool:
    """Check if at least 2 files share the specified join column."""
    join_lower = join_column.lower()
    files_with_column = 0

    for meta in files:
        columns_lower = {col.lower() for col in meta.columns}
        if join_lower in columns_lower or any(join_lower in col for col in columns_lower):
            files_with_column += 1

    return files_with_column >= 2


def _check_joinability_auto(files: list[EvidenceMetadata]) -> bool:
    """Auto-detect if files share common columns that could be a join key."""
    if len(files) < 2:
        return False

    # Find columns shared between any two files
    for i in range(len(files)):
        cols_i = {col.lower() for col in files[i].columns}
        for j in range(i + 1, len(files)):
            cols_j = {col.lower() for col in files[j].columns}
            common = cols_i & cols_j
            # Filter out generic columns that are unlikely join keys
            generic = {"id", "date", "timestamp", "created_at", "updated_at", "type", "status"}
            meaningful_common = common - generic
            if meaningful_common:
                return True
            # Even generic columns can be join keys
            if common:
                return True

    return False
