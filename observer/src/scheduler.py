"""APScheduler setup — manages periodic observer tasks.

Configures four recurring jobs:
- quality_check: every hour — detect issues in gateway metrics
- prompt_optimization: every 6 hours — analyze prompt patterns, propose improvements
- model_fit: daily — run drift detection, bias checks
- self_eval: weekly — evaluate observer's own changes success rate
"""

from __future__ import annotations

from typing import Any

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from observer.src.config import ObserverSettings

logger = structlog.get_logger(__name__)


class ObserverScheduler:
    """Manages all periodic observer tasks via APScheduler.

    Wraps an AsyncIOScheduler with the observer's specific jobs.
    Supports graceful start/stop and runtime schedule adjustments.
    """

    def __init__(self, settings: ObserverSettings) -> None:
        self._settings = settings
        self._scheduler: AsyncIOScheduler = AsyncIOScheduler(
            job_defaults={
                "coalesce": True,
                "max_instances": 1,
                "misfire_grace_time": 300,
            }
        )
        self._quality_check_fn: Any = None
        self._prompt_optimization_fn: Any = None
        self._model_fit_fn: Any = None
        self._self_eval_fn: Any = None
        self._last_run_times: dict[str, str] = {}

    def configure(
        self,
        quality_check_fn: Any,
        prompt_optimization_fn: Any,
        model_fit_fn: Any,
        self_eval_fn: Any,
    ) -> None:
        """Register the callback functions for each scheduled job.

        Args:
            quality_check_fn: Async function for hourly quality checks.
            prompt_optimization_fn: Async function for prompt analysis.
            model_fit_fn: Async function for daily drift/bias detection.
            self_eval_fn: Async function for weekly self-evaluation.
        """
        self._quality_check_fn = quality_check_fn
        self._prompt_optimization_fn = prompt_optimization_fn
        self._model_fit_fn = model_fit_fn
        self._self_eval_fn = self_eval_fn

    def start(self) -> None:
        """Start the scheduler and register all jobs."""
        if not self._quality_check_fn:
            raise RuntimeError("Scheduler not configured. Call configure() before start().")

        # Quality check — every hour
        self._scheduler.add_job(
            self._run_quality_check,
            trigger=IntervalTrigger(seconds=self._settings.schedule_quality_sec),
            id="quality_check",
            name="Hourly quality check",
            replace_existing=True,
        )

        # Prompt optimization — every 6 hours
        self._scheduler.add_job(
            self._run_prompt_optimization,
            trigger=IntervalTrigger(seconds=self._settings.schedule_prompts_sec),
            id="prompt_optimization",
            name="Prompt pattern optimization",
            replace_existing=True,
        )

        # Model fit — daily
        self._scheduler.add_job(
            self._run_model_fit,
            trigger=IntervalTrigger(seconds=self._settings.schedule_model_fit_sec),
            id="model_fit",
            name="Daily model drift and bias check",
            replace_existing=True,
        )

        # Self-evaluation — weekly
        self._scheduler.add_job(
            self._run_self_eval,
            trigger=IntervalTrigger(seconds=self._settings.schedule_self_eval_sec),
            id="self_eval",
            name="Weekly self-evaluation",
            replace_existing=True,
        )

        self._scheduler.start()
        logger.info(
            "scheduler_started",
            quality_sec=self._settings.schedule_quality_sec,
            prompt_sec=self._settings.schedule_prompts_sec,
            model_fit_sec=self._settings.schedule_model_fit_sec,
            self_eval_sec=self._settings.schedule_self_eval_sec,
        )

    def stop(self) -> None:
        """Gracefully stop the scheduler."""
        if self._scheduler.running:
            self._scheduler.shutdown(wait=True)
            logger.info("scheduler_stopped")

    @property
    def is_running(self) -> bool:
        """Whether the scheduler is currently running."""
        return self._scheduler.running

    @property
    def last_run_times(self) -> dict[str, str]:
        """Get last run times for each job."""
        return dict(self._last_run_times)

    def get_job_status(self) -> list[dict[str, Any]]:
        """Get status of all scheduled jobs."""
        jobs: list[dict[str, Any]] = []
        for job in self._scheduler.get_jobs():
            next_run = job.next_run_time
            jobs.append({
                "id": job.id,
                "name": job.name,
                "next_run": next_run.isoformat() if next_run else None,
                "last_run": self._last_run_times.get(job.id),
            })
        return jobs

    async def _run_quality_check(self) -> None:
        """Execute the quality check job with error handling."""
        from datetime import datetime, timezone

        job_id = "quality_check"
        logger.info("job_starting", job_id=job_id)
        try:
            await self._quality_check_fn()
            self._last_run_times[job_id] = datetime.now(timezone.utc).isoformat()
            logger.info("job_completed", job_id=job_id)
        except Exception as exc:
            logger.error("job_failed", job_id=job_id, error=str(exc), exc_info=True)

    async def _run_prompt_optimization(self) -> None:
        """Execute the prompt optimization job with error handling."""
        from datetime import datetime, timezone

        job_id = "prompt_optimization"
        logger.info("job_starting", job_id=job_id)
        try:
            await self._prompt_optimization_fn()
            self._last_run_times[job_id] = datetime.now(timezone.utc).isoformat()
            logger.info("job_completed", job_id=job_id)
        except Exception as exc:
            logger.error("job_failed", job_id=job_id, error=str(exc), exc_info=True)

    async def _run_model_fit(self) -> None:
        """Execute the model fit job with error handling."""
        from datetime import datetime, timezone

        job_id = "model_fit"
        logger.info("job_starting", job_id=job_id)
        try:
            await self._model_fit_fn()
            self._last_run_times[job_id] = datetime.now(timezone.utc).isoformat()
            logger.info("job_completed", job_id=job_id)
        except Exception as exc:
            logger.error("job_failed", job_id=job_id, error=str(exc), exc_info=True)

    async def _run_self_eval(self) -> None:
        """Execute the self-evaluation job with error handling."""
        from datetime import datetime, timezone

        job_id = "self_eval"
        logger.info("job_starting", job_id=job_id)
        try:
            await self._self_eval_fn()
            self._last_run_times[job_id] = datetime.now(timezone.utc).isoformat()
            logger.info("job_completed", job_id=job_id)
        except Exception as exc:
            logger.error("job_failed", job_id=job_id, error=str(exc), exc_info=True)

    def trigger_job(self, job_id: str) -> bool:
        """Manually trigger a job to run immediately.

        Args:
            job_id: The job identifier to trigger.

        Returns:
            True if job was found and triggered.
        """
        job = self._scheduler.get_job(job_id)
        if job is None:
            logger.warning("trigger_job_not_found", job_id=job_id)
            return False

        job.modify(next_run_time=None)
        self._scheduler.modify_job(job_id, next_run_time=None)
        logger.info("job_manually_triggered", job_id=job_id)
        return True

    def reschedule_job(self, job_id: str, interval_seconds: int) -> bool:
        """Reschedule a job with a new interval.

        Used by self-regulation to adjust frequency based on performance.

        Args:
            job_id: The job to reschedule.
            interval_seconds: New interval in seconds.

        Returns:
            True if job was found and rescheduled.
        """
        job = self._scheduler.get_job(job_id)
        if job is None:
            logger.warning("reschedule_job_not_found", job_id=job_id)
            return False

        self._scheduler.reschedule_job(
            job_id,
            trigger=IntervalTrigger(seconds=interval_seconds),
        )
        logger.info(
            "job_rescheduled",
            job_id=job_id,
            new_interval_seconds=interval_seconds,
        )
        return True
