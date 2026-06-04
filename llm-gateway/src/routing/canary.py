from __future__ import annotations

import random
import time
from threading import Lock

import structlog

from src.models import CanaryConfig, CanaryMetrics, CanaryStatus, ModelConfig, RoutingConfig

logger = structlog.get_logger(__name__)


class CanaryManager:
    """Manages canary traffic splitting experiments.

    Routes a percentage of traffic to a canary model and tracks
    metrics for both control and canary variants.
    """

    def __init__(self) -> None:
        self._experiments: dict[str, _CanaryExperiment] = {}
        self._lock = Lock()

    def update_from_config(self, config: RoutingConfig) -> None:
        """Sync canary experiments from routing config."""
        with self._lock:
            configured_keys = set(config.canary.keys())
            # Remove experiments no longer in config
            for key in list(self._experiments.keys()):
                if key not in configured_keys:
                    del self._experiments[key]
            # Add/update experiments from config
            for key, canary_cfg in config.canary.items():
                if key not in self._experiments:
                    self._experiments[key] = _CanaryExperiment(
                        task_key=key,
                        config=canary_cfg,
                    )
                else:
                    self._experiments[key].update_config(canary_cfg)

    def should_use_canary(self, agent: str, task: str) -> tuple[bool, str]:
        """Determine if this request should go to canary model.

        Args:
            agent: Agent name
            task: Task name

        Returns:
            Tuple of (use_canary: bool, variant: str "control" or "canary")
        """
        key = f"{agent}/{task}"
        experiment = self._experiments.get(key)
        if experiment is None:
            # Try task-only key
            experiment = self._experiments.get(task)
            if experiment is None:
                return False, "control"

        roll = random.randint(1, 100)
        if roll <= experiment.config.traffic_pct:
            return True, "canary"
        return False, "control"

    def get_canary_model_id(self, agent: str, task: str) -> str | None:
        """Get the canary model ID for a task if experiment is active."""
        key = f"{agent}/{task}"
        experiment = self._experiments.get(key)
        if experiment is None:
            experiment = self._experiments.get(task)
        if experiment is None:
            return None
        return experiment.config.model

    def record_result(
        self,
        agent: str,
        task: str,
        variant: str,
        confidence: float,
        latency_ms: int,
        error: bool,
        escalated: bool,
        cost_usd: float,
    ) -> None:
        """Record a result for the experiment."""
        key = f"{agent}/{task}"
        experiment = self._experiments.get(key)
        if experiment is None:
            experiment = self._experiments.get(task)
        if experiment is None:
            return

        experiment.record(
            variant=variant,
            confidence=confidence,
            latency_ms=latency_ms,
            error=error,
            escalated=escalated,
            cost_usd=cost_usd,
        )

    def get_status(self, task: str) -> CanaryStatus | None:
        """Get the status of a canary experiment."""
        # Try with task key directly or any key containing the task
        experiment = self._experiments.get(task)
        if experiment is None:
            for key, exp in self._experiments.items():
                if task in key:
                    experiment = exp
                    break
        if experiment is None:
            return None
        return experiment.get_status()

    def set_canary(
        self,
        task_key: str,
        model: str,
        traffic_pct: int = 20,
        min_samples: int = 30,
    ) -> CanaryStatus:
        """Start or update a canary experiment."""
        config = CanaryConfig(
            model=model,
            traffic_pct=traffic_pct,
            min_samples=min_samples,
        )
        with self._lock:
            self._experiments[task_key] = _CanaryExperiment(
                task_key=task_key,
                config=config,
            )
        logger.info(
            "canary_started",
            task_key=task_key,
            model=model,
            traffic_pct=traffic_pct,
        )
        return self._experiments[task_key].get_status()

    def promote_canary(self, task: str) -> bool:
        """Promote canary to 100% (makes it primary)."""
        experiment = self._find_experiment(task)
        if experiment is None:
            return False
        with self._lock:
            del self._experiments[experiment.task_key]
        logger.info("canary_promoted", task=task, model=experiment.config.model)
        return True

    def rollback_canary(self, task: str) -> bool:
        """Remove canary experiment, revert to control only."""
        experiment = self._find_experiment(task)
        if experiment is None:
            return False
        with self._lock:
            del self._experiments[experiment.task_key]
        logger.info("canary_rolled_back", task=task)
        return True

    def _find_experiment(self, task: str) -> _CanaryExperiment | None:
        """Find experiment by exact key or partial match."""
        experiment = self._experiments.get(task)
        if experiment is not None:
            return experiment
        for key, exp in self._experiments.items():
            if task in key:
                return exp
        return None


class _CanaryExperiment:
    """Internal tracking state for one canary experiment."""

    def __init__(self, task_key: str, config: CanaryConfig) -> None:
        self.task_key = task_key
        self.config = config
        self.started_at = time.time()
        self._control_samples: list[_Sample] = []
        self._canary_samples: list[_Sample] = []
        self._lock = Lock()

    def update_config(self, config: CanaryConfig) -> None:
        """Update experiment config (e.g., traffic percentage)."""
        self.config = config

    def record(
        self,
        variant: str,
        confidence: float,
        latency_ms: int,
        error: bool,
        escalated: bool,
        cost_usd: float,
    ) -> None:
        """Record a sample for the given variant."""
        sample = _Sample(
            confidence=confidence,
            latency_ms=latency_ms,
            error=error,
            escalated=escalated,
            cost_usd=cost_usd,
            timestamp=time.time(),
        )
        with self._lock:
            if variant == "canary":
                self._canary_samples.append(sample)
            else:
                self._control_samples.append(sample)

    def get_status(self) -> CanaryStatus:
        """Compute metrics for both variants."""
        return CanaryStatus(
            task=self.task_key,
            active=True,
            model=self.config.model,
            traffic_pct=self.config.traffic_pct,
            started_at=self.started_at,
            control=self._compute_metrics(self._control_samples),
            canary=self._compute_metrics(self._canary_samples),
        )

    def _compute_metrics(self, samples: list[_Sample]) -> CanaryMetrics:
        """Aggregate metrics from samples."""
        if not samples:
            return CanaryMetrics()

        count = len(samples)
        confidences = [s.confidence for s in samples]
        latencies = [s.latency_ms for s in samples]
        errors = sum(1 for s in samples if s.error)
        escalations = sum(1 for s in samples if s.escalated)
        costs = [s.cost_usd for s in samples]

        sorted_latencies = sorted(latencies)
        p95_idx = min(int(count * 0.95), count - 1)

        return CanaryMetrics(
            sample_count=count,
            avg_confidence=sum(confidences) / count,
            avg_latency_ms=sum(latencies) / count,
            p95_latency_ms=float(sorted_latencies[p95_idx]),
            error_rate=errors / count,
            escalation_rate=escalations / count,
            avg_cost_usd=sum(costs) / count,
        )


class _Sample:
    """A single recorded sample from a request."""

    __slots__ = ("confidence", "latency_ms", "error", "escalated", "cost_usd", "timestamp")

    def __init__(
        self,
        confidence: float,
        latency_ms: int,
        error: bool,
        escalated: bool,
        cost_usd: float,
        timestamp: float,
    ) -> None:
        self.confidence = confidence
        self.latency_ms = latency_ms
        self.error = error
        self.escalated = escalated
        self.cost_usd = cost_usd
        self.timestamp = timestamp
