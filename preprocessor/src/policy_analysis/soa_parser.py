"""Parser for Statement of Applicability (SOA) spreadsheets.

Handles SOA documents that have already been processed by the preprocessor's
file ingestion pipeline (Excel/CSV -> metadata with sheet schemas and sample rows).
Extracts control applicability status and justification per control ID.
"""

from __future__ import annotations

import re

import structlog

logger = structlog.get_logger(__name__)

# Common column name patterns for SOA fields
_CONTROL_ID_PATTERNS = re.compile(
    r"^(control[\s_-]?id|control[\s_-]?number|control[\s_-]?ref|"
    r"ref(?:erence)?|id|annex[\s_-]?a[\s_-]?ref|clause|control|"
    r"control[\s_-]?identifier|iso[\s_-]?control)$",
    re.IGNORECASE,
)

_APPLICABLE_PATTERNS = re.compile(
    r"^(applicable|applicability|status|included|in[\s_-]?scope|"
    r"applicable\?|apply|relevant)$",
    re.IGNORECASE,
)

_JUSTIFICATION_PATTERNS = re.compile(
    r"^(justification|reason|rationale|explanation|notes?|"
    r"remarks?|description|comment|exclusion[\s_-]?reason)$",
    re.IGNORECASE,
)

_SCOPE_PATTERNS = re.compile(
    r"^(scope|boundary|department|owner|responsible[\s_-]?party|"
    r"implementation[\s_-]?status|impl[\s_-]?status)$",
    re.IGNORECASE,
)

# Truthy values for applicability
_TRUTHY_VALUES = frozenset({
    "yes", "y", "true", "1", "applicable", "included", "in scope",
    "in-scope", "inscope", "selected", "active", "implemented",
})

_FALSY_VALUES = frozenset({
    "no", "n", "false", "0", "not applicable", "n/a", "na",
    "excluded", "out of scope", "out-of-scope", "not included",
    "not selected", "removed",
})


def _find_column(columns: list[str], pattern: re.Pattern[str]) -> str | None:
    """Find first column name matching a pattern."""
    for col in columns:
        if pattern.match(col.strip()):
            return col
    return None


def _normalize_applicable(value: str) -> bool | None:
    """Normalize an applicability cell value to True/False/None.

    Returns None if the value cannot be determined.
    """
    cleaned = value.strip().lower()
    if cleaned in _TRUTHY_VALUES:
        return True
    if cleaned in _FALSY_VALUES:
        return False
    return None


def _parse_from_sheets(metadata: dict) -> dict[str, dict]:
    """Parse SOA from preprocessor metadata containing sheet schemas.

    Expects metadata["sheets"] to be a list of sheet objects with
    "columns" and "sample_rows" keys.
    """
    sheets = metadata.get("sheets", [])
    if not sheets:
        return {}

    results: dict[str, dict] = {}

    for sheet in sheets:
        columns = sheet.get("columns", [])
        sample_rows = sheet.get("sample_rows", [])

        if not columns or not sample_rows:
            continue

        # Identify relevant columns
        control_id_col = _find_column(columns, _CONTROL_ID_PATTERNS)
        applicable_col = _find_column(columns, _APPLICABLE_PATTERNS)
        justification_col = _find_column(columns, _JUSTIFICATION_PATTERNS)
        scope_col = _find_column(columns, _SCOPE_PATTERNS)

        # Must have at least a control ID column
        if not control_id_col:
            continue

        for row in sample_rows:
            control_id = str(row.get(control_id_col, "")).strip()
            if not control_id:
                continue

            # Parse applicability
            applicable: bool | None = None
            if applicable_col:
                raw_value = str(row.get(applicable_col, "")).strip()
                applicable = _normalize_applicable(raw_value)

            # Parse justification
            justification = ""
            if justification_col:
                justification = str(row.get(justification_col, "")).strip()

            # Parse scope
            scope = ""
            if scope_col:
                scope = str(row.get(scope_col, "")).strip()

            results[control_id] = {
                "applicable": applicable if applicable is not None else True,
                "justification": justification,
                "scope": scope,
            }

    return results


def _parse_from_text(text_content: str) -> dict[str, dict]:
    """Attempt to parse SOA from plain text / CSV content.

    Handles pipe-delimited, tab-delimited, and comma-delimited tables.
    """
    if not text_content or not text_content.strip():
        return {}

    lines = text_content.strip().split("\n")
    if len(lines) < 2:
        return {}

    # Detect delimiter
    first_line = lines[0]
    delimiter: str | None = None
    for delim in ["|", "\t", ","]:
        if delim in first_line:
            delimiter = delim
            break

    if not delimiter:
        return {}

    # Parse header
    headers = [h.strip().strip("|").strip() for h in first_line.split(delimiter)]
    headers = [h for h in headers if h]

    if not headers:
        return {}

    # Find columns
    control_id_col_idx: int | None = None
    applicable_col_idx: int | None = None
    justification_col_idx: int | None = None
    scope_col_idx: int | None = None

    for idx, col in enumerate(headers):
        if control_id_col_idx is None and _CONTROL_ID_PATTERNS.match(col):
            control_id_col_idx = idx
        elif applicable_col_idx is None and _APPLICABLE_PATTERNS.match(col):
            applicable_col_idx = idx
        elif justification_col_idx is None and _JUSTIFICATION_PATTERNS.match(col):
            justification_col_idx = idx
        elif scope_col_idx is None and _SCOPE_PATTERNS.match(col):
            scope_col_idx = idx

    if control_id_col_idx is None:
        return {}

    results: dict[str, dict] = {}

    # Skip header separator lines (e.g., |---|---|)
    data_lines = [
        line for line in lines[1:]
        if line.strip() and not re.match(r"^[\s|:\-+]+$", line.strip())
    ]

    for line in data_lines:
        cells = [c.strip().strip("|").strip() for c in line.split(delimiter)]
        cells = [c for c in cells if c or True]  # Preserve empty cells for indexing

        # Re-split preserving empties
        cells = [c.strip().strip("|").strip() for c in line.split(delimiter)]

        if len(cells) <= control_id_col_idx:
            continue

        control_id = cells[control_id_col_idx].strip()
        if not control_id:
            continue

        applicable: bool | None = None
        if applicable_col_idx is not None and len(cells) > applicable_col_idx:
            applicable = _normalize_applicable(cells[applicable_col_idx])

        justification = ""
        if justification_col_idx is not None and len(cells) > justification_col_idx:
            justification = cells[justification_col_idx].strip()

        scope = ""
        if scope_col_idx is not None and len(cells) > scope_col_idx:
            scope = cells[scope_col_idx].strip()

        results[control_id] = {
            "applicable": applicable if applicable is not None else True,
            "justification": justification,
            "scope": scope,
        }

    return results


def parse_soa(metadata: dict, text_content: str = "") -> dict[str, dict]:
    """Parse a Statement of Applicability into structured control data.

    Accepts preprocessor metadata (with sheet schemas from Excel/CSV processing)
    and optionally raw text content for fallback parsing.

    Args:
        metadata: Preprocessor FileMetadata dict containing "sheets" with
            column names and sample_rows. This is the primary parsing path.
        text_content: Optional raw text content (CSV/pipe-delimited) for
            fallback parsing when metadata doesn't contain sheet data.

    Returns:
        Dict mapping control_id to control info:
        {
            "A.5.1": {
                "applicable": True,
                "justification": "Required for our scope",
                "scope": "IT Department"
            }
        }

        Returns empty dict if unable to parse (graceful degradation).
    """
    # Try structured metadata first (primary path)
    results = _parse_from_sheets(metadata)
    if results:
        logger.info(
            "soa_parsed_from_metadata",
            control_count=len(results),
        )
        return results

    # Fallback: try parsing from text content
    if text_content:
        results = _parse_from_text(text_content)
        if results:
            logger.info(
                "soa_parsed_from_text",
                control_count=len(results),
            )
            return results

    logger.warning("soa_parse_failed", metadata_keys=list(metadata.keys()))
    return {}
