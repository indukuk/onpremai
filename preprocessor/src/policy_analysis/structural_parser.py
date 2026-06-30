"""No-LLM structural parser for compliance policy documents.

Parses policy documents into hierarchical sections by detecting numbered headings,
markdown headings, and ALL CAPS headings. Identifies obligation candidates within
sections (clauses containing shall/must/required/mandatory).
"""

from __future__ import annotations

import re
import uuid

from preprocessor.src.policy_analysis.models import PolicySection


# --- Heading detection patterns ---

# Numbered headings: "1.", "1.1", "1.1.1", "A.1", "A.1.2" etc.
_NUMBERED_HEADING_RE = re.compile(
    r"^(?P<number>(?:[A-Z]\.)?(?:\d+\.)+\d*)\s+(?P<title>.+)$"
)

# Markdown headings: # Title, ## Title, ### Title
_MARKDOWN_HEADING_RE = re.compile(
    r"^(?P<hashes>#{1,6})\s+(?P<title>.+)$"
)

# ALL CAPS headings: lines that are entirely uppercase, min 3 chars, no sentence punctuation mid-line
_ALLCAPS_HEADING_RE = re.compile(
    r"^(?P<title>[A-Z][A-Z0-9\s\-&/,():]{2,})$"
)

# Obligation modality keywords
_OBLIGATION_KEYWORDS = re.compile(
    r"\b(shall|must|required\s+to|mandatory|is\s+required)\b",
    re.IGNORECASE,
)

# Frequency patterns
_FREQUENCY_RE = re.compile(
    r"\b(daily|weekly|monthly|quarterly|semi-annually|annually|bi-annually|"
    r"every\s+\d+\s+(?:day|week|month|year)s?)\b",
    re.IGNORECASE,
)


def _generate_id() -> str:
    """Generate a short unique ID for sections."""
    return uuid.uuid4().hex[:12]


def _count_numbered_level(number_str: str) -> int:
    """Determine heading level from a numbered prefix.

    Examples:
        "1." -> 1
        "1.1" -> 2
        "1.1.1" -> 3
        "A.1" -> 2
        "A.1.2" -> 3
    """
    # Strip leading letter prefix (e.g., "A.")
    cleaned = re.sub(r"^[A-Z]\.", "", number_str)
    if not cleaned:
        # Was just "A." — treat as level 1
        return 1
    parts = [p for p in cleaned.split(".") if p]
    return len(parts)


def _detect_heading_style(lines: list[str]) -> str:
    """Detect the dominant heading style in the document.

    Returns: "markdown", "numbered", "allcaps", or "none"
    """
    markdown_count = 0
    numbered_count = 0
    allcaps_count = 0

    # Sample first 200 lines for efficiency
    sample = lines[:200]

    for line in sample:
        stripped = line.strip()
        if not stripped:
            continue
        if _MARKDOWN_HEADING_RE.match(stripped):
            markdown_count += 1
        elif _NUMBERED_HEADING_RE.match(stripped):
            numbered_count += 1
        elif _ALLCAPS_HEADING_RE.match(stripped) and len(stripped) <= 80:
            allcaps_count += 1

    # Return the dominant style
    counts = {
        "markdown": markdown_count,
        "numbered": numbered_count,
        "allcaps": allcaps_count,
    }
    best = max(counts, key=counts.get)  # type: ignore[arg-type]
    if counts[best] == 0:
        return "none"
    return best


def _parse_markdown_headings(lines: list[str]) -> list[dict[str, str | int]]:
    """Extract heading positions using markdown heading syntax."""
    headings: list[dict[str, str | int]] = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        match = _MARKDOWN_HEADING_RE.match(stripped)
        if match:
            level = len(match.group("hashes"))
            title = match.group("title").strip()
            headings.append({"line": i, "level": level, "title": title})
    return headings


def _parse_numbered_headings(lines: list[str]) -> list[dict[str, str | int]]:
    """Extract heading positions using numbered heading syntax."""
    headings: list[dict[str, str | int]] = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        match = _NUMBERED_HEADING_RE.match(stripped)
        if match:
            number = match.group("number")
            title = match.group("title").strip()
            level = _count_numbered_level(number)
            # Use number + title as the heading text
            headings.append({"line": i, "level": level, "title": f"{number} {title}"})
    return headings


def _parse_allcaps_headings(lines: list[str]) -> list[dict[str, str | int]]:
    """Extract heading positions using ALL CAPS heading detection."""
    headings: list[dict[str, str | int]] = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or len(stripped) < 3 or len(stripped) > 80:
            continue
        match = _ALLCAPS_HEADING_RE.match(stripped)
        if match:
            title = match.group("title").strip()
            # All caps headings are always level 1 (no hierarchy signal)
            headings.append({"line": i, "level": 1, "title": title})
    return headings


def _build_sections(
    lines: list[str],
    headings: list[dict[str, str | int]],
) -> list[PolicySection]:
    """Build PolicySection list from detected headings and content between them."""
    if not headings:
        # Fallback: entire document is one section
        full_text = "\n".join(lines).strip()
        if not full_text:
            return []
        return [
            PolicySection(
                section_id=_generate_id(),
                heading="Document",
                level=1,
                content=full_text,
                parent_id=None,
            )
        ]

    sections: list[PolicySection] = []
    # Track parent stack for hierarchy: list of (section_id, level)
    parent_stack: list[tuple[str, int]] = []

    for idx, heading in enumerate(headings):
        heading_line = int(heading["line"])
        level = int(heading["level"])
        title = str(heading["title"])

        # Content is everything between this heading and the next
        if idx + 1 < len(headings):
            next_line = int(headings[idx + 1]["line"])
        else:
            next_line = len(lines)

        # Content starts on the line after the heading
        content_lines = lines[heading_line + 1 : next_line]
        content = "\n".join(content_lines).strip()

        section_id = _generate_id()

        # Determine parent
        # Pop stack entries that are at same level or deeper
        while parent_stack and parent_stack[-1][1] >= level:
            parent_stack.pop()

        parent_id = parent_stack[-1][0] if parent_stack else None

        sections.append(
            PolicySection(
                section_id=section_id,
                heading=title,
                level=level,
                content=content,
                parent_id=parent_id,
            )
        )

        # Push onto stack
        parent_stack.append((section_id, level))

    return sections


def _detect_obligations_in_section(section: PolicySection) -> list[str]:
    """Find lines in a section's content that contain obligation keywords.

    Returns the raw text of each obligation candidate line.
    """
    candidates: list[str] = []
    for line in section.content.split("\n"):
        stripped = line.strip()
        if stripped and _OBLIGATION_KEYWORDS.search(stripped):
            candidates.append(stripped)
    return candidates


def parse_document(text: str, filename: str = "") -> list[PolicySection]:
    """Parse a policy document into hierarchical sections.

    Detects the dominant heading style (markdown, numbered, or ALL CAPS) and
    splits the document into PolicySection objects preserving hierarchy.

    Args:
        text: Full text content of the policy document.
        filename: Optional filename for context (unused in parsing logic).

    Returns:
        List of PolicySection objects representing the document structure.
        If no headings are detected, returns a single section containing the
        entire document.
    """
    if not text or not text.strip():
        return []

    lines = text.split("\n")
    style = _detect_heading_style(lines)

    if style == "markdown":
        headings = _parse_markdown_headings(lines)
    elif style == "numbered":
        headings = _parse_numbered_headings(lines)
    elif style == "allcaps":
        headings = _parse_allcaps_headings(lines)
    else:
        headings = []

    sections = _build_sections(lines, headings)
    return sections


def extract_obligation_candidates(sections: list[PolicySection]) -> list[dict[str, str]]:
    """Extract obligation candidate sentences from parsed sections.

    Scans section content for lines containing normative keywords
    (shall, must, required, mandatory).

    Args:
        sections: List of PolicySection objects from parse_document().

    Returns:
        List of dicts with keys: "text", "section_id", "modality", "frequency".
    """
    candidates: list[dict[str, str]] = []

    for section in sections:
        obligation_lines = _detect_obligations_in_section(section)
        for line in obligation_lines:
            # Detect modality
            modality = "must"  # default
            lower_line = line.lower()
            if "shall" in lower_line:
                modality = "shall"
            elif "must" in lower_line:
                modality = "must"
            elif "should" in lower_line:
                modality = "should"
            elif "may" in lower_line:
                modality = "may"

            # Detect frequency
            freq_match = _FREQUENCY_RE.search(line)
            frequency = freq_match.group(0).lower() if freq_match else ""

            candidates.append({
                "text": line,
                "section_id": section.section_id,
                "modality": modality,
                "frequency": frequency,
            })

    return candidates
