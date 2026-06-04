"""Tests for the discovery node.

Tests evidence hash caching:
- Unchanged hash -> returns cached result (skip evaluation)
- Changed hash -> proceeds with full evaluation
- Bypass cache flag -> always proceeds
- No evidence found -> returns error
"""

from __future__ import annotations

import hashlib
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "agent-eval"))

from src.graph.discovery import (
    _check_evidence_cache,
    _compute_evidence_hash,
    _detect_file_type,
    discovery_node,
)
from src.models import (
    ComplianceStatus,
    EvalResult,
    EvidenceFile,
    TimingStats,
)


# ---------------------------------------------------------------------------
# EVIDENCE HASH COMPUTATION
# ---------------------------------------------------------------------------


class TestComputeEvidenceHash:
    """Tests for the deterministic evidence hash computation."""

    def test_same_files_same_hash(self, sample_evidence_file):
        """Same evidence files always produce the same hash."""
        ts = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        files = [
            sample_evidence_file(
                storage_key="a/file1.pdf",
                size_bytes=1000,
                last_modified=ts,
            ),
            sample_evidence_file(
                storage_key="b/file2.csv",
                size_bytes=2000,
                last_modified=ts,
            ),
        ]

        hash1 = _compute_evidence_hash(files)
        hash2 = _compute_evidence_hash(files)

        assert hash1 == hash2
        assert len(hash1) == 64  # SHA-256 hex digest

    def test_different_files_different_hash(self, sample_evidence_file):
        """Different evidence files produce different hashes."""
        ts = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        files_a = [
            sample_evidence_file(
                storage_key="file1.pdf", size_bytes=1000, last_modified=ts
            ),
        ]
        files_b = [
            sample_evidence_file(
                storage_key="file2.pdf", size_bytes=1000, last_modified=ts
            ),
        ]

        assert _compute_evidence_hash(files_a) != _compute_evidence_hash(files_b)

    def test_modified_timestamp_changes_hash(self, sample_evidence_file):
        """Changing last_modified changes the hash."""
        files_old = [
            sample_evidence_file(
                storage_key="file.pdf",
                size_bytes=1000,
                last_modified=datetime(2024, 1, 1, tzinfo=timezone.utc),
            ),
        ]
        files_new = [
            sample_evidence_file(
                storage_key="file.pdf",
                size_bytes=1000,
                last_modified=datetime(2024, 6, 1, tzinfo=timezone.utc),
            ),
        ]

        assert _compute_evidence_hash(files_old) != _compute_evidence_hash(files_new)

    def test_size_change_changes_hash(self, sample_evidence_file):
        """Changing size_bytes changes the hash."""
        ts = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        files_a = [
            sample_evidence_file(
                storage_key="file.pdf", size_bytes=1000, last_modified=ts
            ),
        ]
        files_b = [
            sample_evidence_file(
                storage_key="file.pdf", size_bytes=2000, last_modified=ts
            ),
        ]

        assert _compute_evidence_hash(files_a) != _compute_evidence_hash(files_b)

    def test_order_independent(self, sample_evidence_file):
        """Hash is the same regardless of file order (sorted internally)."""
        ts = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        file_a = sample_evidence_file(
            storage_key="aaa.pdf", size_bytes=100, last_modified=ts
        )
        file_b = sample_evidence_file(
            storage_key="bbb.pdf", size_bytes=200, last_modified=ts
        )

        hash_ab = _compute_evidence_hash([file_a, file_b])
        hash_ba = _compute_evidence_hash([file_b, file_a])

        assert hash_ab == hash_ba

    def test_empty_files_list(self):
        """Empty file list produces a consistent hash."""
        hash1 = _compute_evidence_hash([])
        hash2 = _compute_evidence_hash([])

        assert hash1 == hash2


# ---------------------------------------------------------------------------
# FILE TYPE DETECTION
# ---------------------------------------------------------------------------


class TestDetectFileType:
    """Tests for file type detection from filename."""

    @pytest.mark.parametrize(
        "filename,expected",
        [
            ("report.xlsx", "spreadsheet"),
            ("data.xls", "spreadsheet"),
            ("log.csv", "csv"),
            ("policy.pdf", "pdf"),
            ("procedure.doc", "document"),
            ("manual.docx", "document"),
            ("screenshot.png", "image"),
            ("photo.jpg", "image"),
            ("photo.jpeg", "image"),
            ("diagram.gif", "image"),
            ("slides.ppt", "presentation"),
            ("deck.pptx", "presentation"),
            ("config.json", "json"),
            ("readme.txt", "text"),
            ("notes.md", "text"),
            ("random.xyz", "unknown"),
        ],
    )
    def test_file_type_detection(self, filename, expected):
        assert _detect_file_type(filename) == expected


# ---------------------------------------------------------------------------
# CACHE CHECK
# ---------------------------------------------------------------------------


class TestCheckEvidenceCache:
    """Tests for _check_evidence_cache."""

    @pytest.mark.asyncio
    async def test_cache_hit_returns_eval_result(self):
        """Returns cached EvalResult when evidence hash matches."""
        mock_memory = AsyncMock()
        cached_data = {
            "evidence_hash": "abc123",
            "result": {
                "control_id": "CC6.1",
                "framework": "SOC2",
                "tenant_id": "t1",
                "score": 0.9,
                "status": "compliant",
                "evidence_hash": "abc123",
            },
        }
        mock_memory.eval_recall = AsyncMock(return_value=[cached_data])

        result = await _check_evidence_cache(
            mock_memory, "t1", "SOC2", "CC6.1", "abc123"
        )

        assert result is not None
        assert result.cached is True
        assert result.score == 0.9

    @pytest.mark.asyncio
    async def test_cache_miss_hash_mismatch(self):
        """Returns None when evidence hash does not match."""
        mock_memory = AsyncMock()
        cached_data = {
            "evidence_hash": "old_hash",
            "result": {
                "control_id": "CC6.1",
                "framework": "SOC2",
                "tenant_id": "t1",
                "score": 0.9,
                "status": "compliant",
            },
        }
        mock_memory.eval_recall = AsyncMock(return_value=[cached_data])

        result = await _check_evidence_cache(
            mock_memory, "t1", "SOC2", "CC6.1", "new_hash"
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_cache_miss_no_previous_evals(self):
        """Returns None when no previous evaluations exist."""
        mock_memory = AsyncMock()
        mock_memory.eval_recall = AsyncMock(return_value=[])

        result = await _check_evidence_cache(
            mock_memory, "t1", "SOC2", "CC6.1", "any_hash"
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_cache_miss_invalid_result_format(self):
        """Returns None when cached data cannot be validated."""
        mock_memory = AsyncMock()
        cached_data = {
            "evidence_hash": "abc123",
            "result": {"invalid": "data"},
        }
        mock_memory.eval_recall = AsyncMock(return_value=[cached_data])

        result = await _check_evidence_cache(
            mock_memory, "t1", "SOC2", "CC6.1", "abc123"
        )

        # Should return None because validation fails
        assert result is None


# ---------------------------------------------------------------------------
# DISCOVERY NODE
# ---------------------------------------------------------------------------


class TestDiscoveryNode:
    """Tests for the discovery_node graph node."""

    @pytest.mark.asyncio
    async def test_no_evidence_returns_error(self):
        """Returns error when no evidence files are found."""
        mock_storage = AsyncMock()
        mock_storage.list_objects = AsyncMock(return_value=[])
        mock_storage.close = AsyncMock()

        mock_memory = AsyncMock()
        mock_memory.close = AsyncMock()

        state = {
            "tenant_id": "t1",
            "control_id": "CC6.1",
            "framework": "SOC2",
            "trace_id": "trace-1",
            "bypass_cache": False,
        }

        with (
            patch("src.graph.discovery.StorageClient", return_value=mock_storage),
            patch("src.graph.discovery.MemoryClient", return_value=mock_memory),
        ):
            result = await discovery_node(state)

        assert result["evidence_files"] == []
        assert "No evidence files found" in result["error"]
        assert result["evidence_hash"] == ""

    @pytest.mark.asyncio
    async def test_evidence_found_no_cache(self):
        """Discovers evidence files and proceeds (no cache hit)."""
        mock_storage = AsyncMock()
        mock_storage.list_objects = AsyncMock(
            return_value=[
                "t1/evidence/SOC2/CC6.1/policy.pdf",
                "t1/evidence/SOC2/CC6.1/access_log.csv",
            ]
        )
        mock_storage.close = AsyncMock()

        mock_memory = AsyncMock()
        mock_memory.eval_recall = AsyncMock(return_value=[])
        mock_memory.close = AsyncMock()

        state = {
            "tenant_id": "t1",
            "control_id": "CC6.1",
            "framework": "SOC2",
            "trace_id": "trace-1",
            "bypass_cache": False,
        }

        with (
            patch("src.graph.discovery.StorageClient", return_value=mock_storage),
            patch(
                "src.graph.discovery.StorageClient.tenant_prefix",
                side_effect=lambda tid, path: f"{tid}/{path}",
            ),
            patch("src.graph.discovery.MemoryClient", return_value=mock_memory),
        ):
            result = await discovery_node(state)

        assert len(result["evidence_files"]) == 2
        assert result["evidence_hash"] != ""
        assert "cached_result" not in result
        assert result["timing"].discovery_ms > 0

    @pytest.mark.asyncio
    async def test_cache_hit_returns_cached_result(self):
        """Returns cached_result when evidence hash matches previous eval."""
        mock_storage = AsyncMock()
        mock_storage.list_objects = AsyncMock(
            return_value=["t1/evidence/SOC2/CC6.1/policy.pdf"]
        )
        mock_storage.close = AsyncMock()

        # We need to match the hash that will be computed
        mock_memory = AsyncMock()
        cached_eval = {
            "evidence_hash": "will_be_patched",
            "result": {
                "control_id": "CC6.1",
                "framework": "SOC2",
                "tenant_id": "t1",
                "score": 0.95,
                "status": "compliant",
            },
        }
        mock_memory.eval_recall = AsyncMock(return_value=[cached_eval])
        mock_memory.close = AsyncMock()

        state = {
            "tenant_id": "t1",
            "control_id": "CC6.1",
            "framework": "SOC2",
            "trace_id": "trace-1",
            "bypass_cache": False,
        }

        # Mock _check_evidence_cache to return a cached result
        cached_result = EvalResult(
            control_id="CC6.1",
            framework="SOC2",
            tenant_id="t1",
            score=0.95,
            status=ComplianceStatus.COMPLIANT,
            cached=True,
        )

        with (
            patch("src.graph.discovery.StorageClient", return_value=mock_storage),
            patch(
                "src.graph.discovery.StorageClient.tenant_prefix",
                side_effect=lambda tid, path: f"{tid}/{path}",
            ),
            patch("src.graph.discovery.MemoryClient", return_value=mock_memory),
            patch(
                "src.graph.discovery._check_evidence_cache",
                return_value=cached_result,
            ),
        ):
            result = await discovery_node(state)

        assert result["cached_result"] is not None
        assert result["cached_result"].cached is True
        assert result["cached_result"].score == 0.95

    @pytest.mark.asyncio
    async def test_bypass_cache_skips_cache_check(self):
        """bypass_cache=True skips cache lookup."""
        mock_storage = AsyncMock()
        mock_storage.list_objects = AsyncMock(
            return_value=["t1/evidence/SOC2/CC6.1/policy.pdf"]
        )
        mock_storage.close = AsyncMock()

        mock_memory = AsyncMock()
        mock_memory.eval_recall = AsyncMock()
        mock_memory.close = AsyncMock()

        state = {
            "tenant_id": "t1",
            "control_id": "CC6.1",
            "framework": "SOC2",
            "trace_id": "trace-1",
            "bypass_cache": True,
        }

        with (
            patch("src.graph.discovery.StorageClient", return_value=mock_storage),
            patch(
                "src.graph.discovery.StorageClient.tenant_prefix",
                side_effect=lambda tid, path: f"{tid}/{path}",
            ),
            patch("src.graph.discovery.MemoryClient", return_value=mock_memory),
        ):
            result = await discovery_node(state)

        # Should NOT have called eval_recall since bypass_cache=True
        mock_memory.eval_recall.assert_not_called()
        assert "cached_result" not in result

    @pytest.mark.asyncio
    async def test_skips_directories_and_metadata_files(self):
        """Directories and metadata.json files are excluded."""
        mock_storage = AsyncMock()
        mock_storage.list_objects = AsyncMock(
            return_value=[
                "t1/evidence/SOC2/CC6.1/",
                "t1/evidence/SOC2/CC6.1/metadata.json",
                "t1/evidence/SOC2/CC6.1/real_file.pdf",
            ]
        )
        mock_storage.close = AsyncMock()

        mock_memory = AsyncMock()
        mock_memory.eval_recall = AsyncMock(return_value=[])
        mock_memory.close = AsyncMock()

        state = {
            "tenant_id": "t1",
            "control_id": "CC6.1",
            "framework": "SOC2",
            "trace_id": "trace-1",
            "bypass_cache": False,
        }

        with (
            patch("src.graph.discovery.StorageClient", return_value=mock_storage),
            patch(
                "src.graph.discovery.StorageClient.tenant_prefix",
                side_effect=lambda tid, path: f"{tid}/{path}",
            ),
            patch("src.graph.discovery.MemoryClient", return_value=mock_memory),
        ):
            result = await discovery_node(state)

        # Only real_file.pdf should be included
        assert len(result["evidence_files"]) == 1
        assert result["evidence_files"][0].filename == "real_file.pdf"

    @pytest.mark.asyncio
    async def test_deduplicates_files_from_multiple_prefixes(self):
        """Files found in both specific and general prefixes are deduplicated."""
        mock_storage = AsyncMock()

        # First call (specific prefix) and second call (general prefix) share a file
        mock_storage.list_objects = AsyncMock(
            side_effect=[
                ["t1/evidence/SOC2/CC6.1/shared.pdf", "t1/evidence/SOC2/CC6.1/specific.csv"],
                ["t1/evidence/SOC2/CC6.1/shared.pdf", "t1/evidence/general.pdf"],
            ]
        )
        mock_storage.close = AsyncMock()

        mock_memory = AsyncMock()
        mock_memory.eval_recall = AsyncMock(return_value=[])
        mock_memory.close = AsyncMock()

        state = {
            "tenant_id": "t1",
            "control_id": "CC6.1",
            "framework": "SOC2",
            "trace_id": "trace-1",
            "bypass_cache": False,
        }

        with (
            patch("src.graph.discovery.StorageClient", return_value=mock_storage),
            patch(
                "src.graph.discovery.StorageClient.tenant_prefix",
                side_effect=lambda tid, path: f"{tid}/{path}",
            ),
            patch("src.graph.discovery.MemoryClient", return_value=mock_memory),
        ):
            result = await discovery_node(state)

        # Should be 3 unique files (shared.pdf deduplicated)
        assert len(result["evidence_files"]) == 3
