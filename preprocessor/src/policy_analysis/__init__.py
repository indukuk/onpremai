"""Policy Analysis Pipeline - structural parsing, obligation extraction, and criteria generation.

Provides no-LLM structural parsing of compliance policy documents and SOA spreadsheets,
extracting obligations, control mappings, and generating testing criteria for agent-eval.
LLM-powered modules handle entity extraction, control mapping, criteria generation,
obligation consolidation, and review management.
"""

from __future__ import annotations

from src.policy_analysis.control_mapper import ControlMapper
from src.policy_analysis.criteria_generator import CriteriaGenerator
from src.policy_analysis.graph_extractor import GraphExtractor
from src.policy_analysis.models import (
    ControlMapping,
    GeneratedCriterion,
    GeneratedTestingCriteria,
    Obligation,
    PipelineState,
    PolicyEntity,
    PolicyGraph,
    PolicyRelationship,
    PolicySection,
)
from src.policy_analysis.obligation_consolidator import ObligationConsolidator
from src.policy_analysis.review_manager import ReviewManager
from src.policy_analysis.soa_parser import parse_soa
from src.policy_analysis.structural_parser import parse_document

__all__ = [
    "ControlMapper",
    "ControlMapping",
    "CriteriaGenerator",
    "GeneratedCriterion",
    "GeneratedTestingCriteria",
    "GraphExtractor",
    "Obligation",
    "ObligationConsolidator",
    "PipelineState",
    "PolicyEntity",
    "PolicyGraph",
    "PolicyRelationship",
    "PolicySection",
    "ReviewManager",
    "parse_document",
    "parse_soa",
]
