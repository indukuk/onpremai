"""Tests for Layer 1: Deterministic rule engine.

Tests all 8 rule types with known inputs, verifying PASS/FAIL/NEEDS_JUDGMENT
outcomes for each rule handler.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "agent-eval"))

from src.models import (
    Criterion,
    CriterionResult,
    CriterionResultEnum,
    EvalMethod,
    EvidenceFile,
    EvidenceMetadata,
    TestingCriteria,
    TimingStats,
)
from src.rules.engine import dispatch_rule
from src.rules.file_existence import check_file_existence
from src.rules.freshness import check_freshness
from src.rules.row_count import check_row_count
from src.rules.null_rate import check_null_rate
from src.rules.schema_presence import check_schema_presence
from src.rules.cross_reference import check_cross_reference
from src.rules.quantitative import check_quantitative
from src.rules.keyword_presence import check_keyword_presence


# ---------------------------------------------------------------------------
# 1. FILE EXISTENCE
# ---------------------------------------------------------------------------


class TestFileExistence:
    """Tests for the file_existence rule check."""

    def test_pass_document_found(self, sample_criterion, sample_evidence_metadata):
        """PASS when a matching document file exists."""
        criterion = sample_criterion(
            id="FE1",
            evidence_type="document",
            pass_condition="Access control policy exists",
            check_type="file_existence",
        )
        meta = sample_evidence_metadata(
            storage_key="tenant1/evidence/access_policy.pdf",
            file_type="pdf",
        )

        result = check_file_existence(criterion, [meta], [])

        assert result.result == CriterionResultEnum.PASS
        assert result.method == EvalMethod.RULE_FILE_EXISTENCE
        assert "access_policy.pdf" in result.reason

    def test_fail_no_matching_file(self, sample_criterion, sample_evidence_metadata):
        """FAIL when no file matching the expected type exists."""
        criterion = sample_criterion(
            id="FE2",
            evidence_type="document",
            pass_condition="Termination procedure document exists",
            check_type="file_existence",
        )
        # Only structured data available, no documents
        meta = sample_evidence_metadata(
            storage_key="tenant1/evidence/access_log.csv",
            file_type="csv",
        )

        result = check_file_existence(criterion, [meta], [])

        assert result.result == CriterionResultEnum.FAIL
        assert result.method == EvalMethod.RULE_FILE_EXISTENCE

    def test_pass_with_name_pattern(self, sample_criterion, sample_evidence_metadata):
        """PASS when file matches the name pattern from check_params."""
        criterion = sample_criterion(
            id="FE3",
            evidence_type="document",
            pass_condition="Policy document exists",
            check_type="file_existence",
            check_params={"name_pattern": "policy"},
        )
        meta = sample_evidence_metadata(
            storage_key="tenant1/evidence/security_policy.pdf",
            file_type="pdf",
        )

        result = check_file_existence(criterion, [meta], [])

        assert result.result == CriterionResultEnum.PASS

    def test_fail_name_pattern_no_match(self, sample_criterion, sample_evidence_metadata):
        """FAIL when file exists but does not match the name pattern."""
        criterion = sample_criterion(
            id="FE4",
            evidence_type="document",
            pass_condition="Audit certificate exists",
            check_type="file_existence",
            check_params={"name_pattern": "certificate"},
        )
        meta = sample_evidence_metadata(
            storage_key="tenant1/evidence/general_notes.pdf",
            file_type="pdf",
        )

        result = check_file_existence(criterion, [meta], [])

        assert result.result == CriterionResultEnum.FAIL

    def test_pass_using_evidence_files_fallback(self, sample_criterion, sample_evidence_file):
        """PASS when metadata is empty but evidence_files have a matching file."""
        criterion = sample_criterion(
            id="FE5",
            evidence_type="document",
            pass_condition="Policy document exists",
            check_type="file_existence",
        )
        ef = sample_evidence_file(
            storage_key="tenant1/evidence/policy_v2.pdf",
            file_type="pdf",
        )

        result = check_file_existence(criterion, [], [ef])

        assert result.result == CriterionResultEnum.PASS


# ---------------------------------------------------------------------------
# 2. FRESHNESS
# ---------------------------------------------------------------------------


class TestFreshness:
    """Tests for the freshness rule check."""

    def test_pass_all_files_fresh(self, sample_criterion, sample_evidence_file, sample_evidence_metadata):
        """PASS when all evidence files are within the freshness window."""
        criterion = sample_criterion(
            id="FR1",
            evidence_type="document",
            pass_condition="Reviewed within 12 months",
            check_type="freshness",
        )
        fresh_file = sample_evidence_file(
            last_modified=datetime.now(timezone.utc) - timedelta(days=60),
        )

        result = check_freshness(criterion, [], [fresh_file])

        assert result.result == CriterionResultEnum.PASS
        assert result.method == EvalMethod.RULE_FRESHNESS

    def test_fail_all_files_stale(self, sample_criterion, sample_evidence_file):
        """FAIL when all evidence files exceed the freshness window."""
        criterion = sample_criterion(
            id="FR2",
            evidence_type="document",
            pass_condition="Reviewed within 6 months",
            check_type="freshness",
        )
        stale_file = sample_evidence_file(
            last_modified=datetime.now(timezone.utc) - timedelta(days=200),
        )

        result = check_freshness(criterion, [], [stale_file])

        assert result.result == CriterionResultEnum.FAIL
        assert "freshness threshold" in result.reason

    def test_needs_judgment_mixed_freshness(self, sample_criterion, sample_evidence_file):
        """NEEDS_JUDGMENT when some files are fresh and some stale."""
        criterion = sample_criterion(
            id="FR3",
            evidence_type="document",
            pass_condition="Reviewed within 3 months",
            check_type="freshness",
        )
        fresh = sample_evidence_file(
            storage_key="fresh.pdf",
            last_modified=datetime.now(timezone.utc) - timedelta(days=30),
        )
        stale = sample_evidence_file(
            storage_key="stale.pdf",
            last_modified=datetime.now(timezone.utc) - timedelta(days=120),
        )

        result = check_freshness(criterion, [], [fresh, stale])

        assert result.result == CriterionResultEnum.NEEDS_JUDGMENT

    def test_needs_judgment_cannot_determine_age(self, sample_criterion):
        """NEEDS_JUDGMENT when no date can be parsed from criterion."""
        criterion = sample_criterion(
            id="FR4",
            evidence_type="document",
            pass_condition="Document is current",
            check_type="freshness",
        )

        result = check_freshness(criterion, [], [])

        assert result.result == CriterionResultEnum.NEEDS_JUDGMENT

    def test_pass_with_explicit_max_age_days(self, sample_criterion, sample_evidence_file):
        """PASS when check_params provides explicit max_age_days."""
        criterion = sample_criterion(
            id="FR5",
            evidence_type="document",
            pass_condition="Document is current",
            check_type="freshness",
            check_params={"max_age_days": 365},
        )
        fresh_file = sample_evidence_file(
            last_modified=datetime.now(timezone.utc) - timedelta(days=100),
        )

        result = check_freshness(criterion, [], [fresh_file])

        assert result.result == CriterionResultEnum.PASS


# ---------------------------------------------------------------------------
# 3. ROW COUNT
# ---------------------------------------------------------------------------


class TestRowCount:
    """Tests for the row_count rule check."""

    def test_pass_above_minimum(self, sample_criterion, sample_evidence_metadata):
        """PASS when row count meets minimum threshold."""
        criterion = sample_criterion(
            id="RC1",
            evidence_type="structured_data",
            pass_condition="At least 10 records exist",
            check_type="row_count",
        )
        meta = sample_evidence_metadata(
            file_type="csv",
            row_count=50,
        )

        result = check_row_count(criterion, [meta], [])

        assert result.result == CriterionResultEnum.PASS
        assert result.method == EvalMethod.RULE_ROW_COUNT
        assert "50" in result.reason

    def test_fail_below_minimum(self, sample_criterion, sample_evidence_metadata):
        """FAIL when row count is below minimum."""
        criterion = sample_criterion(
            id="RC2",
            evidence_type="structured_data",
            pass_condition="Minimum 100 records",
            check_type="row_count",
            check_params={"min_rows": 100},
        )
        meta = sample_evidence_metadata(
            file_type="spreadsheet",
            row_count=25,
        )

        result = check_row_count(criterion, [meta], [])

        assert result.result == CriterionResultEnum.FAIL
        assert "25" in result.reason
        assert "100" in result.reason

    def test_fail_no_structured_data(self, sample_criterion, sample_evidence_metadata):
        """FAIL when no structured data files are present."""
        criterion = sample_criterion(
            id="RC3",
            evidence_type="structured_data",
            pass_condition="Records exist",
            check_type="row_count",
        )
        meta = sample_evidence_metadata(
            file_type="pdf",
            row_count=0,
        )

        result = check_row_count(criterion, [meta], [])

        assert result.result == CriterionResultEnum.FAIL

    def test_pass_aggregates_multiple_files(self, sample_criterion, sample_evidence_metadata):
        """PASS when row counts sum from multiple files meets threshold."""
        criterion = sample_criterion(
            id="RC4",
            evidence_type="structured_data",
            pass_condition="At least 100 records exist",
            check_type="row_count",
            check_params={"min_rows": 100},
        )
        meta1 = sample_evidence_metadata(
            storage_key="file1.csv", file_type="csv", row_count=60
        )
        meta2 = sample_evidence_metadata(
            storage_key="file2.csv", file_type="csv", row_count=50
        )

        result = check_row_count(criterion, [meta1, meta2], [])

        assert result.result == CriterionResultEnum.PASS

    def test_pass_default_min_is_one(self, sample_criterion, sample_evidence_metadata):
        """PASS when no explicit min_rows and data exists (defaults to 1)."""
        criterion = sample_criterion(
            id="RC5",
            evidence_type="structured_data",
            pass_condition="Data is present",
            check_type="row_count",
        )
        meta = sample_evidence_metadata(file_type="json", row_count=1)

        result = check_row_count(criterion, [meta], [])

        assert result.result == CriterionResultEnum.PASS


# ---------------------------------------------------------------------------
# 4. NULL RATE
# ---------------------------------------------------------------------------


class TestNullRate:
    """Tests for the null_rate rule check."""

    def test_pass_columns_above_threshold(self, sample_criterion, sample_evidence_metadata):
        """PASS when all columns meet the populated threshold."""
        criterion = sample_criterion(
            id="NR1",
            evidence_type="structured_data",
            pass_condition="Key columns 95% populated",
            check_type="null_rate",
            check_params={"min_populated_rate": 0.95, "columns": ["user_id", "action"]},
        )
        meta = sample_evidence_metadata(
            file_type="csv",
            row_count=100,
            columns=["user_id", "action", "timestamp"],
            schema_info={
                "null_rates": {"user_id": 0.02, "action": 0.01, "timestamp": 0.05}
            },
        )

        result = check_null_rate(criterion, [meta], [])

        assert result.result == CriterionResultEnum.PASS
        assert result.method == EvalMethod.RULE_NULL_RATE

    def test_fail_columns_below_threshold(self, sample_criterion, sample_evidence_metadata):
        """FAIL when columns have too many nulls."""
        criterion = sample_criterion(
            id="NR2",
            evidence_type="structured_data",
            pass_condition="99% populated",
            check_type="null_rate",
            check_params={"min_populated_rate": 0.99, "columns": ["user_id"]},
        )
        meta = sample_evidence_metadata(
            file_type="csv",
            row_count=100,
            columns=["user_id", "action"],
            schema_info={"null_rates": {"user_id": 0.10, "action": 0.02}},
        )

        result = check_null_rate(criterion, [meta], [])

        assert result.result == CriterionResultEnum.FAIL

    def test_needs_judgment_no_null_stats(self, sample_criterion, sample_evidence_metadata):
        """NEEDS_JUDGMENT when structured data exists but null stats are missing."""
        criterion = sample_criterion(
            id="NR3",
            evidence_type="structured_data",
            pass_condition="Columns populated",
            check_type="null_rate",
        )
        meta = sample_evidence_metadata(
            file_type="csv",
            row_count=50,
            columns=["user_id", "action"],
            schema_info={},
        )

        result = check_null_rate(criterion, [meta], [])

        assert result.result == CriterionResultEnum.NEEDS_JUDGMENT

    def test_needs_judgment_no_structured_evidence(self, sample_criterion, sample_evidence_metadata):
        """NEEDS_JUDGMENT when no structured evidence is available."""
        criterion = sample_criterion(
            id="NR4",
            evidence_type="structured_data",
            pass_condition="95% populated",
            check_type="null_rate",
        )
        meta = sample_evidence_metadata(file_type="pdf", row_count=0)

        result = check_null_rate(criterion, [meta], [])

        assert result.result == CriterionResultEnum.NEEDS_JUDGMENT


# ---------------------------------------------------------------------------
# 5. SCHEMA PRESENCE
# ---------------------------------------------------------------------------


class TestSchemaPresence:
    """Tests for the schema_presence rule check."""

    def test_pass_all_required_columns_present(self, sample_criterion, sample_evidence_metadata):
        """PASS when all required columns exist in evidence."""
        criterion = sample_criterion(
            id="SP1",
            evidence_type="structured_data",
            pass_condition="Contains required fields",
            check_type="schema_presence",
            check_params={"required_columns": ["user_id", "action", "date"]},
        )
        meta = sample_evidence_metadata(
            file_type="csv",
            columns=["user_id", "action", "date", "status"],
            row_count=10,
        )

        result = check_schema_presence(criterion, [meta], [])

        assert result.result == CriterionResultEnum.PASS
        assert result.method == EvalMethod.RULE_SCHEMA_PRESENCE

    def test_fail_missing_columns(self, sample_criterion, sample_evidence_metadata):
        """FAIL when required columns are missing from evidence."""
        criterion = sample_criterion(
            id="SP2",
            evidence_type="structured_data",
            pass_condition="Contains required fields",
            check_type="schema_presence",
            check_params={"required_columns": ["reviewer", "approval_date", "outcome"]},
        )
        meta = sample_evidence_metadata(
            file_type="csv",
            columns=["user_id", "action"],
            row_count=10,
        )

        result = check_schema_presence(criterion, [meta], [])

        assert result.result == CriterionResultEnum.FAIL
        assert "reviewer" in result.reason or "approval_date" in result.reason

    def test_needs_judgment_no_column_info(self, sample_criterion, sample_evidence_metadata):
        """NEEDS_JUDGMENT when no column information is available."""
        criterion = sample_criterion(
            id="SP3",
            evidence_type="structured_data",
            pass_condition="Contains required fields",
            check_type="schema_presence",
            check_params={"required_columns": ["user_id"]},
        )
        meta = sample_evidence_metadata(
            file_type="pdf",
            columns=[],
        )

        result = check_schema_presence(criterion, [meta], [])

        assert result.result == CriterionResultEnum.NEEDS_JUDGMENT

    def test_needs_judgment_cannot_determine_columns(self, sample_criterion, sample_evidence_metadata):
        """NEEDS_JUDGMENT when no required columns can be extracted."""
        criterion = sample_criterion(
            id="SP4",
            evidence_type="structured_data",
            pass_condition="Data is valid",
            check_type="schema_presence",
            check_params={},
        )
        meta = sample_evidence_metadata(
            file_type="csv",
            columns=["col_a", "col_b"],
            row_count=5,
        )

        result = check_schema_presence(criterion, [meta], [])

        assert result.result == CriterionResultEnum.NEEDS_JUDGMENT


# ---------------------------------------------------------------------------
# 6. CROSS REFERENCE
# ---------------------------------------------------------------------------


class TestCrossReference:
    """Tests for the cross_reference rule check."""

    def test_pass_zero_violations(self, sample_criterion, sample_evidence_metadata):
        """PASS when pre-computed cross-reference shows 0 violations."""
        criterion = sample_criterion(
            id="XR1",
            evidence_type="structured_data",
            pass_condition="No active terminated users",
            check_type="cross_reference",
        )
        meta1 = sample_evidence_metadata(
            storage_key="users.csv",
            file_type="csv",
            columns=["user_id", "status"],
            row_count=100,
            schema_info={
                "cross_reference_results": {"violations": 0, "total_checked": 100}
            },
        )
        meta2 = sample_evidence_metadata(
            storage_key="access.csv",
            file_type="csv",
            columns=["user_id", "role"],
            row_count=80,
        )

        result = check_cross_reference(criterion, [meta1, meta2], [])

        assert result.result == CriterionResultEnum.PASS
        assert result.method == EvalMethod.RULE_CROSS_REFERENCE

    def test_fail_violations_found(self, sample_criterion, sample_evidence_metadata):
        """FAIL when cross-reference reveals violations."""
        criterion = sample_criterion(
            id="XR2",
            evidence_type="structured_data",
            pass_condition="No active terminated users",
            check_type="cross_reference",
        )
        meta1 = sample_evidence_metadata(
            storage_key="users.csv",
            file_type="csv",
            columns=["user_id", "status"],
            row_count=100,
            schema_info={
                "cross_reference_results": {"violations": 3, "total_checked": 100}
            },
        )
        meta2 = sample_evidence_metadata(
            storage_key="access.csv",
            file_type="csv",
            columns=["user_id", "role"],
            row_count=80,
        )

        result = check_cross_reference(criterion, [meta1, meta2], [])

        assert result.result == CriterionResultEnum.FAIL
        assert "3 violation" in result.reason

    def test_fail_no_structured_data(self, sample_criterion, sample_evidence_metadata):
        """FAIL when no structured datasets are available."""
        criterion = sample_criterion(
            id="XR3",
            evidence_type="structured_data",
            pass_condition="No active terminated users",
            check_type="cross_reference",
        )
        meta = sample_evidence_metadata(file_type="pdf", columns=[])

        result = check_cross_reference(criterion, [meta], [])

        assert result.result == CriterionResultEnum.FAIL

    def test_needs_judgment_single_dataset(self, sample_criterion, sample_evidence_metadata):
        """NEEDS_JUDGMENT when only one dataset is available."""
        criterion = sample_criterion(
            id="XR4",
            evidence_type="structured_data",
            pass_condition="No active terminated users",
            check_type="cross_reference",
        )
        meta = sample_evidence_metadata(
            file_type="csv",
            columns=["user_id", "status"],
            row_count=10,
        )

        result = check_cross_reference(criterion, [meta], [])

        assert result.result == CriterionResultEnum.NEEDS_JUDGMENT

    def test_needs_judgment_joinable_no_precomputed(self, sample_criterion, sample_evidence_metadata):
        """NEEDS_JUDGMENT when datasets are joinable but no precomputed results."""
        criterion = sample_criterion(
            id="XR5",
            evidence_type="structured_data",
            pass_condition="No active terminated users",
            check_type="cross_reference",
        )
        meta1 = sample_evidence_metadata(
            storage_key="users.csv",
            file_type="csv",
            columns=["user_id", "status"],
            row_count=100,
        )
        meta2 = sample_evidence_metadata(
            storage_key="access.csv",
            file_type="csv",
            columns=["user_id", "role"],
            row_count=80,
        )

        result = check_cross_reference(criterion, [meta1, meta2], [])

        assert result.result == CriterionResultEnum.NEEDS_JUDGMENT
        assert "code execution" in result.reason


# ---------------------------------------------------------------------------
# 7. QUANTITATIVE
# ---------------------------------------------------------------------------


class TestQuantitative:
    """Tests for the quantitative threshold rule check."""

    def test_pass_metric_meets_threshold(self, sample_criterion, sample_evidence_metadata):
        """PASS when metric value satisfies the threshold condition."""
        criterion = sample_criterion(
            id="QT1",
            evidence_type="structured_data",
            pass_condition="SLA max 48 hours",
            check_type="quantitative",
            check_params={
                "metric_name": "avg_removal_hours",
                "operator": "<=",
                "threshold_value": 48,
            },
        )
        meta = sample_evidence_metadata(
            file_type="csv",
            row_count=50,
            schema_info={"metrics": {"avg_removal_hours": 24.5}},
        )

        result = check_quantitative(criterion, [meta], [])

        assert result.result == CriterionResultEnum.PASS
        assert result.method == EvalMethod.RULE_QUANTITATIVE

    def test_fail_metric_exceeds_threshold(self, sample_criterion, sample_evidence_metadata):
        """FAIL when metric value exceeds the threshold."""
        criterion = sample_criterion(
            id="QT2",
            evidence_type="structured_data",
            pass_condition="SLA max 48 hours",
            check_type="quantitative",
            check_params={
                "metric_name": "avg_removal_hours",
                "operator": "<=",
                "threshold_value": 48,
            },
        )
        meta = sample_evidence_metadata(
            file_type="csv",
            row_count=50,
            schema_info={"metrics": {"avg_removal_hours": 72.0}},
        )

        result = check_quantitative(criterion, [meta], [])

        assert result.result == CriterionResultEnum.FAIL

    def test_needs_judgment_no_metrics(self, sample_criterion, sample_evidence_metadata):
        """NEEDS_JUDGMENT when structured data exists but no precomputed metrics."""
        criterion = sample_criterion(
            id="QT3",
            evidence_type="structured_data",
            pass_condition="Max 48 hours",
            check_type="quantitative",
            check_params={"metric_name": "sla_hours", "threshold_value": 48},
        )
        meta = sample_evidence_metadata(
            file_type="csv",
            row_count=50,
            schema_info={},
        )

        result = check_quantitative(criterion, [meta], [])

        assert result.result == CriterionResultEnum.NEEDS_JUDGMENT

    def test_pass_gte_operator(self, sample_criterion, sample_evidence_metadata):
        """PASS when using >= operator and metric meets threshold."""
        criterion = sample_criterion(
            id="QT4",
            evidence_type="structured_data",
            pass_condition="Coverage >= 95%",
            check_type="quantitative",
            check_params={
                "metric_name": "coverage_pct",
                "operator": ">=",
                "threshold_value": 95,
            },
        )
        meta = sample_evidence_metadata(
            file_type="json",
            row_count=1,
            schema_info={"metrics": {"coverage_pct": 97.5}},
        )

        result = check_quantitative(criterion, [meta], [])

        assert result.result == CriterionResultEnum.PASS

    def test_needs_judgment_no_data_at_all(self, sample_criterion, sample_evidence_metadata):
        """NEEDS_JUDGMENT when no evidence data is available."""
        criterion = sample_criterion(
            id="QT5",
            evidence_type="structured_data",
            pass_condition="Threshold within 24h",
            check_type="quantitative",
        )
        meta = sample_evidence_metadata(file_type="pdf", row_count=0)

        result = check_quantitative(criterion, [meta], [])

        assert result.result == CriterionResultEnum.NEEDS_JUDGMENT


# ---------------------------------------------------------------------------
# 8. KEYWORD PRESENCE
# ---------------------------------------------------------------------------


class TestKeywordPresence:
    """Tests for the keyword_presence rule check."""

    def test_pass_all_keywords_found(self, sample_criterion, sample_evidence_metadata):
        """PASS when all required keywords appear in evidence text."""
        criterion = sample_criterion(
            id="KP1",
            evidence_type="document",
            pass_condition="Policy covers provisioning, de-provisioning, and least privilege",
            check_type="keyword_presence",
            check_params={"keywords": ["provisioning", "de-provisioning", "least privilege"]},
        )
        meta = sample_evidence_metadata(
            file_type="pdf",
            text_content="This policy defines user provisioning steps, "
            "de-provisioning on termination, and enforces least privilege access.",
        )

        result = check_keyword_presence(criterion, [meta], [])

        assert result.result == CriterionResultEnum.PASS
        assert result.method == EvalMethod.RULE_KEYWORD_PRESENCE

    def test_fail_no_keywords_found(self, sample_criterion, sample_evidence_metadata):
        """FAIL when none of the required keywords appear."""
        criterion = sample_criterion(
            id="KP2",
            evidence_type="document",
            pass_condition="Policy covers encryption and backup",
            check_type="keyword_presence",
            check_params={"keywords": ["encryption", "backup"]},
        )
        meta = sample_evidence_metadata(
            file_type="pdf",
            text_content="This document describes the office layout and parking procedures.",
        )

        result = check_keyword_presence(criterion, [meta], [])

        assert result.result == CriterionResultEnum.FAIL

    def test_needs_judgment_partial_match(self, sample_criterion, sample_evidence_metadata):
        """NEEDS_JUDGMENT when some but not all keywords are found."""
        criterion = sample_criterion(
            id="KP3",
            evidence_type="document",
            pass_condition="Covers access control, encryption, and monitoring",
            check_type="keyword_presence",
            check_params={"keywords": ["access control", "encryption", "monitoring"]},
        )
        meta = sample_evidence_metadata(
            file_type="pdf",
            text_content="The access control policy defines role-based permissions. "
            "Monitoring agents run continuously.",
        )

        result = check_keyword_presence(criterion, [meta], [])

        assert result.result == CriterionResultEnum.NEEDS_JUDGMENT
        assert "encryption" in result.reason

    def test_needs_judgment_no_text_content(self, sample_criterion, sample_evidence_metadata):
        """NEEDS_JUDGMENT when no text content is available to search."""
        criterion = sample_criterion(
            id="KP4",
            evidence_type="document",
            pass_condition="Covers encryption",
            check_type="keyword_presence",
            check_params={"keywords": ["encryption"]},
        )
        meta = sample_evidence_metadata(file_type="pdf", text_content="")

        result = check_keyword_presence(criterion, [meta], [])

        assert result.result == CriterionResultEnum.NEEDS_JUDGMENT

    def test_pass_extracted_keywords_from_condition(self, sample_criterion, sample_evidence_metadata):
        """PASS when keywords are extracted from pass_condition (no explicit params)."""
        criterion = sample_criterion(
            id="KP5",
            evidence_type="document",
            pass_condition="Document mentions provisioning and de-provisioning",
            check_type="keyword_presence",
        )
        meta = sample_evidence_metadata(
            file_type="pdf",
            text_content="New user provisioning is automated. "
            "De-provisioning occurs within 24 hours of termination.",
        )

        result = check_keyword_presence(criterion, [meta], [])

        assert result.result == CriterionResultEnum.PASS


# ---------------------------------------------------------------------------
# DISPATCH ENGINE TESTS
# ---------------------------------------------------------------------------


class TestDispatchRule:
    """Tests for the rule dispatch engine."""

    def test_unknown_check_type_returns_needs_judgment(self, sample_criterion):
        """NEEDS_JUDGMENT when check_type has no handler."""
        criterion = sample_criterion(id="D1")

        result = dispatch_rule(
            check_type="nonexistent_rule",
            criterion=criterion,
            evidence_metadata=[],
            evidence_files=[],
        )

        assert result.result == CriterionResultEnum.NEEDS_JUDGMENT
        assert "No rule handler" in result.reason

    def test_handler_exception_returns_needs_judgment(self, sample_criterion, monkeypatch):
        """NEEDS_JUDGMENT when a rule handler raises an unexpected exception."""
        from src.rules import engine as engine_module

        def exploding_handler(criterion, metadata, files):
            raise RuntimeError("Unexpected failure")

        monkeypatch.setitem(engine_module.RULE_HANDLERS, "exploding", exploding_handler)

        criterion = sample_criterion(id="D2")
        result = dispatch_rule(
            check_type="exploding",
            criterion=criterion,
            evidence_metadata=[],
            evidence_files=[],
        )

        assert result.result == CriterionResultEnum.NEEDS_JUDGMENT
        assert "Rule execution error" in result.reason

    def test_dispatches_to_correct_handler(self, sample_criterion, sample_evidence_metadata):
        """Verifies correct handler is called for each check_type."""
        criterion = sample_criterion(
            id="D3",
            evidence_type="structured_data",
            pass_condition="Records exist",
            check_type="row_count",
        )
        meta = sample_evidence_metadata(file_type="csv", row_count=10)

        result = dispatch_rule(
            check_type="row_count",
            criterion=criterion,
            evidence_metadata=[meta],
            evidence_files=[],
        )

        assert result.method == EvalMethod.RULE_ROW_COUNT


# ---------------------------------------------------------------------------
# RULES ENGINE NODE TESTS
# ---------------------------------------------------------------------------


class TestRulesEngineNode:
    """Tests for the rules_engine_node graph node."""

    @pytest.mark.asyncio
    async def test_processes_all_criteria(self, sample_testing_criteria, sample_evidence_metadata):
        """All criteria are processed and results returned."""
        from src.graph.rules_engine import rules_engine_node

        meta_doc = sample_evidence_metadata(
            storage_key="policy.pdf", file_type="pdf"
        )
        meta_csv = sample_evidence_metadata(
            storage_key="access.csv", file_type="csv", row_count=100
        )

        state = {
            "testing_criteria": sample_testing_criteria(),
            "evidence_metadata": [meta_doc, meta_csv],
            "evidence_files": [],
            "trace_id": "test-trace",
        }

        result = await rules_engine_node(state)

        assert "rule_results" in result
        assert "needs_judgment" in result
        # C4 (unstructured) should always need judgment
        assert "C4" in result["needs_judgment"]

    @pytest.mark.asyncio
    async def test_no_testing_criteria_returns_error(self):
        """Returns error dict when no testing criteria available."""
        from src.graph.rules_engine import rules_engine_node

        state = {"testing_criteria": None}

        result = await rules_engine_node(state)

        assert result["error"] == "No testing criteria available"
        assert result["rule_results"] == {}

    @pytest.mark.asyncio
    async def test_timing_stats_populated(self, sample_testing_criteria, sample_evidence_metadata):
        """TimingStats is populated with layer1_ms."""
        from src.graph.rules_engine import rules_engine_node

        state = {
            "testing_criteria": sample_testing_criteria(),
            "evidence_metadata": [
                sample_evidence_metadata(file_type="pdf"),
            ],
            "evidence_files": [],
            "trace_id": "t1",
        }

        result = await rules_engine_node(state)

        assert result["timing"].layer1_ms > 0
