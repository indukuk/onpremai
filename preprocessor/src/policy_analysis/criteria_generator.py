"""Generate testing criteria from mapped obligations via LLM.

Takes obligations that have been mapped to a specific control and
generates testing criteria in the exact format that agent-eval expects.
Uses the strong tier for high-quality criterion generation.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import structlog

from common.clients import LLMClient, MemoryClient
from common.errors import LLMCreditExhaustedError, LLMUnavailableError

from src.policy_analysis.models import (
    GeneratedCriterion,
    GeneratedTestingCriteria,
)

logger = structlog.get_logger(__name__)

_CRITERIA_PROMPT = """Generate testing criteria for control {control_id} ({framework}) based on these policy obligations.

Control objective: {control_objective}
Organization's policy obligations for this control:
{obligations_text}

Generate 4-6 testing criteria. For each criterion:
- category: "policy" | "procedure" | "implementation" | "monitoring"
- question: what to verify
- evidence_type: "document" | "structured_data" | "unstructured"
- pass_condition: specific, measurable, references policy thresholds
- fail_condition: specific failure indicators
- weight: 0.05-0.30 (must sum to ~1.0)
- check_type: "file_existence" | "freshness" | "keyword_presence" | "row_count" | "null_rate" | "cross_reference" | "quantitative" (for deterministic Layer 1 checks)

Respond in JSON matching this schema:
{{"control_id": "{control_id}", "framework": "{framework}", "control_objective": "...", "criteria": [{{"id": "unique-id", "category": "...", "question": "...", "evidence_type": "...", "pass_condition": "...", "fail_condition": "...", "weight": 0.2, "check_type": "..."}}], "scoring": {{"compliant": "score >= 0.85", "partially_compliant": "0.60-0.84", "non_compliant": "< 0.60"}}}}"""


class CriteriaGenerator:
    """Generates testing criteria from control-mapped obligations.

    Uses the LLM Gateway (strong tier) to produce detailed testing
    criteria that agent-eval can consume directly. Generated criteria
    start with ``status="candidate"`` and require approval before use.
    """

    def __init__(self, llm: LLMClient, memory: MemoryClient) -> None:
        """Initialize the criteria generator.

        Args:
            llm: LLMClient instance for gateway calls.
            memory: MemoryClient for storing generated criteria.
        """
        self._llm = llm
        self._memory = memory

    async def generate_for_control(
        self,
        control_id: str,
        framework: str,
        obligations: list[dict[str, Any]],
        tenant_id: str,
        control_objective: str = "",
    ) -> dict[str, Any]:
        """Generate testing criteria for a specific control.

        Takes all obligations mapped to one control and asks the LLM
        to produce testing criteria in the agent-eval format.

        Args:
            control_id: The framework control identifier (e.g., "CC6.1").
            framework: Framework name (e.g., "SOC2").
            obligations: List of obligation dicts mapped to this control.
            tenant_id: Tenant ID for budget tracking.
            control_objective: Optional objective description for the control.

        Returns:
            Dict matching the GeneratedTestingCriteria schema.

        Raises:
            LLMUnavailableError: If gateway is unreachable.
            LLMCreditExhaustedError: If tenant budget is exhausted.
        """
        # Build obligation text for the prompt
        obligation_lines: list[str] = []
        for obl in obligations:
            text = obl.get("text", obl.get("label", ""))
            subject = obl.get("subject", "")
            threshold = obl.get("threshold", "")
            frequency = obl.get("frequency", "")

            line = f"- {text}"
            if subject:
                line += f" (responsible: {subject})"
            if threshold:
                line += f" [threshold: {threshold}]"
            if frequency:
                line += f" [frequency: {frequency}]"
            obligation_lines.append(line)

        obligations_text = "\n".join(obligation_lines) if obligation_lines else "No specific obligations provided."

        # Derive control objective if not provided
        if not control_objective:
            control_objective = f"Ensure compliance with {framework} control {control_id}"

        prompt = _CRITERIA_PROMPT.format(
            control_id=control_id,
            framework=framework,
            control_objective=control_objective,
            obligations_text=obligations_text,
        )

        response = await self._llm.complete(
            messages=[{"role": "user", "content": prompt}],
            task="generate_testing_criteria",
            tenant_id=tenant_id,
            temperature=0.1,
            max_tokens=4096,
        )

        parsed = self._parse_criteria_response(response.content)

        # Build the complete criteria object
        criteria = self._build_criteria(
            parsed=parsed,
            control_id=control_id,
            framework=framework,
            tenant_id=tenant_id,
            control_objective=control_objective,
            obligations=obligations,
        )

        logger.info(
            "criteria_generated",
            control_id=control_id,
            framework=framework,
            criteria_count=len(criteria.get("criteria", [])),
            tenant_id=tenant_id,
        )

        return criteria

    async def store_criteria(self, criteria: dict[str, Any], tenant_id: str) -> bool:
        """Store generated criteria in memory service.

        Stores via skill memory with a naming convention that allows
        retrieval by framework and control.

        Args:
            criteria: The generated criteria dict.
            tenant_id: Tenant identifier.

        Returns:
            True if stored successfully, False otherwise.
        """
        framework = criteria.get("framework", "unknown")
        control_id = criteria.get("control_id", "unknown")
        skill_name = f"criteria/{framework}/{control_id}"

        success = await self._memory.skill_store(
            tenant_id=tenant_id,
            skill_name=skill_name,
            skill_data=criteria,
            metadata={
                "source": "policy_analysis",
                "status": criteria.get("status", "candidate"),
                "criteria_count": len(criteria.get("criteria", [])),
            },
        )

        if success:
            logger.info(
                "criteria_stored",
                skill_name=skill_name,
                tenant_id=tenant_id,
            )
        else:
            logger.warning(
                "criteria_store_failed",
                skill_name=skill_name,
                tenant_id=tenant_id,
            )

        return success

    def _parse_criteria_response(self, content: str) -> dict[str, Any]:
        """Parse LLM response containing generated criteria.

        Args:
            content: Raw LLM response text.

        Returns:
            Parsed JSON dict. Returns empty structure on parse failure.
        """
        text = content.strip()

        # Strip markdown code fences
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)

        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            text = text[start:end]

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            logger.warning(
                "criteria_json_parse_failed",
                content_preview=content[:200],
            )
            return {"criteria": []}

    def _build_criteria(
        self,
        parsed: dict[str, Any],
        control_id: str,
        framework: str,
        tenant_id: str,
        control_objective: str,
        obligations: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Build a complete GeneratedTestingCriteria from parsed LLM output.

        Validates and normalizes the LLM output, assigns IDs where missing,
        and ensures weights are reasonable.

        Args:
            parsed: Parsed LLM response dict.
            control_id: Control identifier.
            framework: Framework name.
            tenant_id: Tenant identifier.
            control_objective: Control objective text.
            obligations: Source obligations for provenance.

        Returns:
            Dict matching GeneratedTestingCriteria schema.
        """
        raw_criteria = parsed.get("criteria", [])
        criteria_list: list[dict[str, Any]] = []

        for raw in raw_criteria:
            criterion = GeneratedCriterion(
                id=raw.get("id", str(uuid.uuid4())),
                category=self._validate_category(raw.get("category", "implementation")),
                question=raw.get("question", ""),
                evidence_type=self._validate_evidence_type(raw.get("evidence_type", "document")),
                pass_condition=raw.get("pass_condition", ""),
                fail_condition=raw.get("fail_condition", ""),
                weight=self._clamp_weight(raw.get("weight", 0.2)),
                check_type=raw.get("check_type"),
                check_params=raw.get("check_params", {}),
                policy_source=raw.get("policy_source", ""),
                status="candidate",
            )
            criteria_list.append(criterion.model_dump(mode="json"))

        # Normalize weights to sum to ~1.0
        criteria_list = self._normalize_weights(criteria_list)

        # Build provenance info
        derived_from: list[dict[str, str]] = []
        for obl in obligations:
            derived_from.append({
                "document": obl.get("document_name", ""),
                "section": obl.get("section_id", ""),
                "page": str(obl.get("page_number", "")),
            })

        result = GeneratedTestingCriteria(
            control_id=control_id,
            framework=framework,
            tenant_id=tenant_id,
            control_objective=parsed.get("control_objective", control_objective),
            criteria=[GeneratedCriterion(**c) for c in criteria_list],
            derived_from=derived_from,
            status="candidate",
        )
        return result.model_dump(mode="json")

    @staticmethod
    def _validate_category(category: str) -> str:
        """Validate and normalize criterion category."""
        valid = {"policy", "procedure", "implementation", "monitoring"}
        cat = category.lower().strip()
        return cat if cat in valid else "implementation"

    @staticmethod
    def _validate_evidence_type(evidence_type: str) -> str:
        """Validate and normalize evidence type."""
        valid = {"document", "structured_data", "unstructured"}
        et = evidence_type.lower().strip()
        return et if et in valid else "document"

    @staticmethod
    def _clamp_weight(weight: Any) -> float:
        """Clamp weight to valid range [0.05, 0.30]."""
        try:
            w = float(weight)
        except (TypeError, ValueError):
            return 0.2
        return max(0.05, min(0.30, w))

    @staticmethod
    def _normalize_weights(criteria: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Normalize weights to sum to approximately 1.0.

        Args:
            criteria: List of criterion dicts with ``weight`` keys.

        Returns:
            Same list with adjusted weights.
        """
        if not criteria:
            return criteria

        total = sum(c.get("weight", 0.2) for c in criteria)
        if total <= 0:
            # Distribute evenly
            even_weight = 1.0 / len(criteria)
            for c in criteria:
                c["weight"] = round(even_weight, 3)
        elif abs(total - 1.0) > 0.05:
            # Scale to sum to 1.0
            for c in criteria:
                c["weight"] = round(c.get("weight", 0.2) / total, 3)

        return criteria
