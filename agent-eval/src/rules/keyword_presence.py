"""Keyword presence rule check.

Verifies that required keywords or phrases appear in document text.
Returns PASS if all required terms found, FAIL if none found,
NEEDS_JUDGMENT if only some found (partial match needs context).
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


def check_keyword_presence(
    criterion: Criterion,
    evidence_metadata: list[EvidenceMetadata],
    evidence_files: list[Any],
) -> CriterionResult:
    """Check if required keywords/phrases appear in evidence text.

    Extracts required terms from check_params or pass_condition,
    then searches through text content of relevant evidence files.
    """
    check_params = criterion.check_params
    pass_condition = criterion.pass_condition

    # Determine required keywords
    required_keywords = check_params.get("keywords", [])
    if not required_keywords:
        required_keywords = _extract_keywords(pass_condition)

    if not required_keywords:
        return CriterionResult(
            criterion_id=criterion.id,
            category=criterion.category,
            result=CriterionResultEnum.NEEDS_JUDGMENT,
            method=EvalMethod.LLM_JUDGMENT,
            reason="Cannot extract required keywords from criterion definition",
        )

    # Collect text content from document-type evidence
    all_text = ""
    relevant_files: list[str] = []

    for meta in evidence_metadata:
        if meta.text_content:
            all_text += " " + meta.text_content
            relevant_files.append(meta.storage_key)

    if not all_text.strip():
        return CriterionResult(
            criterion_id=criterion.id,
            category=criterion.category,
            result=CriterionResultEnum.NEEDS_JUDGMENT,
            method=EvalMethod.LLM_JUDGMENT,
            reason="No text content available in evidence for keyword search",
        )

    # Search for keywords (case-insensitive)
    all_text_lower = all_text.lower()
    found_keywords: list[str] = []
    missing_keywords: list[str] = []

    for keyword in required_keywords:
        keyword_lower = keyword.lower()
        # Use word boundary matching for single words, substring for phrases
        if " " in keyword_lower:
            # Phrase match
            if keyword_lower in all_text_lower:
                found_keywords.append(keyword)
            else:
                missing_keywords.append(keyword)
        else:
            # Word boundary match
            pattern = r"\b" + re.escape(keyword_lower) + r"\b"
            if re.search(pattern, all_text_lower):
                found_keywords.append(keyword)
            else:
                missing_keywords.append(keyword)

    # Determine result
    total = len(required_keywords)
    found_count = len(found_keywords)

    if found_count == total:
        return CriterionResult(
            criterion_id=criterion.id,
            category=criterion.category,
            result=CriterionResultEnum.PASS,
            method=EvalMethod.RULE_KEYWORD_PRESENCE,
            reason=f"All {total} required terms found: {', '.join(found_keywords)}",
            evidence_used=relevant_files[:3],
        )

    if found_count == 0:
        return CriterionResult(
            criterion_id=criterion.id,
            category=criterion.category,
            result=CriterionResultEnum.FAIL,
            method=EvalMethod.RULE_KEYWORD_PRESENCE,
            reason=f"None of {total} required terms found. Missing: {', '.join(missing_keywords)}",
            evidence_used=relevant_files[:3],
        )

    # Partial match -- need LLM to determine if context covers the concept
    return CriterionResult(
        criterion_id=criterion.id,
        category=criterion.category,
        result=CriterionResultEnum.NEEDS_JUDGMENT,
        method=EvalMethod.LLM_JUDGMENT,
        reason=f"Found {found_count}/{total} terms. Missing: {', '.join(missing_keywords)}. LLM to check if concepts are covered by synonyms.",
        evidence_used=relevant_files[:3],
    )


def _extract_keywords(pass_condition: str) -> list[str]:
    """Extract required keywords from the pass condition text.

    Looks for quoted terms, comma-separated lists, and compliance-specific
    vocabulary in the pass condition.
    """
    keywords: list[str] = []

    # Extract quoted terms first
    quoted = re.findall(r"['\"]([^'\"]+)['\"]", pass_condition)
    keywords.extend(quoted)

    # Look for "covers X, Y, Z" pattern
    covers_match = re.search(
        r"(?:covers|mentions|includes|addresses|contains)\s+(.+?)(?:\.|$)",
        pass_condition,
        re.IGNORECASE,
    )
    if covers_match:
        items_text = covers_match.group(1)
        # Split by comma or "and"
        items = re.split(r",\s*|\s+and\s+", items_text)
        for item in items:
            item = item.strip()
            if item and len(item) > 2 and item not in keywords:
                keywords.append(item)

    # If still no keywords, look for compliance-specific terms in the condition
    if not keywords:
        compliance_terms = [
            "provisioning",
            "de-provisioning",
            "least privilege",
            "review cadence",
            "periodic review",
            "access control",
            "multi-factor",
            "mfa",
            "encryption",
            "audit trail",
            "segregation of duties",
            "change management",
            "incident response",
            "backup",
            "recovery",
            "monitoring",
            "logging",
        ]
        condition_lower = pass_condition.lower()
        for term in compliance_terms:
            if term in condition_lower:
                keywords.append(term)

    return keywords
