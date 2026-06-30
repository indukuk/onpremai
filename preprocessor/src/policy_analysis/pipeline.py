"""Policy Analysis Pipeline orchestrator.

Coordinates the end-to-end analysis of a policy document:
1. Structural parsing (no LLM)
2. Graph extraction (LLM)
3. Control mapping (LLM)
4. Criteria generation (LLM)
5. Storage for agent-eval consumption

Triggered when the preprocessor detects a policy document.
Handles errors gracefully — partial results are preserved.
"""

from __future__ import annotations

import hashlib
import time
from datetime import datetime, timezone
from typing import Any

import structlog

from common.clients import LLMClient, MemoryClient

from src.policy_analysis.control_mapper import ControlMapper
from src.policy_analysis.criteria_generator import CriteriaGenerator
from src.policy_analysis.graph_extractor import GraphExtractor
from src.policy_analysis.models import PipelineState
from src.policy_analysis.obligation_consolidator import ObligationConsolidator
from src.policy_analysis.structural_parser import parse_document

logger = structlog.get_logger(__name__)

POLICY_INDICATORS = frozenset({
    "shall", "must not", "is required to", "policy statement",
    "scope and applicability", "compliance requirements",
    "roles and responsibilities", "enforcement",
})


def is_policy_document(filename: str, text_content: str = "") -> bool:
    """Detect whether a document is a compliance policy.

    Heuristic:
    - Filename contains 'policy' (case-insensitive)
    - Or text contains multiple obligation keywords
    """
    if "policy" in filename.lower():
        return True

    if not text_content:
        return False

    text_lower = text_content[:5000].lower()
    matches = sum(1 for indicator in POLICY_INDICATORS if indicator in text_lower)
    return matches >= 3


class PolicyAnalysisPipeline:
    """Orchestrates policy document analysis from text to testing criteria."""

    def __init__(
        self,
        llm: LLMClient,
        memory: MemoryClient,
    ) -> None:
        self._llm = llm
        self._memory = memory
        self._extractor = GraphExtractor(llm=llm)
        self._mapper = ControlMapper(llm=llm)
        self._generator = CriteriaGenerator(llm=llm, memory=memory)
        self._consolidator = ObligationConsolidator()

    async def run(
        self,
        tenant_id: str,
        document_key: str,
        document_name: str,
        text_content: str,
        framework: str = "soc2",
    ) -> PipelineState:
        """Run the full policy analysis pipeline.

        Args:
            tenant_id: Tenant this policy belongs to.
            document_key: Storage key of the document.
            document_name: Human-readable filename.
            text_content: Extracted text content of the policy.
            framework: Target compliance framework.

        Returns:
            PipelineState with progress and results summary.
        """
        content_hash = hashlib.sha256(text_content.encode()).hexdigest()[:16]
        state = PipelineState(
            tenant_id=tenant_id,
            document_key=document_key,
            content_hash=content_hash,
            started_at=datetime.now(timezone.utc).isoformat(),
        )

        start_time = time.time()

        logger.info(
            "policy_pipeline_started",
            tenant_id=tenant_id,
            document=document_name,
            content_length=len(text_content),
        )

        # Step 1: Structural parsing (no LLM)
        state.current_step = "parsing"
        try:
            sections = parse_document(text_content, filename=document_name)
            state.sections_parsed = len(sections)
        except Exception as exc:
            state.errors.append(f"Parsing failed: {exc}")
            state.current_step = "failed"
            logger.error("policy_parse_failed", error=str(exc), document=document_name)
            return state

        if not sections:
            state.errors.append("No sections found in document")
            state.current_step = "failed"
            return state

        logger.info("policy_parsed", sections=len(sections), document=document_name)

        # Step 2: Graph extraction (LLM)
        state.current_step = "extracting"
        try:
            section_dicts = [s.model_dump(mode="json") for s in sections]
            graph = await self._extractor.extract_from_sections(
                sections=section_dicts,
                tenant_id=tenant_id,
                document_id=document_key,
            )
            obligation_nodes = [
                n for n in graph.get("nodes", [])
                if n.get("entity_type") == "obligation"
            ]
            state.obligations_extracted = len(obligation_nodes)
        except Exception as exc:
            state.errors.append(f"Extraction failed: {exc}")
            state.current_step = "failed"
            logger.error("policy_extraction_failed", error=str(exc))
            return state

        if not obligation_nodes:
            state.errors.append("No obligations extracted")
            state.current_step = "complete"
            state.completed_at = datetime.now(timezone.utc).isoformat()
            return state

        logger.info(
            "policy_extracted",
            obligations=len(obligation_nodes),
            total_nodes=len(graph.get("nodes", [])),
        )

        # Step 3: Control mapping (LLM)
        state.current_step = "mapping"
        try:
            mappings = await self._mapper.map_obligations(
                obligations=obligation_nodes,
                framework=framework,
                tenant_id=tenant_id,
            )
            state.controls_mapped = len(mappings)
        except Exception as exc:
            state.errors.append(f"Mapping failed: {exc}")
            logger.warning("policy_mapping_failed", error=str(exc))
            mappings = []

        if not mappings:
            state.errors.append("No control mappings found")
            state.current_step = "complete"
            state.completed_at = datetime.now(timezone.utc).isoformat()
            return state

        logger.info("policy_mapped", mappings=len(mappings))

        # Step 4: Group obligations by control and generate criteria
        state.current_step = "generating"
        controls_obligations = self._group_by_control(obligation_nodes, mappings)

        criteria_count = 0
        for control_id, obligations in controls_obligations.items():
            try:
                criteria = await self._generator.generate_for_control(
                    control_id=control_id,
                    framework=framework,
                    obligations=obligations,
                    tenant_id=tenant_id,
                )
                if criteria:
                    await self._generator.store_criteria(criteria, tenant_id)
                    criteria_count += 1
            except Exception as exc:
                state.errors.append(f"Criteria generation failed for {control_id}: {exc}")
                logger.warning(
                    "criteria_generation_failed",
                    control_id=control_id,
                    error=str(exc),
                )

        state.criteria_generated = criteria_count

        # Store the policy graph for future queries
        try:
            await self._memory.tenant_store(
                tenant_id=tenant_id,
                fact=f"Policy analyzed: {document_name} ({len(obligation_nodes)} obligations, {len(mappings)} control mappings, {criteria_count} criteria generated)",
                category="policy_analysis",
            )
        except Exception:
            pass

        # Publish event for shadow agent
        try:
            await self._memory.event_queue_push(
                user_id="__all__",
                tenant_id=tenant_id,
                event_type="policy_analyzed",
                summary=f"Policy '{document_name}' analyzed: {criteria_count} testing criteria generated for {len(controls_obligations)} controls",
                priority="medium",
                source_service="preprocessor",
                metadata={
                    "document_name": document_name,
                    "framework": framework,
                    "obligations": len(obligation_nodes),
                    "criteria_generated": criteria_count,
                },
            )
        except Exception:
            pass

        state.current_step = "complete"
        state.completed_at = datetime.now(timezone.utc).isoformat()

        elapsed_sec = time.time() - start_time
        logger.info(
            "policy_pipeline_complete",
            tenant_id=tenant_id,
            document=document_name,
            sections=state.sections_parsed,
            obligations=state.obligations_extracted,
            mappings=state.controls_mapped,
            criteria=state.criteria_generated,
            elapsed_sec=round(elapsed_sec, 1),
            errors=len(state.errors),
        )

        return state

    def _group_by_control(
        self,
        obligations: list[dict[str, Any]],
        mappings: list[dict[str, Any]],
    ) -> dict[str, list[dict[str, Any]]]:
        """Group obligations by their mapped control_id."""
        obligation_by_id: dict[str, dict[str, Any]] = {}
        for obl in obligations:
            obl_id = obl.get("id", "")
            if obl_id:
                obligation_by_id[obl_id] = obl

        controls: dict[str, list[dict[str, Any]]] = {}
        for mapping in mappings:
            control_id = mapping.get("control_id", "")
            obl_id = mapping.get("obligation_id", "")
            if control_id and obl_id and obl_id in obligation_by_id:
                controls.setdefault(control_id, []).append(obligation_by_id[obl_id])

        return controls
