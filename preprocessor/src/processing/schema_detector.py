"""Schema detection for structured data files.

Infers column types, detects date/ID/numeric columns, extracts sample rows,
and computes row counts. Works with tabular data from Excel, CSV, and JSON.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

import structlog

from src.models import ColumnType, SheetSchema

logger = structlog.get_logger(__name__)

# Patterns for column type detection
_DATE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\d{4}-\d{2}-\d{2}"),  # ISO format
    re.compile(r"\d{2}/\d{2}/\d{4}"),  # US format
    re.compile(r"\d{2}-\d{2}-\d{4}"),  # EU format
    re.compile(r"\d{2}\.\d{2}\.\d{4}"),  # Dotted format
]

_EMAIL_PATTERN = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")

_ID_COLUMN_NAMES = frozenset({
    "id", "user_id", "employee_id", "account_id", "record_id",
    "uuid", "guid", "ref", "reference", "key", "pk",
    "ticket_id", "case_id", "incident_id", "control_id",
})

_DATE_COLUMN_NAMES = frozenset({
    "date", "created_at", "updated_at", "timestamp", "datetime",
    "review_date", "start_date", "end_date", "due_date",
    "created", "modified", "last_login", "expires_at",
})

SAMPLE_ROW_COUNT = 5


def detect_schema(
    columns: list[str],
    rows: list[dict[str, Any]],
    sheet_name: str = "Sheet1",
) -> SheetSchema:
    """Detect schema from column names and sample data.

    Analyzes column values to infer types (string, date, numeric, ID, email, boolean).
    Returns a SheetSchema with column types, sample rows, and row count.

    Args:
        columns: List of column names.
        rows: All data rows as list of dicts.
        sheet_name: Name of the sheet/table.

    Returns:
        SheetSchema with detected types and sample data.
    """
    column_types: dict[str, str] = {}

    for col in columns:
        col_values = [row.get(col) for row in rows[:100] if row.get(col) is not None]
        detected_type = _infer_column_type(col, col_values)
        column_types[col] = detected_type.value

    # Take first N rows as samples
    sample_rows = _sanitize_sample_rows(rows[:SAMPLE_ROW_COUNT], columns)

    return SheetSchema(
        name=sheet_name,
        columns=columns,
        row_count=len(rows),
        sample_rows=sample_rows,
        column_types=column_types,
    )


def _infer_column_type(column_name: str, values: list[Any]) -> ColumnType:
    """Infer the type of a column from its name and sample values.

    Uses a heuristic approach:
    1. Check column name against known patterns (ID, date).
    2. Analyze actual values to determine type.
    """
    col_lower = column_name.lower().strip()

    # Name-based hints
    if col_lower in _ID_COLUMN_NAMES or col_lower.endswith("_id"):
        return ColumnType.ID

    if col_lower in _DATE_COLUMN_NAMES or "date" in col_lower or "time" in col_lower:
        return ColumnType.DATE

    if not values:
        return ColumnType.UNKNOWN

    # Value-based detection
    type_counts: dict[ColumnType, int] = {}

    for val in values[:50]:
        detected = _detect_value_type(val)
        type_counts[detected] = type_counts.get(detected, 0) + 1

    if not type_counts:
        return ColumnType.STRING

    # Return the most common type (majority rules)
    return max(type_counts, key=lambda t: type_counts[t])


def _detect_value_type(value: Any) -> ColumnType:
    """Detect the type of a single value."""
    if value is None:
        return ColumnType.UNKNOWN

    if isinstance(value, bool):
        return ColumnType.BOOLEAN

    if isinstance(value, int):
        return ColumnType.INTEGER

    if isinstance(value, float):
        return ColumnType.FLOAT

    if isinstance(value, datetime):
        return ColumnType.DATE

    # String-based detection
    str_val = str(value).strip()

    if not str_val:
        return ColumnType.UNKNOWN

    # Boolean strings
    if str_val.lower() in ("true", "false", "yes", "no", "y", "n", "1", "0"):
        return ColumnType.BOOLEAN

    # Email
    if _EMAIL_PATTERN.match(str_val):
        return ColumnType.EMAIL

    # Date patterns
    for pattern in _DATE_PATTERNS:
        if pattern.search(str_val):
            return ColumnType.DATE

    # Numeric strings
    try:
        int(str_val)
        return ColumnType.INTEGER
    except (ValueError, TypeError):
        pass

    try:
        float(str_val)
        return ColumnType.FLOAT
    except (ValueError, TypeError):
        pass

    return ColumnType.STRING


def _sanitize_sample_rows(
    rows: list[dict[str, Any]], columns: list[str]
) -> list[dict[str, Any]]:
    """Sanitize sample rows for JSON serialization.

    Ensures all values are JSON-safe (strings, numbers, booleans, None).
    Limits to the declared columns only.
    """
    sanitized: list[dict[str, Any]] = []

    for row in rows:
        clean_row: dict[str, Any] = {}
        for col in columns:
            val = row.get(col)
            if isinstance(val, datetime):
                clean_row[col] = val.isoformat()
            elif isinstance(val, (str, int, float, bool)) or val is None:
                clean_row[col] = val
            else:
                clean_row[col] = str(val)
        sanitized.append(clean_row)

    return sanitized
