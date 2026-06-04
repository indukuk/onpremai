"""Tests for the DedupService: similarity threshold, merge logic, edge cases."""
from __future__ import annotations

from unittest.mock import patch

import pytest

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../memory-service"))

from src.services.dedup import DedupService


# ---------------------------------------------------------------------------
# is_duplicate() tests
# ---------------------------------------------------------------------------


class TestIsDuplicate:
    """Tests for dedup similarity threshold evaluation."""

    def test_exact_match_is_duplicate(self):
        """Similarity of 1.0 (exact match) is always a duplicate."""
        svc = DedupService(threshold=0.9)
        assert svc.is_duplicate(1.0) is True

    def test_above_threshold_is_duplicate(self):
        """Similarity above threshold is considered a duplicate."""
        svc = DedupService(threshold=0.9)
        assert svc.is_duplicate(0.95) is True

    def test_at_threshold_is_duplicate(self):
        """Similarity exactly at threshold is considered a duplicate (>=)."""
        svc = DedupService(threshold=0.9)
        assert svc.is_duplicate(0.9) is True

    def test_below_threshold_is_not_duplicate(self):
        """Similarity below threshold is not a duplicate."""
        svc = DedupService(threshold=0.9)
        assert svc.is_duplicate(0.89) is False

    def test_zero_similarity_is_not_duplicate(self):
        """Zero similarity is never a duplicate."""
        svc = DedupService(threshold=0.9)
        assert svc.is_duplicate(0.0) is False

    def test_custom_threshold(self):
        """Custom threshold overrides the default."""
        svc = DedupService(threshold=0.7)
        assert svc.is_duplicate(0.75) is True
        assert svc.is_duplicate(0.65) is False

    def test_very_low_threshold(self):
        """Very low threshold makes almost everything a duplicate."""
        svc = DedupService(threshold=0.1)
        assert svc.is_duplicate(0.15) is True
        assert svc.is_duplicate(0.05) is False

    def test_threshold_of_one_requires_exact_match(self):
        """Threshold of 1.0 means only exact matches are duplicates."""
        svc = DedupService(threshold=1.0)
        assert svc.is_duplicate(0.999) is False
        assert svc.is_duplicate(1.0) is True


# ---------------------------------------------------------------------------
# merge_confidence() tests
# ---------------------------------------------------------------------------


class TestMergeConfidence:
    """Tests for confidence merging logic."""

    def test_incoming_higher_takes_precedence(self):
        """Higher incoming confidence wins."""
        svc = DedupService(threshold=0.9)
        assert svc.merge_confidence(existing=0.7, incoming=0.95) == 0.95

    def test_existing_higher_stays(self):
        """Higher existing confidence is preserved."""
        svc = DedupService(threshold=0.9)
        assert svc.merge_confidence(existing=0.99, incoming=0.8) == 0.99

    def test_equal_confidences(self):
        """Equal confidences return the same value."""
        svc = DedupService(threshold=0.9)
        assert svc.merge_confidence(existing=0.5, incoming=0.5) == 0.5

    def test_zero_existing(self):
        """Zero existing confidence allows incoming to take over."""
        svc = DedupService(threshold=0.9)
        assert svc.merge_confidence(existing=0.0, incoming=0.8) == 0.8

    def test_both_max_confidence(self):
        """Both at 1.0 returns 1.0."""
        svc = DedupService(threshold=0.9)
        assert svc.merge_confidence(existing=1.0, incoming=1.0) == 1.0


# ---------------------------------------------------------------------------
# threshold property tests
# ---------------------------------------------------------------------------


class TestThresholdProperty:
    """Tests for the threshold configuration."""

    def test_default_threshold_from_settings(self):
        """Default threshold comes from settings when not specified."""
        with patch("src.services.dedup.settings") as mock_settings:
            mock_settings.DEDUP_SIMILARITY_THRESHOLD = 0.85
            svc = DedupService()
            assert svc.threshold == 0.85

    def test_explicit_threshold_overrides_settings(self):
        """Explicit threshold parameter overrides config."""
        svc = DedupService(threshold=0.75)
        assert svc.threshold == 0.75

    def test_threshold_is_readonly(self):
        """Threshold property does not have a setter."""
        svc = DedupService(threshold=0.9)
        with pytest.raises(AttributeError):
            svc.threshold = 0.5  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge cases and boundary conditions for dedup service."""

    def test_negative_similarity_not_duplicate(self):
        """Negative similarity (theoretically possible with some metrics) is not a duplicate."""
        svc = DedupService(threshold=0.9)
        assert svc.is_duplicate(-0.1) is False

    def test_similarity_greater_than_one(self):
        """Similarity > 1.0 (shouldn't happen but handle gracefully) is a duplicate."""
        svc = DedupService(threshold=0.9)
        assert svc.is_duplicate(1.1) is True

    def test_threshold_zero_everything_is_duplicate(self):
        """Threshold of 0.0 means everything is a duplicate."""
        svc = DedupService(threshold=0.0)
        assert svc.is_duplicate(0.0) is True
        assert svc.is_duplicate(0.001) is True

    def test_merge_confidence_with_boundary_values(self):
        """Merge with 0.0 and 1.0 boundaries."""
        svc = DedupService(threshold=0.9)
        assert svc.merge_confidence(0.0, 0.0) == 0.0
        assert svc.merge_confidence(1.0, 0.0) == 1.0
        assert svc.merge_confidence(0.0, 1.0) == 1.0
