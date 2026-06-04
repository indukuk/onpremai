"""Cross-file join candidate detection.

Analyzes structured files within the same tenant/control prefix to find
columns that could serve as join keys between files. Uses column name
matching and basic type compatibility to score join candidates.
"""

from __future__ import annotations

from typing import Any

import structlog

from src.models import JoinCandidate

logger = structlog.get_logger(__name__)

# Minimum confidence threshold to report a join candidate
_MIN_CONFIDENCE = 0.5

# Column names that are common but not useful joins
_EXCLUDED_COLUMNS = frozenset({
    "id", "row_number", "index", "unnamed: 0", "",
})

# High-confidence join column patterns (domain-specific)
_HIGH_CONFIDENCE_PATTERNS = frozenset({
    "user_id", "employee_id", "account_id", "vendor_id",
    "control_id", "asset_id", "ticket_id", "incident_id",
    "email", "username", "hostname", "ip_address",
})


def detect_joins(
    current_file_key: str,
    current_columns: list[str],
    other_files: list[dict[str, Any]],
) -> list[JoinCandidate]:
    """Detect potential join candidates between the current file and others.

    Compares column names across files to find exact matches that could
    serve as foreign key relationships. Scores based on column name patterns.

    Args:
        current_file_key: Storage key of the file being processed.
        current_columns: Column names from the current file's schema.
        other_files: List of metadata dicts from other files in the same prefix.
            Each must have "file_key" and "sheets" (list with "columns" lists).

    Returns:
        List of JoinCandidate objects sorted by confidence (highest first).
    """
    if not current_columns or not other_files:
        return []

    current_cols_lower = {
        col.lower().strip(): col for col in current_columns
        if col.lower().strip() not in _EXCLUDED_COLUMNS
    }

    candidates: list[JoinCandidate] = []

    for other_meta in other_files:
        other_key = other_meta.get("file_key", "")
        if other_key == current_file_key:
            continue

        other_columns = _extract_columns_from_metadata(other_meta)
        if not other_columns:
            continue

        # Find common columns by name
        other_cols_lower = {
            col.lower().strip(): col for col in other_columns
            if col.lower().strip() not in _EXCLUDED_COLUMNS
        }

        common_cols = set(current_cols_lower.keys()) & set(other_cols_lower.keys())

        for col_name in common_cols:
            confidence = _score_join_confidence(col_name)
            if confidence >= _MIN_CONFIDENCE:
                candidates.append(
                    JoinCandidate(
                        other_file=other_key,
                        join_column=current_cols_lower[col_name],
                        confidence=confidence,
                    )
                )

    # Sort by confidence descending
    candidates.sort(key=lambda c: c.confidence, reverse=True)

    if candidates:
        logger.info(
            "join_candidates_detected",
            file_key=current_file_key,
            candidate_count=len(candidates),
        )

    return candidates


def _extract_columns_from_metadata(metadata: dict[str, Any]) -> list[str]:
    """Extract all column names from a file's metadata.

    Handles both the sheets array format (Excel) and flat columns format (CSV).
    """
    columns: list[str] = []

    sheets = metadata.get("sheets", [])
    for sheet in sheets:
        sheet_cols = sheet.get("columns", [])
        columns.extend(sheet_cols)

    # Fallback: direct columns field
    if not columns:
        direct_cols = metadata.get("columns", [])
        columns.extend(direct_cols)

    return columns


def _score_join_confidence(column_name: str) -> float:
    """Score the confidence that a column match represents a valid join key.

    Higher scores for columns that follow common ID/key naming patterns.
    Lower scores for generic names that might match coincidentally.

    Args:
        column_name: Lowercase column name.

    Returns:
        Confidence score between 0.0 and 1.0.
    """
    # Exact match with known high-confidence patterns
    if column_name in _HIGH_CONFIDENCE_PATTERNS:
        return 0.95

    # Ends with _id (strong foreign key signal)
    if column_name.endswith("_id"):
        return 0.90

    # Contains "id" but not as sole word (e.g., "vendor_identifier")
    if "id" in column_name and column_name != "id":
        return 0.80

    # Contains identifying patterns
    if any(p in column_name for p in ("email", "name", "code", "number", "key")):
        return 0.70

    # Generic column name match - lower confidence
    return 0.55
