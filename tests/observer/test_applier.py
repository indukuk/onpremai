"""Unit tests for observer change applier.

Tests the 3-tier apply engine: tier 1 auto-applies, tier 2 canary, tier 3 proposes only.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from observer.src.changes.applier import ChangeApplier
from observer.src.changes.proposal import ApplyTier, Change, ChangeStatus, ChangeType
from observer.src.config import ObserverSettings


class TestTier1AutoApply:
    """Tests for Tier 1 (AUTO) change application."""

    @pytest.mark.asyncio
    async def test_auto_apply_success(self, settings: ObserverSettings, auto_change: Change) -> None:
        """Tier 1 changes should be directly applied via gateway admin API."""
        applier = ChangeApplier(settings)

        # Mock HTTP client
        mock_client = AsyncMock()
        success_response = MagicMock()
        success_response.status_code = 200
        success_response.json.return_value = {"status": "ok"}
        mock_client.get.return_value = success_response
        mock_client.post.return_value = success_response
        applier._http_client = mock_client

        result = await applier.apply(auto_change)

        assert result.status == ChangeStatus.APPLIED
        assert result.applied_at is not None
        # Should have scheduled a validation
        validations = applier.get_pending_validations()
        assert len(validations) == 1
        assert validations[0]["change_id"] == auto_change.id

    @pytest.mark.asyncio
    async def test_auto_apply_takes_snapshot(self, settings: ObserverSettings, auto_change: Change) -> None:
        """Auto-apply should take a snapshot before applying."""
        applier = ChangeApplier(settings)

        mock_client = AsyncMock()
        success_response = MagicMock()
        success_response.status_code = 200
        success_response.json.return_value = {"routing": {"evaluate_control": "mid"}}
        mock_client.get.return_value = success_response
        mock_client.post.return_value = success_response
        applier._http_client = mock_client

        result = await applier.apply(auto_change)

        assert result.snapshot is not None
        assert "taken_at" in result.snapshot

    @pytest.mark.asyncio
    async def test_auto_apply_failure_rolls_back(self, settings: ObserverSettings, auto_change: Change) -> None:
        """Failed auto-apply should set status to ROLLED_BACK."""
        applier = ChangeApplier(settings)

        mock_client = AsyncMock()
        # Snapshot succeeds
        snapshot_response = MagicMock()
        snapshot_response.status_code = 200
        snapshot_response.json.return_value = {}
        mock_client.get.return_value = snapshot_response

        # Apply fails
        fail_response = MagicMock()
        fail_response.status_code = 500
        mock_client.post.return_value = fail_response
        applier._http_client = mock_client

        result = await applier.apply(auto_change)

        assert result.status == ChangeStatus.ROLLED_BACK

    @pytest.mark.asyncio
    async def test_auto_apply_no_client_fails(self, settings: ObserverSettings, auto_change: Change) -> None:
        """Auto-apply without HTTP client should fail gracefully."""
        applier = ChangeApplier(settings)
        # No client initialized

        result = await applier.apply(auto_change)

        assert result.status == ChangeStatus.ROLLED_BACK

    @pytest.mark.asyncio
    async def test_auto_apply_routing_change(self, settings: ObserverSettings) -> None:
        """Routing change should POST to /admin/routing endpoint."""
        applier = ChangeApplier(settings)

        mock_client = AsyncMock()
        success_response = MagicMock()
        success_response.status_code = 200
        success_response.json.return_value = {}
        mock_client.get.return_value = success_response
        mock_client.post.return_value = success_response
        applier._http_client = mock_client

        change = Change(
            id="chg_routing",
            change_type=ChangeType.ROUTING,
            apply_tier=ApplyTier.AUTO,
            task="evaluate_control",
            config_diff={"task_routing": {"evaluate_control": "strong"}},
        )

        await applier.apply(change)

        # Verify POST was called to /admin/routing
        post_calls = mock_client.post.call_args_list
        routing_calls = [c for c in post_calls if "/admin/routing" in str(c)]
        assert len(routing_calls) > 0

    @pytest.mark.asyncio
    async def test_auto_apply_threshold_change(self, settings: ObserverSettings) -> None:
        """Threshold change should POST to /admin/threshold endpoint."""
        applier = ChangeApplier(settings)

        mock_client = AsyncMock()
        success_response = MagicMock()
        success_response.status_code = 200
        success_response.json.return_value = {}
        mock_client.get.return_value = success_response
        mock_client.post.return_value = success_response
        applier._http_client = mock_client

        change = Change(
            id="chg_threshold",
            change_type=ChangeType.THRESHOLD,
            apply_tier=ApplyTier.AUTO,
            task="evaluate_control",
            config_diff={"task": "evaluate_control", "threshold": 0.85},
        )

        await applier.apply(change)

        post_calls = mock_client.post.call_args_list
        threshold_calls = [c for c in post_calls if "/admin/threshold" in str(c)]
        assert len(threshold_calls) > 0


class TestTier2Canary:
    """Tests for Tier 2 (CANARY) change application."""

    @pytest.mark.asyncio
    async def test_canary_deploy_success(self, settings: ObserverSettings, canary_change: Change) -> None:
        """Successful canary deploy should set status to CANARY_RUNNING."""
        applier = ChangeApplier(settings)

        mock_client = AsyncMock()
        success_response = MagicMock()
        success_response.status_code = 200
        mock_client.post.return_value = success_response
        applier._http_client = mock_client

        result = await applier.apply(canary_change)

        assert result.status == ChangeStatus.CANARY_RUNNING
        assert result.applied_at is not None

    @pytest.mark.asyncio
    async def test_canary_deploy_sets_traffic_percentage(self, settings: ObserverSettings, canary_change: Change) -> None:
        """Canary deploy should use configured traffic percentage."""
        applier = ChangeApplier(settings)

        mock_client = AsyncMock()
        success_response = MagicMock()
        success_response.status_code = 200
        mock_client.post.return_value = success_response
        applier._http_client = mock_client

        await applier.apply(canary_change)

        # Verify payload contains traffic_pct
        call_args = mock_client.post.call_args
        payload = call_args[1]["json"]
        assert payload["traffic_pct"] == settings.canary_traffic_pct
        assert payload["min_samples"] == settings.canary_min_samples

    @pytest.mark.asyncio
    async def test_canary_deploy_failure_stays_proposed(self, settings: ObserverSettings, canary_change: Change) -> None:
        """Failed canary deploy should keep status as PROPOSED."""
        applier = ChangeApplier(settings)

        mock_client = AsyncMock()
        fail_response = MagicMock()
        fail_response.status_code = 500
        fail_response.text = "Internal Server Error"
        mock_client.post.return_value = fail_response
        applier._http_client = mock_client

        result = await applier.apply(canary_change)

        assert result.status == ChangeStatus.PROPOSED

    @pytest.mark.asyncio
    async def test_canary_deploy_http_error_stays_proposed(self, settings: ObserverSettings, canary_change: Change) -> None:
        """HTTP connection error during canary deploy should keep PROPOSED status."""
        import httpx

        applier = ChangeApplier(settings)

        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.HTTPError("Connection refused")
        applier._http_client = mock_client

        result = await applier.apply(canary_change)

        assert result.status == ChangeStatus.PROPOSED

    @pytest.mark.asyncio
    async def test_canary_no_client_stays_proposed(self, settings: ObserverSettings, canary_change: Change) -> None:
        """Canary without HTTP client should stay PROPOSED."""
        applier = ChangeApplier(settings)
        # No client initialized

        result = await applier.apply(canary_change)

        assert result.status == ChangeStatus.PROPOSED


class TestTier3Human:
    """Tests for Tier 3 (HUMAN) change application."""

    @pytest.mark.asyncio
    async def test_human_change_queued(self, settings: ObserverSettings, human_change: Change) -> None:
        """Human-tier changes should be queued for approval, not applied."""
        applier = ChangeApplier(settings)

        result = await applier.apply(human_change)

        assert result.status == ChangeStatus.PROPOSED
        assert result.applied_at is None

        # Should be in human queue
        queue = applier.get_human_queue()
        assert len(queue) == 1
        assert queue[0].id == human_change.id

    @pytest.mark.asyncio
    async def test_human_approve_changes_status(self, settings: ObserverSettings, human_change: Change) -> None:
        """Approving a queued change should set APPROVED status."""
        applier = ChangeApplier(settings)

        await applier.apply(human_change)

        approved = applier.approve_change(human_change.id)
        assert approved is not None
        assert approved.status == ChangeStatus.APPROVED

        # Should be removed from queue
        assert len(applier.get_human_queue()) == 0

    @pytest.mark.asyncio
    async def test_human_reject_changes_status(self, settings: ObserverSettings, human_change: Change) -> None:
        """Rejecting a queued change should set REJECTED status."""
        applier = ChangeApplier(settings)

        await applier.apply(human_change)

        rejected = applier.reject_change(human_change.id)
        assert rejected is not None
        assert rejected.status == ChangeStatus.REJECTED
        assert len(applier.get_human_queue()) == 0

    @pytest.mark.asyncio
    async def test_approve_nonexistent_returns_none(self, settings: ObserverSettings) -> None:
        """Approving a non-existent change ID should return None."""
        applier = ChangeApplier(settings)

        result = applier.approve_change("nonexistent_id")
        assert result is None

    @pytest.mark.asyncio
    async def test_reject_nonexistent_returns_none(self, settings: ObserverSettings) -> None:
        """Rejecting a non-existent change ID should return None."""
        applier = ChangeApplier(settings)

        result = applier.reject_change("nonexistent_id")
        assert result is None


class TestCircuitBreakerOverride:
    """Tests for circuit breaker forcing changes to HUMAN tier."""

    @pytest.mark.asyncio
    async def test_circuit_breaker_forces_auto_to_human(
        self, settings: ObserverSettings, auto_change: Change
    ) -> None:
        """Open circuit breaker should force AUTO tier changes to HUMAN tier."""
        applier = ChangeApplier(settings)

        result = await applier.apply(auto_change, circuit_breaker_open=True)

        assert result.apply_tier == ApplyTier.HUMAN
        assert result.status == ChangeStatus.PROPOSED
        assert len(applier.get_human_queue()) == 1

    @pytest.mark.asyncio
    async def test_circuit_breaker_forces_canary_to_human(
        self, settings: ObserverSettings, canary_change: Change
    ) -> None:
        """Open circuit breaker should force CANARY tier changes to HUMAN tier."""
        applier = ChangeApplier(settings)

        result = await applier.apply(canary_change, circuit_breaker_open=True)

        assert result.apply_tier == ApplyTier.HUMAN
        assert result.status == ChangeStatus.PROPOSED

    @pytest.mark.asyncio
    async def test_circuit_breaker_does_not_affect_human_tier(
        self, settings: ObserverSettings, human_change: Change
    ) -> None:
        """Human-tier changes should not be affected by circuit breaker."""
        applier = ChangeApplier(settings)

        result = await applier.apply(human_change, circuit_breaker_open=True)

        assert result.apply_tier == ApplyTier.HUMAN
        assert result.status == ChangeStatus.PROPOSED

    @pytest.mark.asyncio
    async def test_no_override_when_circuit_breaker_closed(
        self, settings: ObserverSettings, auto_change: Change
    ) -> None:
        """Closed circuit breaker should not interfere with normal tier routing."""
        applier = ChangeApplier(settings)

        mock_client = AsyncMock()
        success_response = MagicMock()
        success_response.status_code = 200
        success_response.json.return_value = {}
        mock_client.get.return_value = success_response
        mock_client.post.return_value = success_response
        applier._http_client = mock_client

        result = await applier.apply(auto_change, circuit_breaker_open=False)

        assert result.apply_tier == ApplyTier.AUTO
        assert result.status == ChangeStatus.APPLIED


class TestValidationTracking:
    """Tests for pending validation management."""

    @pytest.mark.asyncio
    async def test_clear_validation(self, settings: ObserverSettings, auto_change: Change) -> None:
        """clear_validation should remove a specific change from pending list."""
        applier = ChangeApplier(settings)

        mock_client = AsyncMock()
        success_response = MagicMock()
        success_response.status_code = 200
        success_response.json.return_value = {}
        mock_client.get.return_value = success_response
        mock_client.post.return_value = success_response
        applier._http_client = mock_client

        await applier.apply(auto_change)
        assert len(applier.get_pending_validations()) == 1

        applier.clear_validation(auto_change.id)
        assert len(applier.get_pending_validations()) == 0

    @pytest.mark.asyncio
    async def test_clear_nonexistent_validation_is_safe(self, settings: ObserverSettings) -> None:
        """Clearing a non-existent validation should not raise."""
        applier = ChangeApplier(settings)
        applier.clear_validation("nonexistent")
        assert len(applier.get_pending_validations()) == 0


class TestLifecycle:
    """Tests for applier start/close lifecycle."""

    @pytest.mark.asyncio
    async def test_start_creates_http_client(self, settings: ObserverSettings) -> None:
        """Start should initialize the HTTP client."""
        applier = ChangeApplier(settings)
        assert applier._http_client is None

        await applier.start()
        assert applier._http_client is not None

        await applier.close()
        assert applier._http_client is None

    @pytest.mark.asyncio
    async def test_close_without_start_is_safe(self, settings: ObserverSettings) -> None:
        """Closing without starting should not raise."""
        applier = ChangeApplier(settings)
        await applier.close()  # Should not raise
