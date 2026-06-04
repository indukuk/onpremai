"""Quantitative threshold rule check.

Verifies that calculated metrics meet required thresholds.
For example: "removal SLA max 48h" or "review cadence met quarterly".
Returns PASS if metric meets threshold, FAIL if not.
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


def check_quantitative(
    criterion: Criterion,
    evidence_metadata: list[EvidenceMetadata],
    evidence_files: list[Any],
) -> CriterionResult:
    """Check if quantitative metrics from evidence meet thresholds.

    Looks for pre-computed metrics in schema_info or metadata.
    If raw data is present but metrics need computation, falls back
    to NEEDS_JUDGMENT (sandbox will compute).
    """
    check_params = criterion.check_params
    pass_condition = criterion.pass_condition.lower()

    # Extract threshold from check_params
    metric_name = check_params.get("metric_name", "")
    operator = check_params.get("operator", "<=")  # <=, >=, ==, <, >
    threshold_value = check_params.get("threshold_value")

    if threshold_value is None:
        threshold_value = _extract_threshold(pass_condition)

    # Look for pre-computed metrics in evidence metadata
    for meta in evidence_metadata:
        metrics = meta.schema_info.get("metrics", {})
        computed_stats = meta.schema_info.get("computed_stats", {})
        summary = meta.schema_info.get("summary", {})

        all_metrics = {**metrics, **computed_stats, **summary}

        if not all_metrics:
            continue

        # Try to find a matching metric
        if metric_name:
            actual_value = all_metrics.get(metric_name)
            if actual_value is None:
                # Try fuzzy match
                actual_value = _fuzzy_find_metric(metric_name, all_metrics)
        else:
            # Try to infer metric from pass_condition
            actual_value = _infer_metric_value(pass_condition, all_metrics)

        if actual_value is not None and threshold_value is not None:
            try:
                actual_num = float(actual_value)
                threshold_num = float(threshold_value)
            except (ValueError, TypeError):
                continue

            passes = _compare(actual_num, operator, threshold_num)

            if passes:
                return CriterionResult(
                    criterion_id=criterion.id,
                    category=criterion.category,
                    result=CriterionResultEnum.PASS,
                    method=EvalMethod.RULE_QUANTITATIVE,
                    reason=f"Metric {metric_name or 'value'}: {actual_num} {operator} {threshold_num} (threshold met)",
                    evidence_used=[meta.storage_key],
                )
            else:
                return CriterionResult(
                    criterion_id=criterion.id,
                    category=criterion.category,
                    result=CriterionResultEnum.FAIL,
                    method=EvalMethod.RULE_QUANTITATIVE,
                    reason=f"Metric {metric_name or 'value'}: {actual_num} does not meet threshold {operator} {threshold_num}",
                    evidence_used=[meta.storage_key],
                )

    # No pre-computed metrics found -- need sandbox or LLM
    has_structured_data = any(
        meta.file_type in ("spreadsheet", "csv", "json") and meta.row_count > 0
        for meta in evidence_metadata
    )

    if has_structured_data:
        return CriterionResult(
            criterion_id=criterion.id,
            category=criterion.category,
            result=CriterionResultEnum.NEEDS_JUDGMENT,
            method=EvalMethod.LLM_JUDGMENT,
            reason="Structured data exists but pre-computed metrics not available; needs code execution",
        )

    return CriterionResult(
        criterion_id=criterion.id,
        category=criterion.category,
        result=CriterionResultEnum.NEEDS_JUDGMENT,
        method=EvalMethod.LLM_JUDGMENT,
        reason="No quantitative data available for threshold check",
    )


def _compare(actual: float, operator: str, threshold: float) -> bool:
    """Compare actual value against threshold using the specified operator."""
    ops: dict[str, Any] = {
        "<=": lambda a, t: a <= t,
        ">=": lambda a, t: a >= t,
        "<": lambda a, t: a < t,
        ">": lambda a, t: a > t,
        "==": lambda a, t: abs(a - t) < 0.001,
    }
    comparator = ops.get(operator, ops["<="])
    return comparator(actual, threshold)


def _extract_threshold(pass_condition: str) -> float | None:
    """Extract a numeric threshold from pass condition text."""
    # Patterns: "max 48h", "within 24h", ">= 95%", "< 5%"
    patterns = [
        r"max\s+(\d+(?:\.\d+)?)",
        r"within\s+(\d+(?:\.\d+)?)",
        r"(?:<=?|>=?)\s*(\d+(?:\.\d+)?)",
        r"threshold[:\s]+(\d+(?:\.\d+)?)",
        r"(\d+(?:\.\d+)?)\s*(?:hours?|days?|h\b)",
    ]

    for pattern in patterns:
        match = re.search(pattern, pass_condition)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                continue

    return None


def _fuzzy_find_metric(name: str, metrics: dict[str, Any]) -> Any | None:
    """Find a metric by fuzzy name matching."""
    name_lower = name.lower()
    for key, value in metrics.items():
        if name_lower in key.lower() or key.lower() in name_lower:
            return value
    return None


def _infer_metric_value(
    pass_condition: str,
    metrics: dict[str, Any],
) -> Any | None:
    """Try to infer which metric matches the pass condition."""
    # Common metric keywords
    keyword_map = {
        "sla": ["sla", "time", "duration", "hours", "latency"],
        "rate": ["rate", "percentage", "ratio"],
        "count": ["count", "total", "number"],
        "max": ["max", "maximum", "peak"],
        "avg": ["avg", "average", "mean"],
    }

    for category, keywords in keyword_map.items():
        if any(kw in pass_condition for kw in keywords):
            for metric_key, metric_value in metrics.items():
                if any(kw in metric_key.lower() for kw in keywords):
                    return metric_value

    return None
