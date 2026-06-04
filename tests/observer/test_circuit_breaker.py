"""Unit tests for observer circuit breaker.

Tests state transitions: CLOSED -> OPEN -> HALF_OPEN -> CLOSED.
Verifies 3 rollbacks in 6h triggers freeze, reset works, single rollback does not freeze.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from observer.src.circuit_breaker import CircuitBreaker, CircuitBreakerState
from observer.src.config import ObserverSettings


class TestCircuitBreakerTripping:
    """Tests for circuit breaker trip logic."""

    def test_three_rollbacks_in_window_trips_breaker(self, settings: ObserverSettings) -> None:
        """3 rollbacks within 6 hours should trip the circuit breaker to OPEN."""
        cb = CircuitBreaker(settings)

        assert cb.state == CircuitBreakerState.CLOSED
        assert not cb.is_open

        # First rollback - should not trip
        tripped = cb.record_rollback()
        assert not tripped
        assert cb.state == CircuitBreakerState.CLOSED

        # Second rollback - should not trip
        tripped = cb.record_rollback()
        assert not tripped
        assert cb.state == CircuitBreakerState.CLOSED

        # Third rollback - should trip
        tripped = cb.record_rollback()
        assert tripped
        assert cb.state == CircuitBreakerState.OPEN
        assert cb.is_open

    def test_single_rollback_does_not_trip(self, settings: ObserverSettings) -> None:
        """A single rollback should never trip the circuit breaker."""
        cb = CircuitBreaker(settings)

        tripped = cb.record_rollback()
        assert not tripped
        assert cb.state == CircuitBreakerState.CLOSED
        assert not cb.is_open
        assert cb.can_auto_apply()

    def test_two_rollbacks_do_not_trip(self, settings: ObserverSettings) -> None:
        """Two rollbacks are below the threshold of 3."""
        cb = CircuitBreaker(settings)

        cb.record_rollback()
        tripped = cb.record_rollback()

        assert not tripped
        assert cb.state == CircuitBreakerState.CLOSED

    def test_rollbacks_outside_window_do_not_count(self, settings: ObserverSettings) -> None:
        """Rollbacks older than 6 hours should not contribute to the trip count."""
        cb = CircuitBreaker(settings)

        # Inject rollbacks from 7 hours ago (outside the 6h window)
        old_time = datetime.now(timezone.utc) - timedelta(hours=7)
        cb._rollbacks = [old_time, old_time, old_time]

        # New rollback should not trip since the old ones are outside window
        tripped = cb.record_rollback()
        assert not tripped
        assert cb.state == CircuitBreakerState.CLOSED

    def test_can_auto_apply_blocked_when_open(self, settings: ObserverSettings) -> None:
        """Auto-apply should be blocked when breaker is OPEN."""
        cb = CircuitBreaker(settings)

        # Trip the breaker
        cb.record_rollback()
        cb.record_rollback()
        cb.record_rollback()

        assert not cb.can_auto_apply()


class TestCircuitBreakerReset:
    """Tests for manual and automatic reset."""

    def test_manual_reset_restores_closed_state(self, settings: ObserverSettings) -> None:
        """Manual reset should return circuit breaker to CLOSED state."""
        cb = CircuitBreaker(settings)

        # Trip the breaker
        cb.record_rollback()
        cb.record_rollback()
        cb.record_rollback()
        assert cb.state == CircuitBreakerState.OPEN

        # Reset
        result = cb.reset()
        assert result["state"] == "closed"
        assert result["previous"] == "open"
        assert cb.state == CircuitBreakerState.CLOSED
        assert cb.can_auto_apply()

    def test_reset_from_half_open(self, settings: ObserverSettings) -> None:
        """Reset from HALF_OPEN should also work."""
        cb = CircuitBreaker(settings)

        # Force to HALF_OPEN state
        cb._state = CircuitBreakerState.HALF_OPEN

        result = cb.reset()
        assert result["state"] == "closed"
        assert result["previous"] == "half_open"
        assert cb.state == CircuitBreakerState.CLOSED

    def test_reset_from_closed_is_noop(self, settings: ObserverSettings) -> None:
        """Resetting an already closed breaker should not cause errors."""
        cb = CircuitBreaker(settings)

        result = cb.reset()
        assert result["state"] == "closed"
        assert result["previous"] == "closed"


class TestCircuitBreakerCooldown:
    """Tests for cooldown and HALF_OPEN transition."""

    def test_transitions_to_half_open_after_cooldown(self, settings: ObserverSettings) -> None:
        """After cooldown period (12h), breaker should transition to HALF_OPEN."""
        cb = CircuitBreaker(settings)

        # Trip the breaker
        cb.record_rollback()
        cb.record_rollback()
        cb.record_rollback()
        assert cb.state == CircuitBreakerState.OPEN

        # Simulate time passing beyond cooldown
        cb._tripped_at = datetime.now(timezone.utc) - timedelta(hours=13)

        # Accessing state should trigger cooldown check
        assert cb.state == CircuitBreakerState.HALF_OPEN

    def test_half_open_allows_one_probe(self, settings: ObserverSettings) -> None:
        """HALF_OPEN state should allow exactly one probe auto-apply."""
        cb = CircuitBreaker(settings)
        cb._state = CircuitBreakerState.HALF_OPEN

        # First attempt should be allowed
        assert cb.can_auto_apply()

        # Second attempt should be blocked
        assert not cb.can_auto_apply()

    def test_probe_success_closes_breaker(self, settings: ObserverSettings) -> None:
        """Successful probe in HALF_OPEN should close the breaker."""
        cb = CircuitBreaker(settings)
        cb._state = CircuitBreakerState.HALF_OPEN

        cb.record_success()

        assert cb.state == CircuitBreakerState.CLOSED
        assert cb.can_auto_apply()

    def test_probe_failure_retrips_breaker(self, settings: ObserverSettings) -> None:
        """Failed probe in HALF_OPEN should re-trip the breaker to OPEN."""
        cb = CircuitBreaker(settings)
        cb._state = CircuitBreakerState.HALF_OPEN

        tripped = cb.record_rollback()

        assert tripped
        assert cb.state == CircuitBreakerState.OPEN

    def test_stays_open_before_cooldown_elapsed(self, settings: ObserverSettings) -> None:
        """Breaker should remain OPEN if cooldown has not elapsed."""
        cb = CircuitBreaker(settings)

        # Trip the breaker
        cb.record_rollback()
        cb.record_rollback()
        cb.record_rollback()

        # Tripped recently (less than 12h cooldown)
        cb._tripped_at = datetime.now(timezone.utc) - timedelta(hours=6)

        assert cb.state == CircuitBreakerState.OPEN
        assert not cb.can_auto_apply()


class TestCircuitBreakerStatus:
    """Tests for status reporting."""

    def test_status_reports_correct_state(self, settings: ObserverSettings) -> None:
        """get_status should report accurate circuit breaker state."""
        cb = CircuitBreaker(settings)

        status = cb.get_status()
        assert status.state == CircuitBreakerState.CLOSED
        assert status.rollback_count_in_window == 0
        assert status.max_rollbacks == 3
        assert status.window_hours == 6
        assert status.cooldown_hours == 12

    def test_status_after_rollbacks(self, settings: ObserverSettings) -> None:
        """Status should reflect rollback count accurately."""
        cb = CircuitBreaker(settings)

        cb.record_rollback()
        cb.record_rollback()

        status = cb.get_status()
        assert status.rollback_count_in_window == 2
        assert status.state == CircuitBreakerState.CLOSED

    def test_status_after_trip(self, settings: ObserverSettings) -> None:
        """Status should show OPEN state and trip time after breaker trips."""
        cb = CircuitBreaker(settings)

        cb.record_rollback()
        cb.record_rollback()
        cb.record_rollback()

        status = cb.get_status()
        assert status.state == CircuitBreakerState.OPEN
        assert status.tripped_at is not None
        assert status.cooldown_ends_at is not None
        assert status.rollback_count_in_window == 3

    def test_success_in_closed_state_is_noop(self, settings: ObserverSettings) -> None:
        """Recording success in CLOSED state should not change anything."""
        cb = CircuitBreaker(settings)

        cb.record_success()  # Should not raise

        assert cb.state == CircuitBreakerState.CLOSED
