"""Pydantic v2 models for the Policy Analysis Pipeline.

Defines data structures for structural parsing output, obligation extraction,
knowledge graph representation, control mapping, and generated testing criteria.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class PolicySection(BaseModel):
    """A structural section parsed from a policy document."""

    section_id: str
    heading: str
    level: int  # 1=chapter, 2=section, 3=subsection
    content: str
    parent_id: str | None = None
    page_number: int | None = None


class Obligation(BaseModel):
    """A normative obligation extracted from a policy section."""

    id: str
    text: str  # The actual clause text
    section_id: str
    modality: str  # "shall" | "must" | "should" | "may"
    subject: str  # Who must do this (e.g., "System Owner")
    action: str  # What must be done
    object: str = ""  # What it applies to
    threshold: str = ""  # SLA, frequency, cadence
    frequency: str = ""  # "quarterly", "annually", etc.


class PolicyEntity(BaseModel):
    """A node in the policy knowledge graph."""

    id: str
    entity_type: str  # "obligation" | "role" | "term" | "system" | "threshold" | "control"
    label: str
    properties: dict[str, Any] = Field(default_factory=dict)
    section_id: str = ""
    source_text: str = ""


class PolicyRelationship(BaseModel):
    """An edge in the policy knowledge graph."""

    source_id: str
    target_id: str
    relationship: str  # "requires" | "applies_to" | "defines" | "maps_to" | "measured_by" | "has_exception" | "owned_by"
    properties: dict[str, Any] = Field(default_factory=dict)


class PolicyGraph(BaseModel):
    """Complete knowledge graph for a policy document."""

    tenant_id: str
    document_id: str
    document_name: str = ""
    nodes: list[PolicyEntity] = Field(default_factory=list)
    edges: list[PolicyRelationship] = Field(default_factory=list)


class ControlMapping(BaseModel):
    """Maps a policy obligation to a compliance framework control."""

    obligation_id: str
    framework: str
    control_id: str
    confidence: float = 0.9
    source_section: str = ""


class GeneratedCriterion(BaseModel):
    """A testing criterion generated from policy analysis. Matches agent-eval's Criterion schema."""

    id: str
    category: str  # "policy" | "procedure" | "implementation" | "monitoring"
    question: str
    evidence_type: str  # "document" | "structured_data" | "unstructured"
    pass_condition: str
    fail_condition: str
    weight: float = 0.1
    check_type: str | None = None
    check_params: dict[str, Any] = Field(default_factory=dict)
    policy_source: str = ""  # "ISP Section 4.2"
    status: str = "candidate"  # "candidate" | "approved" | "rejected"


class GeneratedTestingCriteria(BaseModel):
    """Complete testing criteria for one control, generated from policy analysis."""

    control_id: str
    framework: str
    tenant_id: str
    control_objective: str
    criteria: list[GeneratedCriterion] = Field(default_factory=list)
    derived_from: list[dict[str, str]] = Field(default_factory=list)  # [{document, section, page}]
    status: str = "candidate"


class PipelineState(BaseModel):
    """Tracks pipeline progress for resumability."""

    tenant_id: str
    document_key: str
    content_hash: str = ""
    current_step: str = "pending"  # pending | parsing | extracting | mapping | generating | complete | failed
    sections_parsed: int = 0
    obligations_extracted: int = 0
    controls_mapped: int = 0
    criteria_generated: int = 0
    errors: list[str] = Field(default_factory=list)
    started_at: str = ""
    completed_at: str = ""
