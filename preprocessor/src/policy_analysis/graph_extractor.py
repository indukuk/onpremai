"""LLM-based entity and relationship extraction from policy sections.

Uses the LLM Gateway to extract obligations, roles, defined terms,
thresholds, and control references from each policy section, then
assembles them into a PolicyGraph structure.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import structlog

from common.clients import LLMClient
from common.errors import LLMCreditExhaustedError, LLMUnavailableError

from src.policy_analysis.models import (
    PolicyEntity,
    PolicyGraph,
    PolicyRelationship,
)

logger = structlog.get_logger(__name__)

# Maximum characters per section content sent to LLM in one call.
_MAX_SECTION_CHARS = 4000

_EXTRACTION_PROMPT = """Extract compliance obligations and entities from this policy section.

Section: {section_heading} (from {document_name})
Content:
{section_content}

Extract:
1. Obligations: statements with SHALL/MUST/REQUIRED (who must do what, with what threshold/frequency)
2. Defined terms: capitalized terms with specific meaning
3. Roles: who is responsible
4. Thresholds: SLAs, frequencies, deadlines, numeric requirements
5. Control references: any framework control IDs mentioned (CC6.1, A.9.2, etc.)

Respond in JSON:
{{"obligations": [{{"text": "...", "subject": "...", "action": "...", "threshold": "...", "frequency": "..."}}], "terms": [{{"term": "...", "definition": "..."}}], "roles": ["..."], "thresholds": [{{"metric": "...", "value": "...", "unit": "..."}}], "control_refs": ["..."]}}"""


class GraphExtractor:
    """Extracts entities and relationships from policy sections via LLM.

    For each section in the document, sends the content to the LLM Gateway
    with the task ``extract_policy_obligations``. Extracted items are assembled
    into a PolicyGraph with typed nodes and edges.
    """

    def __init__(self, llm: LLMClient) -> None:
        """Initialize the extractor.

        Args:
            llm: LLMClient instance for gateway calls.
        """
        self._llm = llm

    async def extract_from_sections(
        self,
        sections: list[dict[str, Any]],
        tenant_id: str,
        document_id: str,
        document_name: str = "",
    ) -> dict[str, Any]:
        """Extract entities and relationships from all sections.

        Processes sections sequentially, batching large content into
        chunks of at most ``_MAX_SECTION_CHARS``. On LLM failure for a
        section, logs a warning and skips that section.

        Args:
            sections: List of section dicts with keys ``section_id``,
                ``heading``, ``content``.
            tenant_id: Tenant identifier for LLM budget tracking.
            document_id: Unique identifier for the source document.
            document_name: Human-readable document name for prompts.

        Returns:
            PolicyGraph-like dict with ``tenant_id``, ``document_id``,
            ``document_name``, ``nodes``, and ``edges``.
        """
        all_nodes: list[dict[str, Any]] = []
        all_edges: list[dict[str, Any]] = []

        for section in sections:
            section_id = section.get("section_id", str(uuid.uuid4()))
            heading = section.get("heading", "Untitled")
            content = section.get("content", "")

            if not content.strip():
                continue

            # Split content into batches if it exceeds the max char limit
            chunks = self._split_content(content)

            for chunk in chunks:
                try:
                    extracted = await self._extract_chunk(
                        section_heading=heading,
                        section_content=chunk,
                        section_id=section_id,
                        document_name=document_name,
                        tenant_id=tenant_id,
                    )
                except (LLMUnavailableError, LLMCreditExhaustedError) as exc:
                    logger.warning(
                        "graph_extraction_llm_failure",
                        section_id=section_id,
                        heading=heading,
                        error=str(exc),
                        error_type=type(exc).__name__,
                    )
                    continue
                except Exception as exc:
                    logger.warning(
                        "graph_extraction_unexpected_error",
                        section_id=section_id,
                        heading=heading,
                        error=str(exc),
                        error_type=type(exc).__name__,
                    )
                    continue

                nodes, edges = self._build_graph_elements(
                    extracted, section_id, document_id
                )
                all_nodes.extend(nodes)
                all_edges.extend(edges)

        graph = PolicyGraph(
            tenant_id=tenant_id,
            document_id=document_id,
            document_name=document_name,
            nodes=[PolicyEntity(**n) for n in all_nodes],
            edges=[PolicyRelationship(**e) for e in all_edges],
        )
        return graph.model_dump(mode="json")

    async def _extract_chunk(
        self,
        section_heading: str,
        section_content: str,
        section_id: str,
        document_name: str,
        tenant_id: str,
    ) -> dict[str, Any]:
        """Send a single chunk to LLM and parse the JSON response.

        Args:
            section_heading: The heading of the section.
            section_content: The text content (already trimmed to max size).
            section_id: Identifier for the source section.
            document_name: Document name for context.
            tenant_id: Tenant ID for budget tracking.

        Returns:
            Parsed dict with keys: obligations, terms, roles, thresholds, control_refs.

        Raises:
            LLMUnavailableError: If gateway is down.
            LLMCreditExhaustedError: If tenant budget is exhausted.
        """
        prompt = _EXTRACTION_PROMPT.format(
            section_heading=section_heading,
            document_name=document_name or "Unknown Document",
            section_content=section_content,
        )

        response = await self._llm.complete(
            messages=[{"role": "user", "content": prompt}],
            task="extract_policy_obligations",
            tenant_id=tenant_id,
            temperature=0.0,
            max_tokens=2048,
        )

        return self._parse_llm_response(response.content)

    def _parse_llm_response(self, content: str) -> dict[str, Any]:
        """Parse LLM response content as JSON.

        Handles common response issues: markdown code fences, trailing text.

        Args:
            content: Raw LLM response text.

        Returns:
            Parsed dict. Returns empty structure on parse failure.
        """
        text = content.strip()

        # Strip markdown code fences if present
        if text.startswith("```"):
            lines = text.split("\n")
            # Remove first and last lines (```json and ```)
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)

        # Try to find JSON object in the response
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            text = text[start:end]

        try:
            parsed = json.loads(text)
            return parsed
        except json.JSONDecodeError:
            logger.warning("graph_extraction_json_parse_failed", content_preview=content[:200])
            return {
                "obligations": [],
                "terms": [],
                "roles": [],
                "thresholds": [],
                "control_refs": [],
            }

    def _build_graph_elements(
        self,
        extracted: dict[str, Any],
        section_id: str,
        document_id: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Convert extracted data into graph nodes and edges.

        Args:
            extracted: Parsed extraction dict from LLM.
            section_id: Source section identifier.
            document_id: Source document identifier.

        Returns:
            Tuple of (nodes list, edges list) as dicts.
        """
        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []

        # Create obligation nodes
        for obl in extracted.get("obligations", []):
            node_id = str(uuid.uuid4())
            nodes.append({
                "id": node_id,
                "entity_type": "obligation",
                "label": obl.get("text", "")[:100],
                "properties": {
                    "subject": obl.get("subject", ""),
                    "action": obl.get("action", ""),
                    "threshold": obl.get("threshold", ""),
                    "frequency": obl.get("frequency", ""),
                    "full_text": obl.get("text", ""),
                },
                "section_id": section_id,
                "source_text": obl.get("text", ""),
            })

            # Link obligation to any mentioned roles
            subject = obl.get("subject", "")
            if subject:
                role_id = str(uuid.uuid4())
                nodes.append({
                    "id": role_id,
                    "entity_type": "role",
                    "label": subject,
                    "properties": {},
                    "section_id": section_id,
                    "source_text": "",
                })
                edges.append({
                    "source_id": node_id,
                    "target_id": role_id,
                    "relationship": "owned_by",
                    "properties": {},
                })

        # Create term nodes
        for term_entry in extracted.get("terms", []):
            term_id = str(uuid.uuid4())
            nodes.append({
                "id": term_id,
                "entity_type": "term",
                "label": term_entry.get("term", ""),
                "properties": {"definition": term_entry.get("definition", "")},
                "section_id": section_id,
                "source_text": term_entry.get("definition", ""),
            })

        # Create role nodes (deduplicate later via consolidator)
        for role_name in extracted.get("roles", []):
            if isinstance(role_name, str) and role_name.strip():
                nodes.append({
                    "id": str(uuid.uuid4()),
                    "entity_type": "role",
                    "label": role_name.strip(),
                    "properties": {},
                    "section_id": section_id,
                    "source_text": "",
                })

        # Create threshold nodes
        for thresh in extracted.get("thresholds", []):
            thresh_id = str(uuid.uuid4())
            nodes.append({
                "id": thresh_id,
                "entity_type": "threshold",
                "label": f"{thresh.get('metric', '')} {thresh.get('value', '')} {thresh.get('unit', '')}".strip(),
                "properties": {
                    "metric": thresh.get("metric", ""),
                    "value": thresh.get("value", ""),
                    "unit": thresh.get("unit", ""),
                },
                "section_id": section_id,
                "source_text": "",
            })

        # Create control reference nodes and edges
        for ctrl_ref in extracted.get("control_refs", []):
            if isinstance(ctrl_ref, str) and ctrl_ref.strip():
                ctrl_id = str(uuid.uuid4())
                nodes.append({
                    "id": ctrl_id,
                    "entity_type": "control",
                    "label": ctrl_ref.strip(),
                    "properties": {"control_id": ctrl_ref.strip()},
                    "section_id": section_id,
                    "source_text": "",
                })

        return nodes, edges

    @staticmethod
    def _split_content(content: str) -> list[str]:
        """Split section content into chunks that fit within the LLM context.

        Splits on paragraph boundaries where possible.

        Args:
            content: Full section text.

        Returns:
            List of content chunks, each at most ``_MAX_SECTION_CHARS``.
        """
        if len(content) <= _MAX_SECTION_CHARS:
            return [content]

        chunks: list[str] = []
        remaining = content

        while remaining:
            if len(remaining) <= _MAX_SECTION_CHARS:
                chunks.append(remaining)
                break

            # Try to split at a paragraph boundary
            split_point = remaining[:_MAX_SECTION_CHARS].rfind("\n\n")
            if split_point < _MAX_SECTION_CHARS // 2:
                # No good paragraph break, try sentence boundary
                split_point = remaining[:_MAX_SECTION_CHARS].rfind(". ")
                if split_point < _MAX_SECTION_CHARS // 2:
                    # Fall back to hard cut
                    split_point = _MAX_SECTION_CHARS

            chunk = remaining[: split_point + 1].strip()
            if chunk:
                chunks.append(chunk)
            remaining = remaining[split_point + 1 :].strip()

        return chunks
