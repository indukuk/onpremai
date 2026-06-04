"""Testing criteria retriever and LangGraph node.

Retrieves testing criteria for a control from the RAG index or
memory service (for observer-updated versions). Falls back to a
default criteria structure if neither source has criteria.
"""

from __future__ import annotations

from typing import Any

import structlog

from common.clients import MemoryClient

from src.models import Criterion, TestingCriteria
from src.rag.index import get_rag_index

logger = structlog.get_logger(__name__)


async def load_testing_criteria_node(state: dict[str, Any]) -> dict[str, Any]:
    """LangGraph node: Load testing criteria for the control being evaluated.

    Priority:
    1. Memory service (observer may have updated version)
    2. RAG index (bundled at build time)
    3. Default minimal criteria (ensures evaluation can proceed)
    """
    framework = state.get("framework", "")
    control_id = state.get("control_id", "")
    tenant_id = state.get("tenant_id", "")
    trace_id = state.get("trace_id", "")

    criteria = await _load_from_memory(tenant_id, framework, control_id)
    if criteria is not None:
        logger.info(
            "criteria_loaded_from_memory",
            framework=framework,
            control_id=control_id,
            trace_id=trace_id,
        )
        return {"testing_criteria": criteria}

    criteria = _load_from_rag(framework, control_id)
    if criteria is not None:
        logger.info(
            "criteria_loaded_from_rag",
            framework=framework,
            control_id=control_id,
            trace_id=trace_id,
        )
        return {"testing_criteria": criteria}

    # Generate default criteria
    criteria = _generate_default_criteria(framework, control_id)
    logger.warning(
        "criteria_using_default",
        framework=framework,
        control_id=control_id,
        trace_id=trace_id,
    )
    return {"testing_criteria": criteria}


async def _load_from_memory(
    tenant_id: str,
    framework: str,
    control_id: str,
) -> TestingCriteria | None:
    """Try to load testing criteria from memory service (observer-updated)."""
    memory = MemoryClient()
    try:
        skills = await memory.skill_recall(
            tenant_id=tenant_id,
            skill_name=f"criteria/{framework}/{control_id}",
        )
        if skills and isinstance(skills, list) and len(skills) > 0:
            skill_data = skills[0]
            data = skill_data.get("skill_data", skill_data)
            return TestingCriteria.model_validate(data)
        return None
    except Exception as exc:
        logger.warning(
            "criteria_memory_load_error",
            error=str(exc),
            framework=framework,
            control_id=control_id,
        )
        return None
    finally:
        await memory.close()


def _load_from_rag(framework: str, control_id: str) -> TestingCriteria | None:
    """Load testing criteria from the bundled RAG index."""
    rag = get_rag_index()
    if not rag.loaded:
        return None

    chunk = rag.get_testing_criteria(framework, control_id)
    if chunk is None:
        return None

    try:
        return TestingCriteria.model_validate(chunk)
    except Exception:
        return None


def _generate_default_criteria(framework: str, control_id: str) -> TestingCriteria:
    """Generate minimal default testing criteria when no source is available.

    These defaults ensure evaluation can always proceed, with criteria
    that cover the standard compliance categories.
    """
    return TestingCriteria(
        control_id=control_id,
        framework=framework,
        control_objective=f"Control {control_id} objective (default criteria)",
        criteria=[
            Criterion(
                id=f"TC-{control_id}-01",
                category="policy",
                question="Is there a documented policy for this control?",
                evidence_type="document",
                pass_condition="Policy document exists, is current (within 12 months), and covers the control objective",
                fail_condition="No policy document, or document is expired or does not cover the control",
                weight=0.20,
                check_type="file_existence",
            ),
            Criterion(
                id=f"TC-{control_id}-02",
                category="procedure",
                question="Is there a documented procedure for implementing this control?",
                evidence_type="document",
                pass_condition="Procedure document exists and describes implementation steps",
                fail_condition="No procedure documentation found",
                weight=0.15,
                check_type="file_existence",
            ),
            Criterion(
                id=f"TC-{control_id}-03",
                category="implementation",
                question="Is there evidence that the control is operating?",
                evidence_type="structured_data",
                pass_condition="Records exist showing control activity during the audit period",
                fail_condition="No operational records found",
                weight=0.30,
                check_type="row_count",
            ),
            Criterion(
                id=f"TC-{control_id}-04",
                category="implementation",
                question="Are control records complete and populated?",
                evidence_type="structured_data",
                pass_condition="Key columns are populated with >= 95% completeness",
                fail_condition="Key columns have significant null/empty values",
                weight=0.20,
                check_type="null_rate",
            ),
            Criterion(
                id=f"TC-{control_id}-05",
                category="monitoring",
                question="Is the control being monitored for effectiveness?",
                evidence_type="unstructured",
                pass_condition="Monitoring evidence shows ongoing oversight of control effectiveness",
                fail_condition="No monitoring or review evidence found",
                weight=0.15,
            ),
        ],
        scoring={
            "compliant": "Weighted score >= 0.85",
            "partially_compliant": "Weighted score 0.60 - 0.84",
            "non_compliant": "Weighted score < 0.60",
            "insufficient_evidence": "Cannot assess >= 50% of criteria weight",
        },
    )
