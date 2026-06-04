from __future__ import annotations

import json
from typing import Any

import structlog

from src.models import CompletionRequest, EscalationConfig, NormalizedResponse

logger = structlog.get_logger(__name__)


class EscalationDecision:
    """Result of an escalation check."""

    def __init__(
        self,
        should_escalate: bool,
        reason: str = "",
        confidence: float = 0.0,
    ) -> None:
        self.should_escalate = should_escalate
        self.reason = reason
        self.confidence = confidence


class EscalationEngine:
    """Handles confidence-based escalation between tiers.

    Escalation is triggered when:
    - Agent declares confidence_threshold AND response confidence < threshold
    - Response is empty or unparseable
    - Structured output doesn't match requested schema
    - Model returns a refusal

    Escalation path: fast -> mid -> strong
    Max escalations per request: configurable (default 2)
    """

    def __init__(self, config: EscalationConfig) -> None:
        self._config = config

    def update_config(self, config: EscalationConfig) -> None:
        """Update escalation configuration."""
        self._config = config

    @property
    def enabled(self) -> bool:
        """Whether escalation is enabled globally."""
        return self._config.enabled

    @property
    def max_escalations(self) -> int:
        """Maximum number of escalations per request."""
        return self._config.max_escalations

    def check(
        self,
        response: NormalizedResponse,
        request: CompletionRequest,
        escalation_count: int,
    ) -> EscalationDecision:
        """Determine if a response should trigger escalation.

        Args:
            response: The normalized response from the current model.
            request: The original completion request.
            escalation_count: How many escalations have already occurred.

        Returns:
            EscalationDecision indicating whether to escalate.
        """
        if not self._config.enabled:
            confidence = self.extract_confidence(response, request)
            return EscalationDecision(
                should_escalate=False,
                confidence=confidence,
            )

        if escalation_count >= self._config.max_escalations:
            confidence = self.extract_confidence(response, request)
            return EscalationDecision(
                should_escalate=False,
                reason="max_escalations_reached",
                confidence=confidence,
            )

        # Check for empty response (before confidence — empty yields 0.0 confidence)
        if self._is_empty_response(response):
            return EscalationDecision(
                should_escalate=True,
                reason="empty_response",
                confidence=0.0,
            )

        # Check for refusal (before confidence — refusals are short, low heuristic score)
        if self._is_refusal(response):
            return EscalationDecision(
                should_escalate=True,
                reason="model_refusal",
                confidence=0.1,
            )

        # Check for parse failure on expected JSON
        if self._is_json_parse_failure(response, request):
            return EscalationDecision(
                should_escalate=True,
                reason="json_parse_failure",
                confidence=0.3,
            )

        confidence = self.extract_confidence(response, request)

        # Check confidence threshold
        if request.confidence_threshold > 0 and confidence < request.confidence_threshold:
            return EscalationDecision(
                should_escalate=True,
                reason=f"confidence {confidence:.2f} < threshold {request.confidence_threshold:.2f}",
                confidence=confidence,
            )

        return EscalationDecision(
            should_escalate=False,
            confidence=confidence,
        )

    def extract_confidence(
        self,
        response: NormalizedResponse,
        request: CompletionRequest,
    ) -> float:
        """Extract confidence from a response.

        Strategy:
        1. If response contains JSON with a 'confidence' field -> use it
        2. If structured_output schema has confidence -> extract it
        3. Otherwise: heuristic scoring
        """
        # Try to extract explicit confidence from JSON response
        explicit = self._extract_explicit_confidence(response)
        if explicit is not None:
            return explicit

        # Heuristic scoring
        return self._heuristic_confidence(response, request)

    def _extract_explicit_confidence(self, response: NormalizedResponse) -> float | None:
        """Try to extract a confidence field from JSON response content."""
        if not response.content:
            return None

        content = response.content.strip()

        # Try direct JSON parse
        try:
            data = json.loads(content)
            if isinstance(data, dict) and "confidence" in data:
                conf = data["confidence"]
                if isinstance(conf, (int, float)):
                    return max(0.0, min(1.0, float(conf)))
        except (json.JSONDecodeError, ValueError):
            pass

        # Try to find JSON block within markdown code fences
        if "```json" in content:
            start = content.find("```json") + 7
            end = content.find("```", start)
            if end > start:
                json_block = content[start:end].strip()
                try:
                    data = json.loads(json_block)
                    if isinstance(data, dict) and "confidence" in data:
                        conf = data["confidence"]
                        if isinstance(conf, (int, float)):
                            return max(0.0, min(1.0, float(conf)))
                except (json.JSONDecodeError, ValueError):
                    pass

        return None

    def _heuristic_confidence(
        self,
        response: NormalizedResponse,
        request: CompletionRequest,
    ) -> float:
        """Apply heuristic confidence scoring.

        - Empty response -> confidence 0.0
        - Parse failure on expected JSON -> confidence 0.3
        - Very short response (< 50 chars) for complex task -> confidence 0.4
        - Normal response -> confidence 0.8 (assumed)
        """
        if self._is_empty_response(response):
            return 0.0

        if self._is_json_parse_failure(response, request):
            return 0.3

        # Short response heuristic
        content = response.content or ""
        is_complex_task = request.task in (
            "evaluate_control",
            "evaluate_unstructured",
            "complex_reasoning",
            "cross_framework_analysis",
            "generate_code",
        )
        if len(content) < 50 and is_complex_task:
            return 0.4

        return 0.8

    def _is_empty_response(self, response: NormalizedResponse) -> bool:
        """Check if response is effectively empty."""
        has_content = response.content and response.content.strip()
        has_tool_calls = response.tool_calls and len(response.tool_calls) > 0
        return not has_content and not has_tool_calls

    def _is_json_parse_failure(
        self,
        response: NormalizedResponse,
        request: CompletionRequest,
    ) -> bool:
        """Check if response should be JSON but isn't parseable."""
        # Only check if JSON format was requested
        if not request.response_format:
            return False
        if request.response_format.type not in ("json_object", "json_schema"):
            return False

        content = response.content
        if not content:
            return True

        try:
            json.loads(content.strip())
            return False
        except (json.JSONDecodeError, ValueError):
            # Try stripping markdown code fences
            stripped = content.strip()
            if stripped.startswith("```"):
                lines = stripped.split("\n")
                inner = "\n".join(lines[1:-1]) if len(lines) > 2 else ""
                try:
                    json.loads(inner)
                    return False
                except (json.JSONDecodeError, ValueError):
                    pass
            return True

    def _is_refusal(self, response: NormalizedResponse) -> bool:
        """Detect if the model refused to answer."""
        content = (response.content or "").lower()
        refusal_indicators = [
            "i cannot",
            "i'm unable to",
            "i am unable to",
            "i can't help",
            "i'm not able to",
            "as an ai",
            "i don't have the ability",
            "i must decline",
        ]
        # Only flag as refusal if the response is short and contains indicators
        if len(content) > 200:
            return False
        return any(indicator in content for indicator in refusal_indicators)

    def get_next_tier(self, current_tier: str) -> str | None:
        """Get the next tier in the escalation path.

        Returns None if already at highest tier.
        """
        path = self._config.path
        try:
            idx = path.index(current_tier)
            if idx + 1 < len(path):
                return path[idx + 1]
        except ValueError:
            pass
        return None
