"""Shared fixtures for agent-eval tests.

Provides mock clients, sample evaluation data, and common test helpers.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure agent-eval src is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "agent-eval"))


# ---------------------------------------------------------------------------
# Mock common/ clients before importing any agent-eval modules
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_llm_client():
    """Mock LLMClient that returns configurable responses."""
    client = AsyncMock()
    client.complete = AsyncMock(
        return_value=MagicMock(
            content='{"result": "PASS", "reason": "Evidence satisfies requirement"}',
            model_used="anthropic.claude-3-haiku",
            tier_used="fast",
            tokens=150,
            latency=0.5,
        )
    )
    client.close = AsyncMock()
    return client


@pytest.fixture
def mock_memory_client():
    """Mock MemoryClient that returns empty context by default."""
    client = AsyncMock()
    client.tenant_recall = AsyncMock(return_value=[])
    client.eval_recall = AsyncMock(return_value=[])
    client.eval_store = AsyncMock()
    client.close = AsyncMock()
    return client


@pytest.fixture
def mock_storage_client():
    """Mock StorageClient that returns configurable file listings."""
    client = AsyncMock()
    client.list_objects = AsyncMock(return_value=[])
    client.get_json = AsyncMock(return_value={})
    client.close = AsyncMock()
    return client


# ---------------------------------------------------------------------------
# Sample data factories
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_criterion():
    """Factory for creating test Criterion instances."""
    from src.models import Criterion

    def _make(
        id: str = "C1",
        category: str = "implementation",
        question: str = "Is access control enforced?",
        evidence_type: str = "document",
        pass_condition: str = "Policy document exists",
        fail_condition: str = "No policy document found",
        weight: float = 0.1,
        check_type: str | None = None,
        check_params: dict[str, Any] | None = None,
    ) -> Criterion:
        return Criterion(
            id=id,
            category=category,
            question=question,
            evidence_type=evidence_type,
            pass_condition=pass_condition,
            fail_condition=fail_condition,
            weight=weight,
            check_type=check_type,
            check_params=check_params or {},
        )

    return _make


@pytest.fixture
def sample_testing_criteria(sample_criterion):
    """Factory for creating TestingCriteria with multiple criteria."""
    from src.models import TestingCriteria

    def _make(criteria=None, control_id="CC6.1", framework="SOC2"):
        if criteria is None:
            criteria = [
                sample_criterion(
                    id="C1",
                    category="policy",
                    check_type="file_existence",
                    evidence_type="document",
                    pass_condition="Access control policy exists",
                    weight=0.25,
                ),
                sample_criterion(
                    id="C2",
                    category="implementation",
                    check_type="row_count",
                    evidence_type="structured_data",
                    pass_condition="At least 1 record exists in access logs",
                    weight=0.25,
                ),
                sample_criterion(
                    id="C3",
                    category="implementation",
                    check_type="freshness",
                    evidence_type="document",
                    pass_condition="Reviewed within 12 months",
                    weight=0.25,
                ),
                sample_criterion(
                    id="C4",
                    category="implementation",
                    evidence_type="unstructured",
                    pass_condition="Evidence demonstrates effective monitoring",
                    weight=0.25,
                ),
            ]
        return TestingCriteria(
            control_id=control_id,
            framework=framework,
            control_objective="Ensure logical access is restricted",
            criteria=criteria,
        )

    return _make


@pytest.fixture
def sample_evidence_metadata():
    """Factory for creating EvidenceMetadata instances."""
    from src.models import EvidenceMetadata

    def _make(
        storage_key: str = "tenant1/evidence/SOC2/CC6.1/access_policy.pdf",
        file_type: str = "pdf",
        columns: list[str] | None = None,
        row_count: int = 0,
        text_content: str = "",
        schema_info: dict[str, Any] | None = None,
    ) -> EvidenceMetadata:
        return EvidenceMetadata(
            storage_key=storage_key,
            file_type=file_type,
            columns=columns or [],
            row_count=row_count,
            text_content=text_content,
            schema_info=schema_info or {},
        )

    return _make


@pytest.fixture
def sample_evidence_file():
    """Factory for creating EvidenceFile instances."""
    from src.models import EvidenceFile

    def _make(
        storage_key: str = "tenant1/evidence/SOC2/CC6.1/access_policy.pdf",
        filename: str = "access_policy.pdf",
        file_type: str = "pdf",
        size_bytes: int = 1024,
        last_modified: datetime | None = None,
    ) -> EvidenceFile:
        if last_modified is None:
            last_modified = datetime.now(timezone.utc) - timedelta(days=30)
        return EvidenceFile(
            storage_key=storage_key,
            filename=filename,
            file_type=file_type,
            size_bytes=size_bytes,
            last_modified=last_modified,
        )

    return _make


@pytest.fixture
def sample_eval_state():
    """Factory for creating a base EvalGraphState dict."""

    def _make(**overrides) -> dict[str, Any]:
        base = {
            "tenant_id": "tenant-001",
            "control_id": "CC6.1",
            "framework": "SOC2",
            "trace_id": "trace-test-001",
            "bypass_cache": False,
        }
        base.update(overrides)
        return base

    return _make
