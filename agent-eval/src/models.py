"""Pydantic models for agent-eval service.

Defines request/response schemas, internal data structures, and evaluation
result types used throughout the pipeline.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# --- Enums ---


class JobStatusEnum(str, Enum):
    """Status of an async evaluation job."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class CriterionResultEnum(str, Enum):
    """Result of evaluating a single criterion."""

    PASS = "PASS"
    PARTIAL = "PARTIAL"
    FAIL = "FAIL"
    NEEDS_JUDGMENT = "NEEDS_JUDGMENT"
    CANNOT_ASSESS = "CANNOT_ASSESS"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class ComplianceStatus(str, Enum):
    """Overall compliance status for a control."""

    COMPLIANT = "compliant"
    PARTIALLY_COMPLIANT = "partially_compliant"
    NON_COMPLIANT = "non_compliant"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    PARTIAL_EVALUATION = "partial_evaluation"


class EvalMethod(str, Enum):
    """Method used to evaluate a criterion."""

    RULE_FILE_EXISTENCE = "rule:file_existence"
    RULE_FRESHNESS = "rule:freshness"
    RULE_SCHEMA_PRESENCE = "rule:schema_presence"
    RULE_ROW_COUNT = "rule:row_count"
    RULE_NULL_RATE = "rule:null_rate"
    RULE_CROSS_REFERENCE = "rule:cross_reference"
    RULE_QUANTITATIVE = "rule:quantitative"
    RULE_KEYWORD_PRESENCE = "rule:keyword_presence"
    LLM_JUDGMENT = "llm_judgment"
    CACHED = "cached"
    DEGRADED = "degraded"


# --- Criterion & Testing Criteria ---


class Criterion(BaseModel):
    """A single testing criterion for a control."""

    id: str
    category: str
    question: str
    evidence_type: str
    pass_condition: str
    fail_condition: str
    weight: float = 0.1
    check_type: str | None = None
    check_params: dict[str, Any] = Field(default_factory=dict)


class TestingCriteria(BaseModel):
    """Complete testing criteria for a single control."""

    chunk_type: str = "testing_criteria"
    control_id: str
    framework: str
    control_objective: str
    criteria: list[Criterion]
    scoring: dict[str, str] = Field(default_factory=dict)
    evidence_checklist: list[dict[str, Any]] = Field(default_factory=list)


# --- Evidence ---


class EvidenceFile(BaseModel):
    """An evidence file discovered in storage."""

    storage_key: str
    filename: str
    file_type: str = ""
    size_bytes: int = 0
    last_modified: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    content_hash: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvidenceMetadata(BaseModel):
    """Extracted metadata from an evidence file."""

    storage_key: str
    file_type: str = ""
    columns: list[str] = Field(default_factory=list)
    row_count: int = 0
    sheet_names: list[str] = Field(default_factory=list)
    text_content: str = ""
    extracted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    schema_info: dict[str, Any] = Field(default_factory=dict)


# --- Criterion Results ---


class CriterionResult(BaseModel):
    """Result of evaluating a single criterion."""

    criterion_id: str
    category: str
    result: CriterionResultEnum
    method: EvalMethod = EvalMethod.LLM_JUDGMENT
    reason: str = ""
    confidence: float | None = None
    evidence_used: list[str] = Field(default_factory=list)


# --- Layer Stats ---


class LayerStats(BaseModel):
    """Statistics about which layers resolved which criteria."""

    layer1_resolved: int = 0
    layer2_resolved: int = 0
    total_criteria: int = 0
    llm_calls: int = 0
    sandbox_calls: int = 0


class TimingStats(BaseModel):
    """Timing breakdown for the evaluation."""

    total_ms: float = 0.0
    layer1_ms: float = 0.0
    layer2_ms: float = 0.0
    layer3_ms: float = 0.0
    sandbox_ms: float = 0.0
    discovery_ms: float = 0.0
    extraction_ms: float = 0.0


# --- Evaluation Result ---


class EvalResult(BaseModel):
    """Complete evaluation result for a single control."""

    evaluation_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    control_id: str
    framework: str
    tenant_id: str
    score: float = 0.0
    status: ComplianceStatus = ComplianceStatus.INSUFFICIENT_EVIDENCE
    evidence_hash: str = ""
    criteria_results: list[CriterionResult] = Field(default_factory=list)
    justification: dict[str, Any] = Field(default_factory=dict)
    layer_stats: LayerStats = Field(default_factory=LayerStats)
    timing: TimingStats = Field(default_factory=TimingStats)
    partial_evaluation: bool = False
    cached: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# --- API Request/Response ---


class EvalRequest(BaseModel):
    """Request to start an evaluation."""

    control_id: str
    framework: str
    tenant_id: str
    bypass_cache: bool = False
    trace_id: str | None = None


class EvalStartResponse(BaseModel):
    """Response from POST /evaluate."""

    job_id: str
    status: JobStatusEnum = JobStatusEnum.PROCESSING


class JobStatus(BaseModel):
    """Response from GET /status/{job_id}."""

    job_id: str
    status: JobStatusEnum
    evaluation: EvalResult | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None


class ChatRequest(BaseModel):
    """Request body for POST /chat."""

    message: str
    tenant_id: str
    session_id: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)


class ChatResponse(BaseModel):
    """Response from POST /chat."""

    response: str
    session_id: str
    sources: list[str] = Field(default_factory=list)


# --- Graph State ---


class EvalState(BaseModel):
    """Serializable state for the LangGraph evaluation pipeline.

    This model tracks accumulated state as the graph executes across
    nodes. It is converted to/from the TypedDict used by LangGraph.
    """

    # Input
    control_id: str = ""
    framework: str = ""
    tenant_id: str = ""
    trace_id: str = ""
    bypass_cache: bool = False

    # Router
    intent: str = ""  # evaluate | chat | status

    # Discovery
    evidence_files: list[EvidenceFile] = Field(default_factory=list)
    evidence_hash: str = ""

    # Extractor
    evidence_metadata: list[EvidenceMetadata] = Field(default_factory=list)

    # Testing criteria
    testing_criteria: TestingCriteria | None = None

    # Layer 1 - Rules
    rule_results: dict[str, CriterionResult] = Field(default_factory=dict)
    needs_judgment: list[str] = Field(default_factory=list)

    # Layer 2 - LLM Judgment
    judgment_results: dict[str, CriterionResult] = Field(default_factory=dict)
    tribunal_justifications: dict[str, dict[str, Any]] = Field(default_factory=dict)

    # Layer 3 - Scoring
    final_score: float = 0.0
    final_status: ComplianceStatus = ComplianceStatus.INSUFFICIENT_EVIDENCE

    # Sandbox
    sandbox_code: str = ""
    sandbox_output: str = ""
    sandbox_retries: int = 0

    # Output
    evaluation_result: EvalResult | None = None
    error: str | None = None

    # Partial evaluation
    partial_evaluation: bool = False

    # Chat
    chat_message: str = ""
    chat_response: str = ""

    # Timing
    timing: TimingStats = Field(default_factory=TimingStats)
    layer_stats: LayerStats = Field(default_factory=LayerStats)

    # Tenant context from memory
    tenant_context: list[dict[str, Any]] = Field(default_factory=list)
    patterns: list[dict[str, Any]] = Field(default_factory=list)
