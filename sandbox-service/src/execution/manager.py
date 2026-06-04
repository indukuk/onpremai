"""Execution Manager: orchestrates the full execution lifecycle.

Responsibilities:
1. Concurrency control via asyncio.Semaphore (bounded queue)
2. File download from storage to temp directory
3. Preamble generation and code assembly
4. Security validation (import allowlist)
5. Docker backend invocation
6. Cleanup of temp files
7. Metrics collection
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
import time
import uuid
from pathlib import Path

import structlog

from src.config import SandboxSettings
from src.execution.docker_backend import DockerBackend, DockerExecutionResult
from src.execution.preamble import generate_preamble
from src.models import ExecutionRequest, ExecutionResult
from src.security.import_allowlist import check_code_safety
from src.storage import FileDownloader

logger = structlog.get_logger(__name__)


class ExecutionManager:
    """Manages concurrent code executions with semaphore-based queuing.

    Enforces MAX_CONCURRENT_EXECUTIONS with a bounded queue of QUEUE_SIZE.
    If both slots and queue are full, raises QueueFullError.
    """

    def __init__(self, settings: SandboxSettings) -> None:
        self._settings = settings
        self._semaphore = asyncio.Semaphore(settings.max_concurrent_executions)
        self._backend = DockerBackend(settings)
        self._downloader = FileDownloader(settings)

        # Metrics state
        self._total_executions: int = 0
        self._successful: int = 0
        self._failed: int = 0
        self._timeouts: list[float] = []  # timestamps of timeouts
        self._oom_kills: list[float] = []  # timestamps of OOM kills
        self._durations: list[int] = []  # recent durations in ms
        self._active: int = 0
        self._queued: int = 0
        self._max_duration_history: int = 1000

    @property
    def active_executions(self) -> int:
        """Number of currently running executions."""
        return self._active

    @property
    def queued_requests(self) -> int:
        """Number of requests waiting in queue."""
        return self._queued

    @property
    def total_executions(self) -> int:
        """Total number of executions attempted."""
        return self._total_executions

    @property
    def success_rate(self) -> float:
        """Ratio of successful executions to total."""
        if self._total_executions == 0:
            return 0.0
        return self._successful / self._total_executions

    @property
    def avg_duration_ms(self) -> float:
        """Average execution duration in milliseconds."""
        if not self._durations:
            return 0.0
        return sum(self._durations) / len(self._durations)

    @property
    def timeouts_last_hour(self) -> int:
        """Number of timeouts in the last hour."""
        cutoff = time.time() - 3600
        return sum(1 for t in self._timeouts if t > cutoff)

    @property
    def oom_kills_last_hour(self) -> int:
        """Number of OOM kills in the last hour."""
        cutoff = time.time() - 3600
        return sum(1 for t in self._oom_kills if t > cutoff)

    def is_queue_full(self) -> bool:
        """Check if both execution slots and queue are at capacity."""
        # semaphore._value tells us available slots (0 means all busy)
        # If all slots busy AND queue is at capacity, reject
        return self._queued >= self._settings.queue_size

    async def execute(self, request: ExecutionRequest) -> ExecutionResult:
        """Execute code in an isolated container.

        This is the main entry point. It:
        1. Validates imports
        2. Acquires a semaphore slot (queuing if needed)
        3. Downloads files
        4. Generates preamble + assembles code
        5. Runs in Docker
        6. Collects metrics
        7. Cleans up

        Args:
            request: The validated execution request.

        Returns:
            ExecutionResult with success/failure, stdout, stderr, metrics.

        Raises:
            QueueFullError: If all slots and queue positions are occupied.
            StorageDownloadError: If file download fails.
        """
        # Step 1: Static security check (no container created if blocked)
        violations = check_code_safety(request.code)
        if violations:
            violation_msg = "\n".join(f"ImportError: {v}" for v in violations)
            logger.warning(
                "blocked_imports_detected",
                trace_id=request.trace_id,
                agent=request.agent,
                violations=violations,
            )
            return ExecutionResult(
                success=False,
                stdout="",
                stderr=violation_msg,
                duration_ms=0,
                memory_used_mb=0,
            )

        # Step 2: Check queue capacity
        if self.is_queue_full():
            raise QueueFullError("All execution slots and queue positions are occupied")

        # Step 3: Queue and wait for slot
        self._queued += 1
        try:
            await self._semaphore.acquire()
        finally:
            self._queued -= 1

        self._active += 1
        self._total_executions += 1

        exec_id = uuid.uuid4().hex[:12]
        exec_dir = Path(self._settings.sandbox_tmp_dir) / exec_id
        data_dir = exec_dir / "data"
        code_path = exec_dir / "code.py"

        try:
            # Step 4: Create temp directories
            data_dir.mkdir(parents=True, exist_ok=True)

            # Step 5: Download files from storage
            if request.files:
                await self._downloader.download_files(request.files, data_dir)

            # Step 6: Generate preamble and assemble code
            preamble = generate_preamble(request.files)
            full_code = preamble + request.code
            code_path.write_text(full_code, encoding="utf-8")

            # Step 7: Execute in Docker
            timeout_sec = min(request.timeout_sec, self._settings.max_timeout_sec)
            memory_mb = min(request.memory_limit_mb, self._settings.max_memory_mb)

            docker_result: DockerExecutionResult = await self._backend.execute(
                code_path=code_path,
                data_dir=data_dir,
                timeout_sec=timeout_sec,
                memory_limit_mb=memory_mb,
            )

            # Step 8: Build response
            success = docker_result.exit_code == 0 and not docker_result.timed_out and not docker_result.oom_killed

            result = ExecutionResult(
                success=success,
                stdout=docker_result.stdout,
                stderr=docker_result.stderr,
                duration_ms=docker_result.duration_ms,
                memory_used_mb=memory_mb if docker_result.oom_killed else 0,
            )

            # Step 9: Update metrics
            if success:
                self._successful += 1
            else:
                self._failed += 1

            if docker_result.timed_out:
                self._timeouts.append(time.time())

            if docker_result.oom_killed:
                self._oom_kills.append(time.time())

            self._durations.append(docker_result.duration_ms)
            if len(self._durations) > self._max_duration_history:
                self._durations = self._durations[-self._max_duration_history:]

            # Prune old timestamps
            cutoff = time.time() - 7200  # keep 2 hours
            self._timeouts = [t for t in self._timeouts if t > cutoff]
            self._oom_kills = [t for t in self._oom_kills if t > cutoff]

            logger.info(
                "execution_completed",
                trace_id=request.trace_id,
                agent=request.agent,
                exec_id=exec_id,
                success=success,
                duration_ms=docker_result.duration_ms,
                timed_out=docker_result.timed_out,
                oom_killed=docker_result.oom_killed,
                file_count=len(request.files),
            )

            return result

        except QueueFullError:
            raise
        except Exception as exc:
            self._failed += 1
            logger.error(
                "execution_error",
                trace_id=request.trace_id,
                agent=request.agent,
                exec_id=exec_id,
                error=str(exc),
            )
            raise

        finally:
            # Step 10: Cleanup
            self._active -= 1
            self._semaphore.release()
            if exec_dir.exists():
                shutil.rmtree(exec_dir, ignore_errors=True)

    def is_backend_available(self) -> bool:
        """Check if the Docker backend is reachable."""
        return self._backend.is_available()

    def is_runtime_image_available(self) -> bool:
        """Check if the runtime image exists locally."""
        return self._backend.runtime_image_exists()

    def close(self) -> None:
        """Shutdown backend connections."""
        self._backend.close()


class QueueFullError(Exception):
    """Raised when all execution slots and queue positions are occupied."""

    pass
