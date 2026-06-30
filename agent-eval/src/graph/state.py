"""LangGraph TypedDict state schema for the evaluation pipeline.

LangGraph requires a TypedDict for graph state. This module defines
EvalGraphState which mirrors the Pydantic EvalState but as a TypedDict
for compatibility with LangGraph's StateGraph.
"""

from __future__ import annotations

from typing import Any, TypedDict

from src.models import (
    ComplianceStatus,
    CriterionResult,
    EvalResult,
    EvidenceFile,
    EvidenceMetadata,
    LayerStats,
    TestingCriteria,
    TimingStats,
)


class EvalGraphState(TypedDict, total=False):
    """State passed between LangGraph nodes during evaluation.

    All fields are optional (total=False) because nodes add fields
    incrementally as the graph executes.
    """

    # Input
    control_id: str
    framework: str
    tenant_id: str
    trace_id: str
    bypass_cache: bool

    # Router
    intent: str

    # Discovery
    evidence_files: list[EvidenceFile]
    evidence_hash: str

    # Extractor
    evidence_metadata: list[EvidenceMetadata]

    # Testing criteria
    testing_criteria: TestingCriteria | None

    # Layer 1 - Rules
    rule_results: dict[str, CriterionResult]
    needs_judgment: list[str]

    # Layer 2 - LLM Judgment
    judgment_results: dict[str, CriterionResult]
    tribunal_justifications: dict[str, dict[str, Any]]  # criterion_id -> tribunal doc

    # Layer 3 - Scoring
    final_score: float
    final_status: ComplianceStatus

    # Sandbox
    sandbox_code: str
    sandbox_output: str
    sandbox_retries: int

    # Output
    evaluation_result: EvalResult | None
    error: str | None

    # Partial evaluation
    partial_evaluation: bool

    # Chat
    chat_message: str
    chat_response: str

    # Timing
    timing: TimingStats
    layer_stats: LayerStats

    # Tenant context from memory
    tenant_context: list[dict[str, Any]]
    patterns: list[dict[str, Any]]

    # Cached result
    cached_result: EvalResult | None
