"""Diagnosis engine — uses strong-tier LLM to analyze root causes.

For each detected issue, builds context (metrics + sample calls),
sends to the LLM via the gateway, and produces a structured diagnosis.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import httpx
import structlog

from observer.src.config import ObserverSettings
from observer.src.detection.detector import DetectedIssue

logger = structlog.get_logger(__name__)


@dataclass
class Diagnosis:
    """Result of LLM-powered root cause analysis."""

    id: str = field(default_factory=lambda: f"diag_{uuid4().hex[:12]}")
    issue_id: str = ""
    root_cause: str = ""
    fix_type: str = ""  # routing | prompt | threshold | model | pattern
    fix_description: str = ""
    confidence: float = 0.0
    requires_prompt_rewrite: bool = False
    diagnosed_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    cost_usd: float = 0.0
    raw_response: str = ""


DIAGNOSIS_SYSTEM_PROMPT = """You are an expert AI system diagnostician analyzing performance issues in an LLM routing system.

Given an issue with its metrics and sample data, diagnose the root cause and propose a fix.

Your response MUST be valid JSON with exactly these fields:
{
  "root_cause": "Clear description of why this issue is occurring",
  "fix_type": "routing|prompt|threshold|model|pattern",
  "fix_description": "Specific actionable fix to apply",
  "confidence": 0.0 to 1.0,
  "requires_prompt_rewrite": true or false
}

Fix types:
- routing: Move task to a different model tier (fast/mid/strong)
- prompt: Rewrite or adjust the prompt template for the task
- threshold: Adjust the confidence threshold that triggers escalation
- model: Add, swap, or reconfigure a model in a tier
- pattern: Record or remove a pattern in the memory service

Be specific and actionable. Base your confidence on how certain you are about the root cause.
"""


class DiagnosisEngine:
    """LLM-powered diagnosis of detected performance issues.

    Uses the strong tier via the LLM gateway (task=complex_reasoning)
    to analyze root causes. Enforces per-cycle budget limits.
    """

    def __init__(self, settings: ObserverSettings) -> None:
        self._settings = settings
        self._http_client: httpx.AsyncClient | None = None
        self._cycle_spend: float = 0.0

    async def start(self) -> None:
        """Initialize the HTTP client."""
        self._http_client = httpx.AsyncClient(
            base_url=self._settings.llm_gateway_url,
            timeout=httpx.Timeout(120.0),
        )

    async def close(self) -> None:
        """Shutdown the HTTP client."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None

    def reset_cycle_budget(self) -> None:
        """Reset the per-cycle budget tracker. Called at the start of each cycle."""
        self._cycle_spend = 0.0

    @property
    def remaining_budget(self) -> float:
        """How much budget remains in the current cycle."""
        return max(0.0, self._settings.observer_budget_per_cycle_usd - self._cycle_spend)

    async def diagnose(self, issue: DetectedIssue) -> Diagnosis | None:
        """Diagnose a single detected issue using strong-tier LLM.

        Args:
            issue: The detected issue to diagnose.

        Returns:
            A Diagnosis object, or None if budget exceeded or LLM unavailable.
        """
        # Budget check
        estimated_cost = self._estimate_cost()
        if estimated_cost > self.remaining_budget:
            logger.warning(
                "diagnosis_deferred_budget",
                issue_id=issue.id,
                estimated_cost=estimated_cost,
                remaining_budget=self.remaining_budget,
            )
            return None

        # Build diagnosis prompt
        user_prompt = self._build_diagnosis_prompt(issue)

        # Call LLM
        try:
            response_data = await self._call_llm(user_prompt)
        except (httpx.HTTPError, ValueError) as exc:
            logger.error("diagnosis_llm_call_failed", issue_id=issue.id, error=str(exc))
            return None

        # Track cost
        actual_cost = response_data.get("cost_usd", estimated_cost)
        self._cycle_spend += actual_cost

        # Parse response
        diagnosis = self._parse_diagnosis_response(
            issue=issue,
            response_content=response_data.get("content", ""),
            cost=actual_cost,
        )

        if diagnosis:
            logger.info(
                "diagnosis_complete",
                issue_id=issue.id,
                diagnosis_id=diagnosis.id,
                fix_type=diagnosis.fix_type,
                confidence=diagnosis.confidence,
                cost_usd=actual_cost,
            )

        return diagnosis

    async def diagnose_batch(self, issues: list[DetectedIssue]) -> list[Diagnosis]:
        """Diagnose a batch of issues, respecting budget limits.

        Issues are processed in severity order (highest first).
        Stops when budget is exhausted; remaining issues are deferred.

        Args:
            issues: List of detected issues (should be pre-sorted by severity).

        Returns:
            List of successful diagnoses.
        """
        self.reset_cycle_budget()
        diagnoses: list[Diagnosis] = []
        deferred_count = 0

        for issue in issues:
            if self.remaining_budget <= 0:
                deferred_count += 1
                continue

            diagnosis = await self.diagnose(issue)
            if diagnosis:
                diagnoses.append(diagnosis)
            elif self.remaining_budget <= 0:
                deferred_count += 1

        if deferred_count > 0:
            logger.warning(
                "issues_deferred_budget_exhausted",
                deferred_count=deferred_count,
                total_spend=self._cycle_spend,
            )

        return diagnoses

    def _estimate_cost(self) -> float:
        """Estimate cost of a single diagnosis call.

        Based on expected token usage with 20% safety margin.
        """
        # Context: issue metrics (~200 tokens) + sample calls (5 * 500) + system prompt (1000)
        estimated_input_tokens = 200 + (5 * 500) + 1000
        estimated_output_tokens = 500

        # Approximate strong-tier pricing (conservative)
        input_price_per_1k = 0.015
        output_price_per_1k = 0.075

        cost = (
            (estimated_input_tokens / 1000 * input_price_per_1k)
            + (estimated_output_tokens / 1000 * output_price_per_1k)
        )
        return cost * 1.2  # 20% safety margin

    def _build_diagnosis_prompt(self, issue: DetectedIssue) -> str:
        """Build the user prompt for diagnosis."""
        context_parts = [
            f"## Issue Details",
            f"- Type: {issue.issue_type.value}",
            f"- Task: {issue.task}" if issue.task else f"- Model: {issue.model}",
            f"- Severity: {issue.severity.value}",
            f"- Description: {issue.description}",
            f"- Current Value: {issue.current_value:.4f}",
            f"- Threshold: {issue.threshold_value:.4f}",
            f"- Baseline: {issue.baseline_value:.4f}",
            f"- Sample Count: {issue.sample_count}",
            f"",
            f"## Metrics Context",
            json.dumps(issue.metrics, indent=2, default=str),
        ]
        return "\n".join(context_parts)

    async def _call_llm(self, user_prompt: str) -> dict[str, Any]:
        """Call the LLM gateway with a diagnosis request."""
        if not self._http_client:
            raise ValueError("DiagnosisEngine not started (call start() first)")

        payload = {
            "messages": [
                {"role": "system", "content": DIAGNOSIS_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "task": "complex_reasoning",
            "agent": "observer",
            "max_tokens": 1000,
        }

        response = await self._http_client.post("/v1/complete", json=payload)

        if response.status_code != 200:
            raise ValueError(
                f"LLM gateway returned {response.status_code}: {response.text}"
            )

        return response.json()

    def _parse_diagnosis_response(
        self,
        issue: DetectedIssue,
        response_content: str,
        cost: float,
    ) -> Diagnosis | None:
        """Parse the LLM response into a Diagnosis object."""
        try:
            # Try to extract JSON from the response
            content = response_content.strip()
            # Handle markdown code blocks
            if content.startswith("```"):
                lines = content.split("\n")
                json_lines = []
                in_block = False
                for line in lines:
                    if line.startswith("```") and not in_block:
                        in_block = True
                        continue
                    elif line.startswith("```") and in_block:
                        break
                    elif in_block:
                        json_lines.append(line)
                content = "\n".join(json_lines)

            data = json.loads(content)

            return Diagnosis(
                issue_id=issue.id,
                root_cause=str(data.get("root_cause", "")),
                fix_type=str(data.get("fix_type", "")),
                fix_description=str(data.get("fix_description", "")),
                confidence=float(data.get("confidence", 0.0)),
                requires_prompt_rewrite=bool(data.get("requires_prompt_rewrite", False)),
                cost_usd=cost,
                raw_response=response_content,
            )
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            logger.error(
                "diagnosis_parse_failed",
                issue_id=issue.id,
                error=str(exc),
                response_preview=response_content[:200],
            )
            return None
