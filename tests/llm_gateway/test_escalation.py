"""Tests for llm-gateway escalation engine.

Tests confidence extraction, escalation decision logic, and tier escalation.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "llm-gateway"))

from src.escalation import EscalationDecision, EscalationEngine
from src.models import (
    CompletionRequest,
    EscalationConfig,
    Message,
    MessageRole,
    NormalizedResponse,
    ResponseFormat,
    ToolCall,
    ToolCallFunction,
    Usage,
)


@pytest.fixture
def engine(escalation_config: EscalationConfig) -> EscalationEngine:
    """Standard escalation engine."""
    return EscalationEngine(escalation_config)


@pytest.fixture
def disabled_engine() -> EscalationEngine:
    """Escalation engine with escalation disabled."""
    config = EscalationConfig(enabled=False, max_escalations=2, path=["fast", "mid", "strong"])
    return EscalationEngine(config)


@pytest.fixture
def request_with_threshold() -> CompletionRequest:
    """Request with confidence threshold set."""
    return CompletionRequest(
        messages=[Message(role=MessageRole.USER, content="Evaluate this control.")],
        task="evaluate_control",
        agent="agent-eval",
        tenant_id="t1",
        confidence_threshold=0.7,
    )


@pytest.fixture
def request_no_threshold() -> CompletionRequest:
    """Request with no confidence threshold."""
    return CompletionRequest(
        messages=[Message(role=MessageRole.USER, content="Summarize this.")],
        task="summarize",
        agent="agent-eval",
        tenant_id="t1",
        confidence_threshold=0.0,
    )


@pytest.fixture
def request_json_format() -> CompletionRequest:
    """Request expecting JSON response format."""
    return CompletionRequest(
        messages=[Message(role=MessageRole.USER, content="Return JSON.")],
        task="evaluate_control",
        agent="agent-eval",
        tenant_id="t1",
        confidence_threshold=0.7,
        response_format=ResponseFormat(type="json_object"),
    )


class TestConfidenceExtraction:
    """Tests for extract_confidence method."""

    def test_extract_from_json_response(
        self, engine: EscalationEngine, request_with_threshold: CompletionRequest
    ) -> None:
        """Extracts confidence from JSON response body."""
        response = NormalizedResponse(
            content='{"result": "compliant", "confidence": 0.92}',
            usage=Usage(input_tokens=100, output_tokens=50),
        )
        confidence = engine.extract_confidence(response, request_with_threshold)
        assert confidence == 0.92

    def test_extract_from_json_in_markdown_fences(
        self, engine: EscalationEngine, request_with_threshold: CompletionRequest
    ) -> None:
        """Extracts confidence from JSON inside markdown code fences."""
        response = NormalizedResponse(
            content='Here is the result:\n```json\n{"confidence": 0.85, "status": "ok"}\n```',
            usage=Usage(input_tokens=100, output_tokens=50),
        )
        confidence = engine.extract_confidence(response, request_with_threshold)
        assert confidence == 0.85

    def test_extract_clamps_to_0_1_range(
        self, engine: EscalationEngine, request_with_threshold: CompletionRequest
    ) -> None:
        """Confidence is clamped between 0.0 and 1.0."""
        response = NormalizedResponse(
            content='{"confidence": 1.5}',
            usage=Usage(input_tokens=100, output_tokens=50),
        )
        confidence = engine.extract_confidence(response, request_with_threshold)
        assert confidence == 1.0

        response_neg = NormalizedResponse(
            content='{"confidence": -0.5}',
            usage=Usage(input_tokens=100, output_tokens=50),
        )
        confidence_neg = engine.extract_confidence(response_neg, request_with_threshold)
        assert confidence_neg == 0.0

    def test_heuristic_empty_response_gives_zero(
        self, engine: EscalationEngine, request_with_threshold: CompletionRequest
    ) -> None:
        """Empty response yields confidence 0.0."""
        response = NormalizedResponse(content="", usage=Usage())
        confidence = engine.extract_confidence(response, request_with_threshold)
        assert confidence == 0.0

    def test_heuristic_none_content_gives_zero(
        self, engine: EscalationEngine, request_with_threshold: CompletionRequest
    ) -> None:
        """None content yields confidence 0.0."""
        response = NormalizedResponse(content=None, usage=Usage())
        confidence = engine.extract_confidence(response, request_with_threshold)
        assert confidence == 0.0

    def test_heuristic_short_response_complex_task(
        self, engine: EscalationEngine, request_with_threshold: CompletionRequest
    ) -> None:
        """Short response (<50 chars) for complex task -> confidence 0.4."""
        response = NormalizedResponse(
            content="OK",
            usage=Usage(input_tokens=100, output_tokens=5),
        )
        confidence = engine.extract_confidence(response, request_with_threshold)
        assert confidence == 0.4

    def test_heuristic_normal_response(
        self, engine: EscalationEngine, request_no_threshold: CompletionRequest
    ) -> None:
        """Normal-length response without explicit confidence -> 0.8."""
        response = NormalizedResponse(
            content="This is a sufficiently long response that should not trigger any special heuristic for confidence scoring in the engine.",
            usage=Usage(input_tokens=100, output_tokens=50),
        )
        confidence = engine.extract_confidence(response, request_no_threshold)
        assert confidence == 0.8

    def test_heuristic_json_parse_failure_with_format(
        self, engine: EscalationEngine, request_json_format: CompletionRequest
    ) -> None:
        """Non-JSON response when JSON was requested -> confidence 0.3."""
        response = NormalizedResponse(
            content="I cannot parse this as structured data because it is too ambiguous.",
            usage=Usage(input_tokens=100, output_tokens=50),
        )
        confidence = engine.extract_confidence(response, request_json_format)
        assert confidence == 0.3

    def test_extract_confidence_integer_value(
        self, engine: EscalationEngine, request_with_threshold: CompletionRequest
    ) -> None:
        """Integer confidence value (e.g. 1) is accepted."""
        response = NormalizedResponse(
            content='{"confidence": 1}',
            usage=Usage(input_tokens=100, output_tokens=50),
        )
        confidence = engine.extract_confidence(response, request_with_threshold)
        assert confidence == 1.0


class TestEscalationCheck:
    """Tests for the check() decision method."""

    def test_escalate_on_low_confidence(
        self, engine: EscalationEngine, request_with_threshold: CompletionRequest
    ) -> None:
        """Escalates when confidence < threshold."""
        response = NormalizedResponse(
            content='{"confidence": 0.5, "result": "unclear"}',
            usage=Usage(input_tokens=100, output_tokens=50),
        )
        decision = engine.check(response, request_with_threshold, escalation_count=0)
        assert decision.should_escalate is True
        assert "confidence" in decision.reason
        assert decision.confidence == 0.5

    def test_no_escalation_when_above_threshold(
        self, engine: EscalationEngine, request_with_threshold: CompletionRequest
    ) -> None:
        """No escalation when confidence >= threshold."""
        response = NormalizedResponse(
            content='{"confidence": 0.85, "result": "compliant"}',
            usage=Usage(input_tokens=100, output_tokens=50),
        )
        decision = engine.check(response, request_with_threshold, escalation_count=0)
        assert decision.should_escalate is False
        assert decision.confidence == 0.85

    def test_escalate_on_empty_response(
        self, engine: EscalationEngine, request_with_threshold: CompletionRequest
    ) -> None:
        """Empty response triggers escalation."""
        response = NormalizedResponse(content="", usage=Usage())
        decision = engine.check(response, request_with_threshold, escalation_count=0)
        assert decision.should_escalate is True
        assert decision.reason == "empty_response"
        assert decision.confidence == 0.0

    def test_escalate_on_json_parse_failure(
        self, engine: EscalationEngine, request_json_format: CompletionRequest
    ) -> None:
        """Non-parseable JSON when JSON format was requested triggers escalation."""
        response = NormalizedResponse(
            content="This is not JSON at all, just plain text.",
            usage=Usage(input_tokens=100, output_tokens=50),
        )
        decision = engine.check(response, request_json_format, escalation_count=0)
        assert decision.should_escalate is True
        assert decision.reason == "json_parse_failure"

    def test_no_escalation_for_valid_json(
        self, engine: EscalationEngine, request_json_format: CompletionRequest
    ) -> None:
        """Valid JSON response with confidence above threshold does not escalate."""
        response = NormalizedResponse(
            content='{"confidence": 0.9, "result": "pass"}',
            usage=Usage(input_tokens=100, output_tokens=50),
        )
        decision = engine.check(response, request_json_format, escalation_count=0)
        assert decision.should_escalate is False

    def test_escalate_on_model_refusal(
        self, engine: EscalationEngine, request_with_threshold: CompletionRequest
    ) -> None:
        """Model refusal triggers escalation."""
        response = NormalizedResponse(
            content="I cannot help with that request.",
            usage=Usage(input_tokens=100, output_tokens=10),
        )
        decision = engine.check(response, request_with_threshold, escalation_count=0)
        assert decision.should_escalate is True
        assert decision.reason == "model_refusal"

    def test_no_refusal_for_long_responses(
        self, engine: EscalationEngine, request_with_threshold: CompletionRequest
    ) -> None:
        """Long responses containing refusal phrases are NOT flagged as refusals."""
        long_content = "I cannot help with that " + "x" * 200
        response = NormalizedResponse(
            content=long_content,
            usage=Usage(input_tokens=100, output_tokens=200),
        )
        # This won't trigger refusal because len > 200
        decision = engine.check(response, request_with_threshold, escalation_count=0)
        # It might still escalate due to low confidence heuristic, but reason won't be refusal
        assert decision.reason != "model_refusal"

    def test_max_escalations_prevents_further_escalation(
        self, engine: EscalationEngine, request_with_threshold: CompletionRequest
    ) -> None:
        """No escalation when max_escalations already reached."""
        response = NormalizedResponse(
            content='{"confidence": 0.3}',
            usage=Usage(input_tokens=100, output_tokens=50),
        )
        decision = engine.check(response, request_with_threshold, escalation_count=2)
        assert decision.should_escalate is False
        assert decision.reason == "max_escalations_reached"

    def test_disabled_engine_never_escalates(
        self,
        disabled_engine: EscalationEngine,
        request_with_threshold: CompletionRequest,
    ) -> None:
        """Disabled escalation engine never recommends escalation."""
        response = NormalizedResponse(content="", usage=Usage())
        decision = disabled_engine.check(response, request_with_threshold, escalation_count=0)
        assert decision.should_escalate is False

    def test_no_threshold_no_confidence_escalation(
        self, engine: EscalationEngine, request_no_threshold: CompletionRequest
    ) -> None:
        """When threshold is 0, confidence-based escalation doesn't trigger."""
        response = NormalizedResponse(
            content="A sufficiently long normal response without any JSON structure that should pass.",
            usage=Usage(input_tokens=100, output_tokens=50),
        )
        decision = engine.check(response, request_no_threshold, escalation_count=0)
        assert decision.should_escalate is False

    def test_tool_call_response_not_empty(
        self, engine: EscalationEngine, request_with_threshold: CompletionRequest
    ) -> None:
        """Response with tool calls is not considered empty."""
        response = NormalizedResponse(
            content=None,
            tool_calls=[
                ToolCall(
                    id="call_1",
                    type="function",
                    function=ToolCallFunction(name="search", arguments='{"q": "test"}'),
                )
            ],
            usage=Usage(input_tokens=100, output_tokens=50),
        )
        decision = engine.check(response, request_with_threshold, escalation_count=0)
        # Not empty, and no confidence threshold check triggers (confidence is heuristic 0.8)
        assert decision.reason != "empty_response"


class TestGetNextTier:
    """Tests for tier escalation path navigation."""

    def test_fast_to_mid(self, engine: EscalationEngine) -> None:
        """fast -> mid."""
        assert engine.get_next_tier("fast") == "mid"

    def test_mid_to_strong(self, engine: EscalationEngine) -> None:
        """mid -> strong."""
        assert engine.get_next_tier("mid") == "strong"

    def test_strong_is_terminal(self, engine: EscalationEngine) -> None:
        """strong -> None (no further escalation)."""
        assert engine.get_next_tier("strong") is None

    def test_unknown_tier(self, engine: EscalationEngine) -> None:
        """Unknown tier returns None."""
        assert engine.get_next_tier("unknown") is None


class TestEscalationEngineProperties:
    """Tests for engine property access."""

    def test_enabled_property(self, engine: EscalationEngine) -> None:
        assert engine.enabled is True

    def test_disabled_engine_enabled_property(self, disabled_engine: EscalationEngine) -> None:
        assert disabled_engine.enabled is False

    def test_max_escalations_property(self, engine: EscalationEngine) -> None:
        assert engine.max_escalations == 2

    def test_update_config(self, engine: EscalationEngine) -> None:
        """update_config swaps the configuration."""
        new_config = EscalationConfig(enabled=False, max_escalations=5, path=["fast", "strong"])
        engine.update_config(new_config)
        assert engine.enabled is False
        assert engine.max_escalations == 5
        assert engine.get_next_tier("fast") == "strong"


class TestJsonParseFailureEdgeCases:
    """Edge cases for JSON parse failure detection."""

    def test_json_in_code_fence_not_failure(self, engine: EscalationEngine) -> None:
        """JSON inside code fences is valid."""
        request = CompletionRequest(
            messages=[Message(role=MessageRole.USER, content="test")],
            task="test",
            agent="a",
            tenant_id="t",
            response_format=ResponseFormat(type="json_object"),
        )
        response = NormalizedResponse(
            content='```json\n{"result": "ok"}\n```',
            usage=Usage(),
        )
        decision = engine.check(response, request, escalation_count=0)
        assert decision.reason != "json_parse_failure"

    def test_no_format_requested_no_json_check(self, engine: EscalationEngine) -> None:
        """If no response_format requested, non-JSON is fine."""
        request = CompletionRequest(
            messages=[Message(role=MessageRole.USER, content="test")],
            task="summarize",
            agent="a",
            tenant_id="t",
            response_format=None,
        )
        response = NormalizedResponse(
            content="This is plain text, not JSON.",
            usage=Usage(input_tokens=50, output_tokens=20),
        )
        decision = engine.check(response, request, escalation_count=0)
        assert decision.reason != "json_parse_failure"

    def test_text_format_no_json_check(self, engine: EscalationEngine) -> None:
        """response_format type='text' does not trigger JSON check."""
        request = CompletionRequest(
            messages=[Message(role=MessageRole.USER, content="test")],
            task="summarize",
            agent="a",
            tenant_id="t",
            response_format=ResponseFormat(type="text"),
        )
        response = NormalizedResponse(
            content="Just text here.",
            usage=Usage(input_tokens=50, output_tokens=20),
        )
        decision = engine.check(response, request, escalation_count=0)
        assert decision.reason != "json_parse_failure"
