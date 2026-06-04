"""Background job manager for async evaluation execution.

Manages asyncio tasks for evaluation jobs, tracks their status, and
provides clean shutdown semantics. Jobs are tracked both in-memory (for
the running process) and via StateClient (for persistence across restarts).
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine

import structlog

from common.clients import StateClient

from src.models import EvalResult, JobStatus, JobStatusEnum

logger = structlog.get_logger(__name__)


class JobManager:
    """Manages background evaluation jobs as asyncio tasks.

    Provides start/poll/cancel semantics with persistent state tracking.
    On graceful shutdown, waits for in-progress evaluations to complete.
    """

    def __init__(self, state_client: StateClient, max_concurrent: int = 10) -> None:
        self._state_client = state_client
        self._max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._active_tasks: dict[str, asyncio.Task[None]] = {}
        self._results: dict[str, EvalResult | None] = {}
        self._errors: dict[str, str] = {}

    async def start_job(
        self,
        coro_factory: Callable[[str], Coroutine[Any, Any, EvalResult]],
        tenant_id: str,
        control_id: str,
        framework: str,
    ) -> str:
        """Start a new evaluation job in the background.

        Args:
            coro_factory: Async function that takes job_id and returns EvalResult.
            tenant_id: Tenant identifier.
            control_id: Control being evaluated.
            framework: Compliance framework.

        Returns:
            The generated job_id.
        """
        job_id = str(uuid.uuid4())

        await self._state_client.set_job_status(
            job_id,
            JobStatusEnum.PROCESSING.value,
            data={
                "tenant_id": tenant_id,
                "control_id": control_id,
                "framework": framework,
                "started_at": datetime.now(timezone.utc).isoformat(),
            },
        )

        task = asyncio.create_task(self._run_job(job_id, coro_factory))
        self._active_tasks[job_id] = task

        logger.info(
            "job_started",
            job_id=job_id,
            tenant_id=tenant_id,
            control_id=control_id,
            framework=framework,
        )

        return job_id

    async def _run_job(
        self,
        job_id: str,
        coro_factory: Callable[[str], Coroutine[Any, Any, EvalResult]],
    ) -> None:
        """Execute a job within the semaphore, updating state on completion/failure."""
        async with self._semaphore:
            try:
                result = await coro_factory(job_id)
                self._results[job_id] = result

                await self._state_client.set_job_status(
                    job_id,
                    JobStatusEnum.COMPLETED.value,
                    data={"completed_at": datetime.now(timezone.utc).isoformat()},
                )
                await self._state_client.set_job_result(
                    job_id,
                    result.model_dump(mode="json"),
                )

                logger.info("job_completed", job_id=job_id)

            except Exception as exc:
                error_msg = f"{type(exc).__name__}: {exc}"
                self._errors[job_id] = error_msg

                await self._state_client.set_job_status(
                    job_id,
                    JobStatusEnum.FAILED.value,
                    data={
                        "error": error_msg,
                        "failed_at": datetime.now(timezone.utc).isoformat(),
                    },
                )

                logger.error(
                    "job_failed",
                    job_id=job_id,
                    error=error_msg,
                    exc_info=True,
                )

            finally:
                self._active_tasks.pop(job_id, None)

    async def get_status(self, job_id: str) -> JobStatus:
        """Get the current status of a job.

        Checks in-memory state first, then falls back to persistent state.
        """
        # Check in-memory result
        if job_id in self._results:
            return JobStatus(
                job_id=job_id,
                status=JobStatusEnum.COMPLETED,
                evaluation=self._results[job_id],
                completed_at=datetime.now(timezone.utc),
            )

        if job_id in self._errors:
            return JobStatus(
                job_id=job_id,
                status=JobStatusEnum.FAILED,
                error=self._errors[job_id],
            )

        if job_id in self._active_tasks:
            return JobStatus(
                job_id=job_id,
                status=JobStatusEnum.PROCESSING,
            )

        # Fall back to persistent state
        state_data = await self._state_client.get_job_status(job_id)
        if state_data is None:
            return JobStatus(
                job_id=job_id,
                status=JobStatusEnum.FAILED,
                error="Job not found",
            )

        status_str = state_data.get("status", "failed")
        try:
            status_enum = JobStatusEnum(status_str)
        except ValueError:
            status_enum = JobStatusEnum.FAILED

        result: EvalResult | None = None
        if status_enum == JobStatusEnum.COMPLETED:
            result_data = await self._state_client.get_job_result(job_id)
            if result_data is not None:
                result = EvalResult.model_validate(result_data)

        return JobStatus(
            job_id=job_id,
            status=status_enum,
            evaluation=result,
            error=state_data.get("data", {}).get("error") if isinstance(state_data.get("data"), dict) else None,
        )

    async def shutdown(self, timeout: float = 30.0) -> None:
        """Gracefully shut down: wait for active tasks to complete.

        Args:
            timeout: Maximum seconds to wait for tasks to finish.
        """
        if not self._active_tasks:
            return

        logger.info(
            "shutdown_waiting",
            active_tasks=len(self._active_tasks),
            timeout=timeout,
        )

        tasks = list(self._active_tasks.values())
        done, pending = await asyncio.wait(tasks, timeout=timeout)

        if pending:
            logger.warning(
                "shutdown_cancelling_tasks",
                pending_count=len(pending),
            )
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)

    @property
    def active_count(self) -> int:
        """Number of currently running evaluation jobs."""
        return len(self._active_tasks)
