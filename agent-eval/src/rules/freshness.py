"""Freshness rule check.

Verifies that evidence files were updated within a specified time window.
Returns PASS if within threshold, FAIL if stale, NEEDS_JUDGMENT if
the date cannot be parsed reliably.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

from src.models import (
    Criterion,
    CriterionResult,
    CriterionResultEnum,
    EvalMethod,
    EvidenceMetadata,
)


def check_freshness(
    criterion: Criterion,
    evidence_metadata: list[EvidenceMetadata],
    evidence_files: list[Any],
) -> CriterionResult:
    """Check if evidence files are within the required freshness window.

    Extracts the max age from pass_condition or check_params, then
    compares evidence last_modified dates against the threshold.
    """
    check_params = criterion.check_params
    pass_condition = criterion.pass_condition.lower()

    # Determine max age in days
    max_age_days = check_params.get("max_age_days")
    if max_age_days is None:
        max_age_days = _extract_max_age(pass_condition)

    if max_age_days is None:
        return CriterionResult(
            criterion_id=criterion.id,
            category=criterion.category,
            result=CriterionResultEnum.NEEDS_JUDGMENT,
            method=EvalMethod.LLM_JUDGMENT,
            reason="Cannot determine freshness threshold from criterion definition",
        )

    now = datetime.now(timezone.utc)
    threshold_date = now - timedelta(days=max_age_days)

    # Check evidence files
    fresh_files: list[str] = []
    stale_files: list[str] = []

    for ef in evidence_files:
        last_modified = getattr(ef, "last_modified", None)
        if last_modified is None:
            continue

        # Ensure timezone-aware
        if last_modified.tzinfo is None:
            last_modified = last_modified.replace(tzinfo=timezone.utc)

        storage_key = getattr(ef, "storage_key", "unknown")
        if last_modified >= threshold_date:
            fresh_files.append(storage_key)
        else:
            stale_files.append(storage_key)

    # Also check extracted_at from metadata
    for meta in evidence_metadata:
        if meta.extracted_at.tzinfo is None:
            extracted = meta.extracted_at.replace(tzinfo=timezone.utc)
        else:
            extracted = meta.extracted_at

        if extracted >= threshold_date:
            if meta.storage_key not in fresh_files:
                fresh_files.append(meta.storage_key)

    if not fresh_files and not stale_files:
        return CriterionResult(
            criterion_id=criterion.id,
            category=criterion.category,
            result=CriterionResultEnum.NEEDS_JUDGMENT,
            method=EvalMethod.LLM_JUDGMENT,
            reason="Cannot determine file dates for freshness check",
        )

    if fresh_files and not stale_files:
        return CriterionResult(
            criterion_id=criterion.id,
            category=criterion.category,
            result=CriterionResultEnum.PASS,
            method=EvalMethod.RULE_FRESHNESS,
            reason=f"All {len(fresh_files)} file(s) updated within {max_age_days} days",
            evidence_used=fresh_files[:5],
        )

    if stale_files and not fresh_files:
        return CriterionResult(
            criterion_id=criterion.id,
            category=criterion.category,
            result=CriterionResultEnum.FAIL,
            method=EvalMethod.RULE_FRESHNESS,
            reason=f"{len(stale_files)} file(s) exceed {max_age_days}-day freshness threshold",
            evidence_used=stale_files[:5],
        )

    # Mix of fresh and stale
    return CriterionResult(
        criterion_id=criterion.id,
        category=criterion.category,
        result=CriterionResultEnum.NEEDS_JUDGMENT,
        method=EvalMethod.LLM_JUDGMENT,
        reason=f"{len(fresh_files)} fresh, {len(stale_files)} stale - needs judgment on sufficiency",
    )


def _extract_max_age(pass_condition: str) -> int | None:
    """Extract max age in days from pass condition text."""
    # Match patterns like "within 12 months", "reviewed within 365 days"
    month_match = re.search(r"(\d+)\s*months?", pass_condition)
    if month_match:
        months = int(month_match.group(1))
        return months * 30

    day_match = re.search(r"(\d+)\s*days?", pass_condition)
    if day_match:
        return int(day_match.group(1))

    year_match = re.search(r"(\d+)\s*years?", pass_condition)
    if year_match:
        years = int(year_match.group(1))
        return years * 365

    # Common implied thresholds
    if "annual" in pass_condition:
        return 365
    if "quarterly" in pass_condition:
        return 90
    if "monthly" in pass_condition:
        return 30

    return None
