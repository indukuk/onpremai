"""Unit tests for observer self-regulation.

Tests autonomy adjustment: >90% success expands, <70% restricts, boundary cases.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from observer.src.changes.proposal import Change, ChangeStatus, ChangeType, ApplyTier
from observer.src.config import ObserverSettings
from observer.src.self_regulation import AutonomyLevel, SelfEvalResult, SelfRegulator


class TestAutonomyExpansion:
    """Tests for expanding autonomy on high success rate (>90%)."""

    @pytest.mark.asyncio
    async def test_expand_from_standard_to_expanded(self, settings: ObserverSettings) -> None:
        """Success rate above 90% with sufficient data should expand from standard to expanded."""
        regulator = SelfRegulator(settings)
        regulator._memory_client = AsyncMock()
        response_mock = MagicMock()
        response_mock.status_code = 200
        regulator._memory_client.post.return_value = response_mock

        # Add 10 changes, all validated (100% success)
        now = datetime.now(timezone.utc)
        for i in range(10):
            change = Change(
                id=f"chg_{i:03d}",
                change_type=ChangeType.ROUTING,
                apply_tier=ApplyTier.AUTO,
                status=ChangeStatus.VALIDATED,
                proposed_at=(now - timedelta(days=1)).isoformat(),
            )
            regulator.record_change(change)

        result = await regulator.evaluate()

        assert result.success_rate == 1.0
        assert result.adjustment_made is True
        assert result.new_autonomy == "expanded"
        assert regulator.autonomy.level == "expanded"
        assert regulator.autonomy.min_confidence < settings.auto_apply_min_confidence
        assert "prompt" in regulator.autonomy.allowed_auto_types

    @pytest.mark.asyncio
    async def test_expand_from_restricted_to_standard(self, settings: ObserverSettings) -> None:
        """Success rate above 90% when restricted should move to standard (not jump to expanded)."""
        regulator = SelfRegulator(settings)
        regulator._memory_client = AsyncMock()
        response_mock = MagicMock()
        response_mock.status_code = 200
        regulator._memory_client.post.return_value = response_mock
        regulator._autonomy.level = "restricted"

        now = datetime.now(timezone.utc)
        for i in range(8):
            change = Change(
                id=f"chg_{i:03d}",
                change_type=ChangeType.THRESHOLD,
                apply_tier=ApplyTier.AUTO,
                status=ChangeStatus.VALIDATED,
                proposed_at=(now - timedelta(days=2)).isoformat(),
            )
            regulator.record_change(change)

        result = await regulator.evaluate()

        assert result.adjustment_made is True
        assert result.new_autonomy == "standard"
        assert regulator.autonomy.level == "standard"

    @pytest.mark.asyncio
    async def test_no_expand_when_already_expanded(self, settings: ObserverSettings) -> None:
        """Already at expanded level should not expand further."""
        regulator = SelfRegulator(settings)
        regulator._memory_client = AsyncMock()
        response_mock = MagicMock()
        response_mock.status_code = 200
        regulator._memory_client.post.return_value = response_mock
        regulator._autonomy.level = "expanded"

        now = datetime.now(timezone.utc)
        for i in range(6):
            change = Change(
                id=f"chg_{i:03d}",
                change_type=ChangeType.ROUTING,
                apply_tier=ApplyTier.AUTO,
                status=ChangeStatus.VALIDATED,
                proposed_at=(now - timedelta(days=1)).isoformat(),
            )
            regulator.record_change(change)

        result = await regulator.evaluate()

        assert result.adjustment_made is False
        assert result.new_autonomy == "expanded"


class TestAutonomyRestriction:
    """Tests for restricting autonomy on low success rate (<70%)."""

    @pytest.mark.asyncio
    async def test_restrict_from_standard_to_restricted(self, settings: ObserverSettings) -> None:
        """Success rate below 70% should restrict from standard to restricted."""
        regulator = SelfRegulator(settings)
        regulator._memory_client = AsyncMock()
        response_mock = MagicMock()
        response_mock.status_code = 200
        regulator._memory_client.post.return_value = response_mock

        now = datetime.now(timezone.utc)
        # 2 validated out of 8 resolved (only 25% success)
        for i in range(2):
            change = Change(
                id=f"chg_ok_{i}",
                change_type=ChangeType.ROUTING,
                apply_tier=ApplyTier.AUTO,
                status=ChangeStatus.VALIDATED,
                proposed_at=(now - timedelta(days=1)).isoformat(),
            )
            regulator.record_change(change)

        for i in range(6):
            change = Change(
                id=f"chg_fail_{i}",
                change_type=ChangeType.ROUTING,
                apply_tier=ApplyTier.AUTO,
                status=ChangeStatus.ROLLED_BACK,
                proposed_at=(now - timedelta(days=1)).isoformat(),
            )
            regulator.record_change(change)

        result = await regulator.evaluate()

        assert result.success_rate < 0.70
        assert result.adjustment_made is True
        assert result.new_autonomy == "restricted"
        assert regulator.autonomy.level == "restricted"
        assert regulator.autonomy.min_confidence > settings.auto_apply_min_confidence
        assert regulator.autonomy.allowed_auto_types == ["threshold"]

    @pytest.mark.asyncio
    async def test_restrict_from_expanded_to_standard(self, settings: ObserverSettings) -> None:
        """Low success rate when expanded should move to standard (not restricted)."""
        regulator = SelfRegulator(settings)
        regulator._memory_client = AsyncMock()
        response_mock = MagicMock()
        response_mock.status_code = 200
        regulator._memory_client.post.return_value = response_mock
        regulator._autonomy.level = "expanded"

        now = datetime.now(timezone.utc)
        # 1 validated, 5 rolled back = 16.7% success rate
        change = Change(
            id="chg_ok",
            change_type=ChangeType.ROUTING,
            apply_tier=ApplyTier.AUTO,
            status=ChangeStatus.VALIDATED,
            proposed_at=(now - timedelta(days=1)).isoformat(),
        )
        regulator.record_change(change)

        for i in range(5):
            change = Change(
                id=f"chg_fail_{i}",
                change_type=ChangeType.ROUTING,
                apply_tier=ApplyTier.AUTO,
                status=ChangeStatus.ROLLED_BACK,
                proposed_at=(now - timedelta(days=1)).isoformat(),
            )
            regulator.record_change(change)

        result = await regulator.evaluate()

        assert result.adjustment_made is True
        assert result.new_autonomy == "standard"

    @pytest.mark.asyncio
    async def test_no_restrict_when_already_restricted(self, settings: ObserverSettings) -> None:
        """Already at restricted level should not restrict further."""
        regulator = SelfRegulator(settings)
        regulator._memory_client = AsyncMock()
        response_mock = MagicMock()
        response_mock.status_code = 200
        regulator._memory_client.post.return_value = response_mock
        regulator._autonomy.level = "restricted"

        now = datetime.now(timezone.utc)
        for i in range(6):
            change = Change(
                id=f"chg_fail_{i}",
                change_type=ChangeType.ROUTING,
                apply_tier=ApplyTier.AUTO,
                status=ChangeStatus.ROLLED_BACK,
                proposed_at=(now - timedelta(days=1)).isoformat(),
            )
            regulator.record_change(change)

        result = await regulator.evaluate()

        assert result.adjustment_made is False
        assert result.new_autonomy == "restricted"


class TestBoundaryCases:
    """Tests for boundary conditions in self-evaluation."""

    @pytest.mark.asyncio
    async def test_exactly_90_percent_does_not_expand(self, settings: ObserverSettings) -> None:
        """Success rate at exactly 90% should NOT expand (threshold is >90%)."""
        regulator = SelfRegulator(settings)
        regulator._memory_client = AsyncMock()
        response_mock = MagicMock()
        response_mock.status_code = 200
        regulator._memory_client.post.return_value = response_mock

        now = datetime.now(timezone.utc)
        # 9 validated + 1 rolled_back = 90% success
        for i in range(9):
            change = Change(
                id=f"chg_ok_{i}",
                change_type=ChangeType.ROUTING,
                apply_tier=ApplyTier.AUTO,
                status=ChangeStatus.VALIDATED,
                proposed_at=(now - timedelta(days=1)).isoformat(),
            )
            regulator.record_change(change)

        change = Change(
            id="chg_fail",
            change_type=ChangeType.ROUTING,
            apply_tier=ApplyTier.AUTO,
            status=ChangeStatus.ROLLED_BACK,
            proposed_at=(now - timedelta(days=1)).isoformat(),
        )
        regulator.record_change(change)

        result = await regulator.evaluate()

        assert result.success_rate == pytest.approx(0.90)
        assert result.adjustment_made is False
        assert result.new_autonomy == "standard"

    @pytest.mark.asyncio
    async def test_exactly_70_percent_does_not_restrict(self, settings: ObserverSettings) -> None:
        """Success rate at exactly 70% should NOT restrict (threshold is <70%)."""
        regulator = SelfRegulator(settings)
        regulator._memory_client = AsyncMock()
        response_mock = MagicMock()
        response_mock.status_code = 200
        regulator._memory_client.post.return_value = response_mock

        now = datetime.now(timezone.utc)
        # 7 validated + 3 rolled_back = 70% success
        for i in range(7):
            change = Change(
                id=f"chg_ok_{i}",
                change_type=ChangeType.ROUTING,
                apply_tier=ApplyTier.AUTO,
                status=ChangeStatus.VALIDATED,
                proposed_at=(now - timedelta(days=1)).isoformat(),
            )
            regulator.record_change(change)

        for i in range(3):
            change = Change(
                id=f"chg_fail_{i}",
                change_type=ChangeType.ROUTING,
                apply_tier=ApplyTier.AUTO,
                status=ChangeStatus.ROLLED_BACK,
                proposed_at=(now - timedelta(days=1)).isoformat(),
            )
            regulator.record_change(change)

        result = await regulator.evaluate()

        assert result.success_rate == pytest.approx(0.70)
        assert result.adjustment_made is False
        assert result.new_autonomy == "standard"

    @pytest.mark.asyncio
    async def test_insufficient_data_no_adjustment(self, settings: ObserverSettings) -> None:
        """With fewer than 5 resolved changes, no adjustment should be made."""
        regulator = SelfRegulator(settings)
        regulator._memory_client = AsyncMock()
        response_mock = MagicMock()
        response_mock.status_code = 200
        regulator._memory_client.post.return_value = response_mock

        now = datetime.now(timezone.utc)
        # Only 3 resolved changes (below 5 minimum)
        for i in range(3):
            change = Change(
                id=f"chg_fail_{i}",
                change_type=ChangeType.ROUTING,
                apply_tier=ApplyTier.AUTO,
                status=ChangeStatus.ROLLED_BACK,
                proposed_at=(now - timedelta(days=1)).isoformat(),
            )
            regulator.record_change(change)

        result = await regulator.evaluate()

        # Even though success rate is 0%, insufficient data prevents adjustment
        assert result.adjustment_made is False

    @pytest.mark.asyncio
    async def test_no_changes_defaults_to_100_percent(self, settings: ObserverSettings) -> None:
        """No changes in the evaluation period should default to 100% success rate."""
        regulator = SelfRegulator(settings)
        regulator._memory_client = AsyncMock()
        response_mock = MagicMock()
        response_mock.status_code = 200
        regulator._memory_client.post.return_value = response_mock

        result = await regulator.evaluate()

        assert result.success_rate == 1.0
        assert result.adjustment_made is False

    @pytest.mark.asyncio
    async def test_old_changes_not_counted(self, settings: ObserverSettings) -> None:
        """Changes older than 7 days should not be counted in weekly evaluation."""
        regulator = SelfRegulator(settings)
        regulator._memory_client = AsyncMock()
        response_mock = MagicMock()
        response_mock.status_code = 200
        regulator._memory_client.post.return_value = response_mock

        # Add changes from 10 days ago
        old_time = datetime.now(timezone.utc) - timedelta(days=10)
        for i in range(10):
            change = Change(
                id=f"chg_old_{i}",
                change_type=ChangeType.ROUTING,
                apply_tier=ApplyTier.AUTO,
                status=ChangeStatus.ROLLED_BACK,
                proposed_at=old_time.isoformat(),
            )
            regulator.record_change(change)

        result = await regulator.evaluate()

        # Old changes should not be in the evaluation window
        assert result.total_changes == 0
        assert result.success_rate == 1.0
        assert result.adjustment_made is False


class TestMemoryPersistence:
    """Tests for autonomy level persistence."""

    @pytest.mark.asyncio
    async def test_persists_autonomy_on_evaluate(self, settings: ObserverSettings) -> None:
        """Evaluation should persist autonomy level to memory service."""
        regulator = SelfRegulator(settings)
        regulator._memory_client = AsyncMock()
        response_mock = MagicMock()
        response_mock.status_code = 200
        regulator._memory_client.post.return_value = response_mock

        await regulator.evaluate()

        regulator._memory_client.post.assert_called_once()
        call_args = regulator._memory_client.post.call_args
        assert call_args[0][0] == "/patterns"
        payload = call_args[1]["json"]
        assert payload["type"] == "observer_autonomy"
        assert "level" in payload["data"]

    @pytest.mark.asyncio
    async def test_restores_autonomy_on_start(self, settings: ObserverSettings) -> None:
        """Start should restore autonomy level from memory service."""
        regulator = SelfRegulator(settings)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "items": [{
                "data": {
                    "level": "expanded",
                    "min_confidence": 0.75,
                    "min_samples": 15,
                    "max_auto_applies_per_day": 15,
                    "allowed_auto_types": ["routing", "threshold", "pattern", "prompt"],
                    "last_adjusted": "2024-01-01T00:00:00+00:00",
                    "reason": "expanded from standard",
                }
            }]
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client_class.return_value = mock_client
            regulator._memory_client = mock_client

            await regulator._restore_autonomy_level()

        assert regulator.autonomy.level == "expanded"
        assert regulator.autonomy.min_confidence == 0.75
        assert regulator.autonomy.min_samples == 15

    @pytest.mark.asyncio
    async def test_handles_memory_service_failure_gracefully(self, settings: ObserverSettings) -> None:
        """Memory service failure should not crash the evaluator."""
        import httpx

        regulator = SelfRegulator(settings)
        regulator._memory_client = AsyncMock()
        regulator._memory_client.post.side_effect = httpx.HTTPError("Connection refused")

        now = datetime.now(timezone.utc)
        for i in range(6):
            change = Change(
                id=f"chg_{i}",
                change_type=ChangeType.ROUTING,
                apply_tier=ApplyTier.AUTO,
                status=ChangeStatus.VALIDATED,
                proposed_at=(now - timedelta(days=1)).isoformat(),
            )
            regulator.record_change(change)

        # Should not raise even though persistence fails
        result = await regulator.evaluate()
        assert result.success_rate == 1.0
