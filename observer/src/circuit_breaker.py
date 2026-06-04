"""Circuit breaker — stops all auto-applies after repeated failures.

State machine: CLOSED -> OPEN -> HALF_OPEN -> CLOSED
- CLOSED: Normal operation, auto-applies allowed
- OPEN: All changes forced to HUMAN tier, timer counting down
- HALF_OPEN: Allow ONE auto-apply as probe, if it fails -> re-trip

Trips when 3+ rollbacks occur within 6 hours.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import structlog

from observer.src.config import ObserverSettings

logger = structlog.get_logger(__name__)


class CircuitBreakerState(str, enum.Enum):
    """Circuit breaker states."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreakerStatus:
    """Current status of the circuit breaker."""

    state: CircuitBreakerState = CircuitBreakerState.CLOSED
    rollback_count_in_window: int = 0
    max_rollbacks: int = 3
    window_hours: int = 6
    cooldown_hours: int = 12
    tripped_at: str | None = None
    cooldown_ends_at: str | None = None
    half_open_probe_used: bool = False


class CircuitBreaker:
    """Circuit breaker for the observer's change pipeline.

    Tracks rollbacks in a rolling window. When the threshold is reached,
    trips to OPEN state where all changes are forced to human approval.

    After cooldown, enters HALF_OPEN where one probe change is allowed.
    If the probe succeeds, the breaker closes. If it fails, it re-trips.
    """

    def __init__(self, settings: ObserverSettings) -> None:
        self._settings = settings
        self._state: CircuitBreakerState = CircuitBreakerState.CLOSED
        self._tripped_at: datetime | None = None
        self._rollbacks: list[datetime] = []
        self._half_open_probe_used: bool = False

    @property
    def is_open(self) -> bool:
        """Whether the circuit breaker is currently blocking auto-applies."""
        self._check_cooldown()
        return self._state in (CircuitBreakerState.OPEN, CircuitBreakerState.HALF_OPEN)

    @property
    def state(self) -> CircuitBreakerState:
        """Current state of the circuit breaker."""
        self._check_cooldown()
        return self._state

    def record_rollback(self) -> bool:
        """Record a rollback and check if the breaker should trip.

        Returns:
            True if the circuit breaker tripped as a result.
        """
        now = datetime.now(timezone.utc)
        self._rollbacks.append(now)

        # If in HALF_OPEN, any failure re-trips immediately
        if self._state == CircuitBreakerState.HALF_OPEN:
            self._trip(now)
            logger.warning(
                "circuit_breaker_retripped",
                reason="half_open_probe_failed",
            )
            return True

        # Count rollbacks in window
        recent_count = self._count_recent_rollbacks()
        if recent_count >= self._settings.circuit_breaker_max_rollbacks:
            self._trip(now)
            logger.warning(
                "circuit_breaker_tripped",
                rollbacks_in_window=recent_count,
                window_hours=self._settings.circuit_breaker_window_hours,
            )
            return True

        return False

    def record_success(self) -> None:
        """Record a successful change application.

        If in HALF_OPEN state, a success closes the breaker.
        """
        if self._state == CircuitBreakerState.HALF_OPEN:
            self._state = CircuitBreakerState.CLOSED
            self._tripped_at = None
            self._half_open_probe_used = False
            logger.info("circuit_breaker_closed", reason="half_open_probe_succeeded")

    def can_auto_apply(self) -> bool:
        """Whether an auto-apply is currently allowed.

        In HALF_OPEN state, allows exactly one probe.
        """
        self._check_cooldown()

        if self._state == CircuitBreakerState.CLOSED:
            return True
        elif self._state == CircuitBreakerState.HALF_OPEN:
            if not self._half_open_probe_used:
                self._half_open_probe_used = True
                logger.info("circuit_breaker_probe_allowed")
                return True
            return False
        else:
            return False

    def reset(self) -> dict[str, str]:
        """Manually reset the circuit breaker (admin action).

        Returns:
            Dict with previous and new state.
        """
        previous = self._state.value
        self._state = CircuitBreakerState.CLOSED
        self._tripped_at = None
        self._half_open_probe_used = False
        logger.info("circuit_breaker_manually_reset", previous_state=previous)
        return {"state": "closed", "previous": previous}

    def get_status(self) -> CircuitBreakerStatus:
        """Get detailed circuit breaker status."""
        self._check_cooldown()
        recent_count = self._count_recent_rollbacks()

        cooldown_ends: str | None = None
        if self._tripped_at:
            from datetime import timedelta
            ends = self._tripped_at + timedelta(hours=self._settings.circuit_breaker_cooldown_hours)
            cooldown_ends = ends.isoformat()

        return CircuitBreakerStatus(
            state=self._state,
            rollback_count_in_window=recent_count,
            max_rollbacks=self._settings.circuit_breaker_max_rollbacks,
            window_hours=self._settings.circuit_breaker_window_hours,
            cooldown_hours=self._settings.circuit_breaker_cooldown_hours,
            tripped_at=self._tripped_at.isoformat() if self._tripped_at else None,
            cooldown_ends_at=cooldown_ends,
            half_open_probe_used=self._half_open_probe_used,
        )

    def _trip(self, at: datetime) -> None:
        """Trip the circuit breaker to OPEN state."""
        self._state = CircuitBreakerState.OPEN
        self._tripped_at = at
        self._half_open_probe_used = False

    def _check_cooldown(self) -> None:
        """Check if cooldown has elapsed and transition to HALF_OPEN."""
        if self._state != CircuitBreakerState.OPEN or self._tripped_at is None:
            return

        from datetime import timedelta
        now = datetime.now(timezone.utc)
        cooldown_end = self._tripped_at + timedelta(
            hours=self._settings.circuit_breaker_cooldown_hours
        )

        if now >= cooldown_end:
            self._state = CircuitBreakerState.HALF_OPEN
            self._half_open_probe_used = False
            logger.info(
                "circuit_breaker_half_open",
                reason="cooldown_elapsed",
                cooldown_hours=self._settings.circuit_breaker_cooldown_hours,
            )

    def _count_recent_rollbacks(self) -> int:
        """Count rollbacks within the configured window."""
        from datetime import timedelta
        now = datetime.now(timezone.utc)
        window_start = now - timedelta(hours=self._settings.circuit_breaker_window_hours)
        return sum(1 for rb in self._rollbacks if rb >= window_start)
