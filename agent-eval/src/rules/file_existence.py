"""File existence rule check.

Verifies that an evidence file matching the expected type/name pattern
exists in the discovered evidence. Returns PASS if found, FAIL if not.
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


def check_file_existence(
    criterion: Criterion,
    evidence_metadata: list[EvidenceMetadata],
    evidence_files: list[Any],
) -> CriterionResult:
    """Check if a file matching the criterion's requirements exists.

    Looks for files matching the evidence type (document, structured_data)
    and optional name patterns from check_params or pass_condition.
    """
    expected_type = criterion.evidence_type.lower()
    pass_condition = criterion.pass_condition.lower()
    check_params = criterion.check_params

    # Extract name pattern from check_params or pass_condition
    name_pattern = check_params.get("name_pattern", "")
    if not name_pattern:
        # Try to extract keywords from pass_condition
        name_pattern = _extract_name_hint(pass_condition)

    # Map evidence types to file types
    type_mapping: dict[str, list[str]] = {
        "document": ["pdf", "document", "text"],
        "structured_data": ["spreadsheet", "csv", "json"],
        "unstructured": ["pdf", "document", "text", "image"],
    }

    acceptable_types = type_mapping.get(expected_type, [])

    # Search for matching files
    matching_files: list[str] = []
    for meta in evidence_metadata:
        if not acceptable_types or meta.file_type in acceptable_types:
            if name_pattern:
                filename_lower = meta.storage_key.lower()
                if re.search(name_pattern, filename_lower):
                    matching_files.append(meta.storage_key)
            else:
                matching_files.append(meta.storage_key)

    # Also check evidence_files if metadata doesn't cover them
    if not matching_files and evidence_files:
        for ef in evidence_files:
            file_type = getattr(ef, "file_type", "")
            storage_key = getattr(ef, "storage_key", "")
            if not acceptable_types or file_type in acceptable_types:
                if name_pattern:
                    if re.search(name_pattern, storage_key.lower()):
                        matching_files.append(storage_key)
                else:
                    matching_files.append(storage_key)

    if matching_files:
        return CriterionResult(
            criterion_id=criterion.id,
            category=criterion.category,
            result=CriterionResultEnum.PASS,
            method=EvalMethod.RULE_FILE_EXISTENCE,
            reason=f"Found {len(matching_files)} matching file(s): {', '.join(matching_files[:3])}",
            evidence_used=matching_files[:5],
        )

    return CriterionResult(
        criterion_id=criterion.id,
        category=criterion.category,
        result=CriterionResultEnum.FAIL,
        method=EvalMethod.RULE_FILE_EXISTENCE,
        reason=f"No file matching type '{expected_type}' found"
        + (f" with pattern '{name_pattern}'" if name_pattern else ""),
    )


def _extract_name_hint(pass_condition: str) -> str:
    """Extract a name pattern hint from the pass condition text."""
    # Common patterns in pass conditions
    keywords = [
        "policy",
        "procedure",
        "access",
        "review",
        "termination",
        "monitoring",
        "audit",
        "log",
        "certificate",
        "report",
    ]

    found: list[str] = []
    for keyword in keywords:
        if keyword in pass_condition:
            found.append(keyword)

    if found:
        # Build a regex pattern matching any of the found keywords
        return "|".join(found[:3])

    return ""
