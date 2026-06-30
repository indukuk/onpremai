"""Tests for Layer 2: LLM judgment node.

Tests the evaluation_node handling of:
- Normal LLM judgment flow
- Credit exhaustion (marks remaining criteria as INSUFFICIENT_EVIDENCE)
- LLM unavailability (marks criterion as CANNOT_ASSESS)
- JSON response parsing (valid, malformed, text fallback)
- Consensus voting for high-weight criteria
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "agent-eval"))

from src.models import (
    Criterion,
    CriterionResult,
    CriterionResultEnum,
    EvalMethod,
    EvidenceMetadata,
    LayerStats,
    TestingCriteria,
    TimingStats,
)


# ---------------------------------------------------------------------------
# Mock settings
# ---------------------------------------------------------------------------


class FakeSettings:
    consensus_weight_threshold = 0.20
    consensus_sample_count = 3
    tribunal_confidence_threshold = 0.70
    tribunal_max_retries = 1


# ---------------------------------------------------------------------------
# RESPONSE PARSING TESTS
# ---------------------------------------------------------------------------


class TestParseJudgmentResponse:
    """Tests for _parse_judgment_response."""

    def _criterion(self, id="C1", category="implementation", weight=0.1):
        return Criterion(
            id=id,
            category=category,
            question="Test",
            evidence_type="document",
            pass_condition="Test",
            fail_condition="Test",
            weight=weight,
        )

    def test_parse_valid_json_pass(self):
        from src.graph.evaluation import _parse_judgment_response

        content = '{"result": "PASS", "reason": "Evidence clearly demonstrates compliance"}'
        result = _parse_judgment_response(content, self._criterion())

        assert result.result == CriterionResultEnum.PASS
        assert result.method == EvalMethod.LLM_JUDGMENT
        assert "compliance" in result.reason

    def test_parse_valid_json_fail(self):
        from src.graph.evaluation import _parse_judgment_response

        content = '{"result": "FAIL", "reason": "No evidence of control"}'
        result = _parse_judgment_response(content, self._criterion())

        assert result.result == CriterionResultEnum.FAIL

    def test_parse_valid_json_partial(self):
        from src.graph.evaluation import _parse_judgment_response

        content = '{"result": "PARTIAL", "reason": "Some gaps exist"}'
        result = _parse_judgment_response(content, self._criterion())

        assert result.result == CriterionResultEnum.PARTIAL

    def test_parse_markdown_wrapped_json(self):
        from src.graph.evaluation import _parse_judgment_response

        content = '```json\n{"result": "PASS", "reason": "Evidence satisfies"}\n```'
        result = _parse_judgment_response(content, self._criterion())

        assert result.result == CriterionResultEnum.PASS

    def test_parse_malformed_json_fallback_pass(self):
        from src.graph.evaluation import _parse_judgment_response

        content = "Based on my analysis, this is a PASS because evidence clearly shows compliance."
        result = _parse_judgment_response(content, self._criterion())

        assert result.result == CriterionResultEnum.PASS

    def test_parse_malformed_json_fallback_fail(self):
        from src.graph.evaluation import _parse_judgment_response

        content = "The evidence is insufficient and this does not meet requirements."
        result = _parse_judgment_response(content, self._criterion())

        assert result.result == CriterionResultEnum.FAIL

    def test_parse_malformed_json_fallback_partial(self):
        from src.graph.evaluation import _parse_judgment_response

        content = "This is a partial match. Some requirements are met but not all."
        result = _parse_judgment_response(content, self._criterion())

        assert result.result == CriterionResultEnum.PARTIAL

    def test_parse_empty_content(self):
        from src.graph.evaluation import _parse_judgment_response

        content = ""
        result = _parse_judgment_response(content, self._criterion())

        assert result.result == CriterionResultEnum.FAIL
        assert "Unable to parse" in result.reason


# ---------------------------------------------------------------------------
# EVALUATION NODE TESTS
# ---------------------------------------------------------------------------


class TestEvaluationNode:
    """Tests for the evaluation_node graph node."""

    def _make_state(
        self,
        needs_judgment: list[str],
        criteria: list[Criterion] | None = None,
        evidence_metadata: list[EvidenceMetadata] | None = None,
    ) -> dict[str, Any]:
        if criteria is None:
            criteria = [
                Criterion(
                    id="C1",
                    category="implementation",
                    question="Is access enforced?",
                    evidence_type="document",
                    pass_condition="Policy exists",
                    fail_condition="No policy",
                    weight=0.15,
                ),
                Criterion(
                    id="C2",
                    category="implementation",
                    question="Are logs maintained?",
                    evidence_type="document",
                    pass_condition="Logs exist",
                    fail_condition="No logs",
                    weight=0.15,
                ),
                Criterion(
                    id="C3",
                    category="implementation",
                    question="Are reviews documented?",
                    evidence_type="document",
                    pass_condition="Reviews documented",
                    fail_condition="No documentation",
                    weight=0.15,
                ),
            ]
        if evidence_metadata is None:
            evidence_metadata = [
                EvidenceMetadata(
                    storage_key="evidence/policy.pdf",
                    file_type="pdf",
                    text_content="Access control policy defines user provisioning.",
                ),
            ]
        return {
            "needs_judgment": needs_judgment,
            "testing_criteria": TestingCriteria(
                control_id="CC6.1",
                framework="SOC2",
                control_objective="Test",
                criteria=criteria,
            ),
            "evidence_metadata": evidence_metadata,
            "rule_results": {},
            "tenant_id": "tenant-001",
            "trace_id": "trace-test",
            "layer_stats": LayerStats(layer1_resolved=2, total_criteria=3),
            "timing": TimingStats(discovery_ms=5.0, extraction_ms=10.0, layer1_ms=15.0),
        }

    @pytest.mark.asyncio
    async def test_no_needs_judgment_returns_empty(self):
        """Returns empty judgment_results when no criteria need judgment."""
        from src.graph.evaluation import evaluation_node

        state = self._make_state(needs_judgment=[])

        with patch("src.graph.evaluation.get_settings", return_value=FakeSettings()):
            result = await evaluation_node(state)

        assert result["judgment_results"] == {}
        assert result["partial_evaluation"] is False

    @pytest.mark.asyncio
    async def test_normal_judgment_flow(self):
        """Normal flow: tribunal returns valid verdicts for each criterion."""
        from src.graph.evaluation import evaluation_node

        # Mock LLM: Prosecutor returns arguments, Judge returns PASS verdict
        call_count = [0]

        async def mock_complete(**kwargs):
            call_count[0] += 1
            task = kwargs.get("task", "")
            if task == "evaluate_prosecute":
                return MagicMock(content='{"arguments": ["Minor gap noted"], "severity": "low"}')
            elif task == "evaluate_judge":
                return MagicMock(content='{"verdict": "PASS", "prosecution_points_accepted": [], "prosecution_points_rejected": ["Minor gap noted"], "defense_points_accepted": [], "defense_points_rejected": [], "justification": "Evidence sufficient", "confidence": 0.9}')
            return MagicMock(content='{"result": "PASS", "reason": "Evidence sufficient"}')

        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(side_effect=mock_complete)
        mock_llm.close = AsyncMock()

        mock_memory = AsyncMock()
        mock_memory.close = AsyncMock()

        state = self._make_state(needs_judgment=["C1", "C2"])

        with (
            patch("src.graph.evaluation.get_settings", return_value=FakeSettings()),
            patch("src.graph.evaluation.LLMClient", return_value=mock_llm),
            patch("src.graph.evaluation.MemoryClient", return_value=mock_memory),
        ):
            result = await evaluation_node(state)

        assert "C1" in result["judgment_results"]
        assert "C2" in result["judgment_results"]
        assert result["judgment_results"]["C1"].result == CriterionResultEnum.PASS
        assert result["partial_evaluation"] is False

    @pytest.mark.asyncio
    async def test_credit_exhaustion_marks_insufficient_evidence(self):
        """Credit exhaustion marks remaining criteria as INSUFFICIENT_EVIDENCE."""
        from common.errors import LLMCreditExhaustedError

        from src.graph.evaluation import evaluation_node

        mock_llm = AsyncMock()
        call_count = [0]

        async def complete_side_effect(**kwargs):
            call_count[0] += 1
            task = kwargs.get("task", "")
            # Let first criterion's tribunal complete (2 calls for simplified)
            if call_count[0] <= 2:
                if task == "evaluate_prosecute":
                    return MagicMock(content='{"arguments": ["OK"], "severity": "low"}')
                return MagicMock(content='{"verdict": "PASS", "prosecution_points_accepted": [], "prosecution_points_rejected": [], "defense_points_accepted": [], "defense_points_rejected": [], "justification": "OK", "confidence": 0.9}')
            # Then exhaust on next criterion
            raise LLMCreditExhaustedError(
                "Budget exhausted", degradation_level=2
            )

        mock_llm.complete = AsyncMock(side_effect=complete_side_effect)
        mock_llm.close = AsyncMock()

        mock_memory = AsyncMock()
        mock_memory.close = AsyncMock()

        state = self._make_state(needs_judgment=["C1", "C2", "C3"])

        with (
            patch("src.graph.evaluation.get_settings", return_value=FakeSettings()),
            patch("src.graph.evaluation.LLMClient", return_value=mock_llm),
            patch("src.graph.evaluation.MemoryClient", return_value=mock_memory),
        ):
            result = await evaluation_node(state)

        # C1 should have been evaluated before exhaustion
        assert result["judgment_results"]["C1"].result == CriterionResultEnum.PASS
        # C2 and C3 should be marked INSUFFICIENT_EVIDENCE
        assert result["judgment_results"]["C2"].result == CriterionResultEnum.INSUFFICIENT_EVIDENCE
        assert result["judgment_results"]["C3"].result == CriterionResultEnum.INSUFFICIENT_EVIDENCE
        assert result["partial_evaluation"] is True
        # Check reason includes degradation info
        assert "budget exhausted" in result["judgment_results"]["C2"].reason.lower()

    @pytest.mark.asyncio
    async def test_llm_unavailable_marks_cannot_assess(self):
        """LLM unavailability marks the criterion as CANNOT_ASSESS."""
        from common.errors import LLMUnavailableError

        from src.graph.evaluation import evaluation_node

        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(
            side_effect=LLMUnavailableError("Gateway down")
        )
        mock_llm.close = AsyncMock()

        mock_memory = AsyncMock()
        mock_memory.close = AsyncMock()

        state = self._make_state(needs_judgment=["C1"])

        with (
            patch("src.graph.evaluation.get_settings", return_value=FakeSettings()),
            patch("src.graph.evaluation.LLMClient", return_value=mock_llm),
            patch("src.graph.evaluation.MemoryClient", return_value=mock_memory),
        ):
            result = await evaluation_node(state)

        assert result["judgment_results"]["C1"].result == CriterionResultEnum.CANNOT_ASSESS
        assert result["judgment_results"]["C1"].method == EvalMethod.DEGRADED

    @pytest.mark.asyncio
    async def test_full_tribunal_for_high_weight(self):
        """High-weight criteria use full adversarial tribunal (3 models)."""
        from src.graph.evaluation import evaluation_node

        high_weight_criteria = [
            Criterion(
                id="C1",
                category="policy",
                question="Critical question",
                evidence_type="document",
                pass_condition="Must pass",
                fail_condition="Must not fail",
                weight=0.30,  # Above consensus_weight_threshold of 0.20
            ),
        ]

        mock_llm = AsyncMock()

        async def tribunal_complete(**kwargs):
            task = kwargs.get("task", "")
            if task == "evaluate_prosecute":
                return MagicMock(content='{"arguments": ["Minor concern"], "severity": "low"}')
            elif task == "evaluate_defend":
                return MagicMock(content='{"arguments": ["Strong evidence found"], "strength": "high"}')
            elif task == "evaluate_judge":
                return MagicMock(content='{"verdict": "PASS", "prosecution_points_accepted": [], "prosecution_points_rejected": ["Minor concern"], "defense_points_accepted": ["Strong evidence found"], "defense_points_rejected": [], "justification": "Defense prevails", "confidence": 0.92}')
            return MagicMock(content='{"result": "PASS", "reason": "OK"}')

        mock_llm.complete = AsyncMock(side_effect=tribunal_complete)
        mock_llm.close = AsyncMock()

        mock_memory = AsyncMock()
        mock_memory.close = AsyncMock()

        state = self._make_state(
            needs_judgment=["C1"],
            criteria=high_weight_criteria,
        )

        with (
            patch("src.graph.evaluation.get_settings", return_value=FakeSettings()),
            patch("src.graph.evaluation.LLMClient", return_value=mock_llm),
            patch("src.graph.evaluation.MemoryClient", return_value=mock_memory),
        ):
            result = await evaluation_node(state)

        assert result["judgment_results"]["C1"].result == CriterionResultEnum.PASS
        assert result["judgment_results"]["C1"].confidence == pytest.approx(0.92, rel=0.01)
        # Full tribunal: 3 calls (prosecutor + defender + judge)
        assert mock_llm.complete.call_count == 3

    @pytest.mark.asyncio
    async def test_timing_stats_populated(self):
        """Timing stats include layer2_ms after evaluation."""
        from src.graph.evaluation import evaluation_node

        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(
            return_value=MagicMock(content='{"result": "PASS", "reason": "OK"}')
        )
        mock_llm.close = AsyncMock()

        mock_memory = AsyncMock()
        mock_memory.close = AsyncMock()

        state = self._make_state(needs_judgment=["C1"])

        with (
            patch("src.graph.evaluation.get_settings", return_value=FakeSettings()),
            patch("src.graph.evaluation.LLMClient", return_value=mock_llm),
            patch("src.graph.evaluation.MemoryClient", return_value=mock_memory),
        ):
            result = await evaluation_node(state)

        assert result["timing"].layer2_ms > 0
        assert result["layer_stats"].layer2_resolved == 1


# ---------------------------------------------------------------------------
# EVIDENCE EXTRACTION TESTS
# ---------------------------------------------------------------------------


class TestExtractRelevantEvidence:
    """Tests for _extract_relevant_evidence helper."""

    def test_document_evidence_extraction(self):
        from src.graph.evaluation import _extract_relevant_evidence

        criterion = Criterion(
            id="C1",
            category="policy",
            question="Test",
            evidence_type="document",
            pass_condition="Test",
            fail_condition="Test",
            weight=0.1,
        )
        metadata = [
            EvidenceMetadata(
                storage_key="policy.pdf",
                file_type="pdf",
                text_content="This is the access control policy content.",
            ),
        ]

        text = _extract_relevant_evidence(criterion, metadata)

        assert "access control policy" in text
        assert "[policy.pdf]" in text

    def test_structured_data_evidence_extraction(self):
        from src.graph.evaluation import _extract_relevant_evidence

        criterion = Criterion(
            id="C1",
            category="implementation",
            question="Test",
            evidence_type="structured_data",
            pass_condition="Test",
            fail_condition="Test",
            weight=0.1,
        )
        metadata = [
            EvidenceMetadata(
                storage_key="access_log.csv",
                file_type="csv",
                columns=["user_id", "action", "timestamp"],
                row_count=150,
            ),
        ]

        text = _extract_relevant_evidence(criterion, metadata)

        assert "access_log.csv" in text
        assert "Columns:" in text
        assert "Row count: 150" in text

    def test_no_matching_evidence_returns_empty(self):
        from src.graph.evaluation import _extract_relevant_evidence

        criterion = Criterion(
            id="C1",
            category="implementation",
            question="Test",
            evidence_type="document",
            pass_condition="Test",
            fail_condition="Test",
            weight=0.1,
        )
        metadata = [
            EvidenceMetadata(
                storage_key="data.csv",
                file_type="csv",
                row_count=10,
            ),
        ]

        text = _extract_relevant_evidence(criterion, metadata)

        assert text == ""

    def test_limits_to_five_evidence_pieces(self):
        from src.graph.evaluation import _extract_relevant_evidence

        criterion = Criterion(
            id="C1",
            category="policy",
            question="Test",
            evidence_type="document",
            pass_condition="Test",
            fail_condition="Test",
            weight=0.1,
        )
        metadata = [
            EvidenceMetadata(
                storage_key=f"doc_{i}.pdf",
                file_type="pdf",
                text_content=f"Content for document {i}",
            )
            for i in range(10)
        ]

        text = _extract_relevant_evidence(criterion, metadata)

        # Should contain at most 5 evidence pieces
        assert text.count("[doc_") <= 5
