"""Tests for sandbox-service ExecutionManager.

Covers:
- Successful execution flow
- Blocked imports short-circuit (no container created)
- Concurrency semaphore enforcement
- Queue full returns 429 equivalent (QueueFullError)
- Timeout handling (metrics tracking)
- OOM handling (metrics tracking)
- Metrics properties (success_rate, avg_duration, etc.)
- Cleanup always runs
- Error propagation from backend
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "sandbox-service"))

from src.execution.docker_backend import DockerExecutionResult
from src.execution.manager import ExecutionManager, QueueFullError
from src.models import ExecutionRequest, ExecutionResult, FileReference, FileType


class TestSuccessfulExecution:
    """Happy path: code executes successfully."""

    async def test_success_returns_result(
        self, execution_manager, sample_execution_request, mock_docker_result_success
    ):
        with patch("src.execution.manager.Path.mkdir"), patch(
            "src.execution.manager.Path.write_text"
        ), patch("src.execution.manager.Path.exists", return_value=True), patch(
            "src.execution.manager.shutil.rmtree"
        ):
            result = await execution_manager.execute(sample_execution_request)

        assert result.success is True
        assert result.stdout == "result: 42\n"
        assert result.stderr == ""
        assert result.duration_ms == 1500

    async def test_success_increments_metrics(
        self, execution_manager, sample_execution_request
    ):
        with patch("src.execution.manager.Path.mkdir"), patch(
            "src.execution.manager.Path.write_text"
        ), patch("src.execution.manager.Path.exists", return_value=True), patch(
            "src.execution.manager.shutil.rmtree"
        ):
            await execution_manager.execute(sample_execution_request)

        assert execution_manager.total_executions == 1
        assert execution_manager.success_rate == 1.0
        assert execution_manager.avg_duration_ms == 1500.0

    async def test_no_files_skips_download(
        self, execution_manager, sample_execution_request_no_files, mock_file_downloader
    ):
        with patch("src.execution.manager.Path.mkdir"), patch(
            "src.execution.manager.Path.write_text"
        ), patch("src.execution.manager.Path.exists", return_value=True), patch(
            "src.execution.manager.shutil.rmtree"
        ):
            await execution_manager.execute(sample_execution_request_no_files)

        # download_files should not have been called
        execution_manager._downloader.download_files.assert_not_called()

    async def test_files_triggers_download(
        self, execution_manager, sample_execution_request, mock_file_downloader
    ):
        with patch("src.execution.manager.Path.mkdir"), patch(
            "src.execution.manager.Path.write_text"
        ), patch("src.execution.manager.Path.exists", return_value=True), patch(
            "src.execution.manager.shutil.rmtree"
        ):
            await execution_manager.execute(sample_execution_request)

        execution_manager._downloader.download_files.assert_called_once()


class TestBlockedImportsShortCircuit:
    """Blocked imports return failure immediately without container creation."""

    async def test_blocked_import_returns_failure(self, execution_manager):
        request = ExecutionRequest(
            code="import os\nprint(os.listdir('/'))",
            files=[],
            timeout_sec=10,
            memory_limit_mb=128,
            agent="test",
            trace_id="trace-block",
        )

        result = await execution_manager.execute(request)

        assert result.success is False
        assert "ImportError" in result.stderr
        assert result.duration_ms == 0

    async def test_blocked_import_no_docker_call(self, execution_manager):
        request = ExecutionRequest(
            code="import subprocess",
            files=[],
            timeout_sec=10,
            memory_limit_mb=128,
            agent="test",
            trace_id="trace-block2",
        )

        await execution_manager.execute(request)

        # Docker backend should never be called
        execution_manager._backend.execute.assert_not_called()

    async def test_blocked_import_does_not_count_as_execution(self, execution_manager):
        request = ExecutionRequest(
            code="import socket",
            files=[],
            timeout_sec=10,
            memory_limit_mb=128,
            agent="test",
            trace_id="trace-block3",
        )

        await execution_manager.execute(request)

        # Blocked imports don't go through the semaphore path
        assert execution_manager.total_executions == 0


class TestQueueFull:
    """When all slots and queue are full, QueueFullError is raised."""

    async def test_queue_full_raises_error(self, sandbox_settings):
        """When queued count >= queue_size, QueueFullError is raised."""
        manager = ExecutionManager(sandbox_settings)
        # Manually set queue to capacity
        manager._queued = sandbox_settings.queue_size

        request = ExecutionRequest(
            code="print(1)",
            files=[],
            timeout_sec=10,
            memory_limit_mb=128,
            agent="test",
            trace_id="trace-full",
        )

        with pytest.raises(QueueFullError):
            await manager.execute(request)

    async def test_is_queue_full_property(self, sandbox_settings):
        manager = ExecutionManager(sandbox_settings)
        assert manager.is_queue_full() is False

        manager._queued = sandbox_settings.queue_size
        assert manager.is_queue_full() is True

    async def test_queue_full_with_concurrent_executions(self, sandbox_settings):
        """Simulate scenario where semaphore is exhausted and queue is full."""
        manager = ExecutionManager(sandbox_settings)
        manager._queued = sandbox_settings.queue_size

        request = ExecutionRequest(
            code="print('test')",
            files=[],
            timeout_sec=10,
            memory_limit_mb=128,
            agent="test",
            trace_id="trace-concurrent",
        )

        with pytest.raises(QueueFullError, match="All execution slots"):
            await manager.execute(request)


class TestConcurrencySemaphore:
    """Semaphore limits concurrent executions."""

    async def test_semaphore_allows_concurrent_up_to_limit(self, sandbox_settings):
        """Two concurrent executions are allowed (max_concurrent=2)."""
        manager = ExecutionManager(sandbox_settings)
        backend = MagicMock()

        # Make execute take some time so we can verify concurrency
        async def slow_execute(**kwargs):
            await asyncio.sleep(0.1)
            return DockerExecutionResult(
                exit_code=0, stdout="ok", stderr="", duration_ms=100,
                oom_killed=False, timed_out=False,
            )

        backend.execute = slow_execute
        backend.is_available.return_value = True
        backend.close.return_value = None
        manager._backend = backend
        manager._downloader = MagicMock()
        manager._downloader.download_files = AsyncMock()

        request = ExecutionRequest(
            code="print(1)",
            files=[],
            timeout_sec=10,
            memory_limit_mb=128,
            agent="test",
            trace_id="trace-sem",
        )

        with patch("src.execution.manager.Path.mkdir"), patch(
            "src.execution.manager.Path.write_text"
        ), patch("src.execution.manager.Path.exists", return_value=True), patch(
            "src.execution.manager.shutil.rmtree"
        ):
            results = await asyncio.gather(
                manager.execute(request),
                manager.execute(request),
            )

        assert len(results) == 2
        assert all(r.success for r in results)

    async def test_active_count_reflects_running(self, execution_manager):
        """Active count starts at 0."""
        assert execution_manager.active_executions == 0


class TestTimeoutHandling:
    """Timeout results are tracked in metrics."""

    async def test_timeout_tracked_in_metrics(
        self, execution_manager, mock_docker_result_timeout
    ):
        execution_manager._backend.execute = AsyncMock(
            return_value=mock_docker_result_timeout
        )

        request = ExecutionRequest(
            code="import time; time.sleep(999)",
            files=[],
            timeout_sec=60,
            memory_limit_mb=128,
            agent="test",
            trace_id="trace-timeout",
        )

        with patch("src.execution.manager.Path.mkdir"), patch(
            "src.execution.manager.Path.write_text"
        ), patch("src.execution.manager.Path.exists", return_value=True), patch(
            "src.execution.manager.shutil.rmtree"
        ), patch(
            "src.execution.manager.check_code_safety", return_value=[]
        ):
            result = await execution_manager.execute(request)

        assert result.success is False
        assert execution_manager.timeouts_last_hour >= 1

    async def test_timeout_result_has_correct_fields(
        self, execution_manager, mock_docker_result_timeout
    ):
        execution_manager._backend.execute = AsyncMock(
            return_value=mock_docker_result_timeout
        )

        request = ExecutionRequest(
            code="x = 1",
            files=[],
            timeout_sec=60,
            memory_limit_mb=128,
            agent="test",
            trace_id="trace-timeout2",
        )

        with patch("src.execution.manager.Path.mkdir"), patch(
            "src.execution.manager.Path.write_text"
        ), patch("src.execution.manager.Path.exists", return_value=True), patch(
            "src.execution.manager.shutil.rmtree"
        ):
            result = await execution_manager.execute(request)

        assert result.success is False
        assert result.duration_ms == 60000


class TestOOMHandling:
    """OOM kills are tracked in metrics."""

    async def test_oom_tracked_in_metrics(
        self, execution_manager, mock_docker_result_oom
    ):
        execution_manager._backend.execute = AsyncMock(
            return_value=mock_docker_result_oom
        )

        request = ExecutionRequest(
            code="x = [0] * (10**9)",
            files=[],
            timeout_sec=30,
            memory_limit_mb=512,
            agent="test",
            trace_id="trace-oom",
        )

        with patch("src.execution.manager.Path.mkdir"), patch(
            "src.execution.manager.Path.write_text"
        ), patch("src.execution.manager.Path.exists", return_value=True), patch(
            "src.execution.manager.shutil.rmtree"
        ), patch(
            "src.execution.manager.check_code_safety", return_value=[]
        ):
            result = await execution_manager.execute(request)

        assert result.success is False
        assert execution_manager.oom_kills_last_hour >= 1

    async def test_oom_reports_memory_used(
        self, execution_manager, mock_docker_result_oom
    ):
        execution_manager._backend.execute = AsyncMock(
            return_value=mock_docker_result_oom
        )

        request = ExecutionRequest(
            code="x = 1",
            files=[],
            timeout_sec=30,
            memory_limit_mb=512,
            agent="test",
            trace_id="trace-oom2",
        )

        with patch("src.execution.manager.Path.mkdir"), patch(
            "src.execution.manager.Path.write_text"
        ), patch("src.execution.manager.Path.exists", return_value=True), patch(
            "src.execution.manager.shutil.rmtree"
        ), patch(
            "src.execution.manager.check_code_safety", return_value=[]
        ):
            result = await execution_manager.execute(request)

        # OOM killed reports the memory limit as memory_used_mb
        assert result.memory_used_mb == 512


class TestMetricsProperties:
    """Metrics properties compute correctly."""

    def test_initial_metrics(self, execution_manager):
        assert execution_manager.total_executions == 0
        assert execution_manager.success_rate == 0.0
        assert execution_manager.avg_duration_ms == 0.0
        assert execution_manager.active_executions == 0
        assert execution_manager.queued_requests == 0
        assert execution_manager.timeouts_last_hour == 0
        assert execution_manager.oom_kills_last_hour == 0

    def test_success_rate_calculation(self, execution_manager):
        execution_manager._total_executions = 10
        execution_manager._successful = 8
        execution_manager._failed = 2
        assert execution_manager.success_rate == 0.8

    def test_avg_duration_calculation(self, execution_manager):
        execution_manager._durations = [100, 200, 300]
        assert execution_manager.avg_duration_ms == 200.0


class TestCleanup:
    """Cleanup always runs after execution."""

    async def test_cleanup_on_success(self, execution_manager, sample_execution_request):
        with patch("src.execution.manager.Path.mkdir"), patch(
            "src.execution.manager.Path.write_text"
        ), patch("src.execution.manager.Path.exists", return_value=True) as mock_exists, patch(
            "src.execution.manager.shutil.rmtree"
        ) as mock_rmtree:
            await execution_manager.execute(sample_execution_request)

        mock_rmtree.assert_called_once()

    async def test_cleanup_on_backend_error(self, execution_manager):
        execution_manager._backend.execute = AsyncMock(
            side_effect=RuntimeError("Docker exploded")
        )

        request = ExecutionRequest(
            code="print(1)",
            files=[],
            timeout_sec=10,
            memory_limit_mb=128,
            agent="test",
            trace_id="trace-err",
        )

        with patch("src.execution.manager.Path.mkdir"), patch(
            "src.execution.manager.Path.write_text"
        ), patch("src.execution.manager.Path.exists", return_value=True), patch(
            "src.execution.manager.shutil.rmtree"
        ) as mock_rmtree:
            with pytest.raises(RuntimeError, match="Docker exploded"):
                await execution_manager.execute(request)

        mock_rmtree.assert_called_once()

    async def test_semaphore_released_on_error(self, execution_manager):
        """Semaphore is always released even if execution fails."""
        execution_manager._backend.execute = AsyncMock(
            side_effect=RuntimeError("Kaboom")
        )

        request = ExecutionRequest(
            code="print(1)",
            files=[],
            timeout_sec=10,
            memory_limit_mb=128,
            agent="test",
            trace_id="trace-release",
        )

        with patch("src.execution.manager.Path.mkdir"), patch(
            "src.execution.manager.Path.write_text"
        ), patch("src.execution.manager.Path.exists", return_value=True), patch(
            "src.execution.manager.shutil.rmtree"
        ):
            with pytest.raises(RuntimeError):
                await execution_manager.execute(request)

        # Active count should be back to 0
        assert execution_manager.active_executions == 0


class TestBackendAvailability:
    """Backend availability checks."""

    def test_is_backend_available(self, execution_manager):
        assert execution_manager.is_backend_available() is True

    def test_is_runtime_image_available(self, execution_manager):
        assert execution_manager.is_runtime_image_available() is True

    def test_backend_unavailable(self, execution_manager):
        execution_manager._backend.is_available.return_value = False
        assert execution_manager.is_backend_available() is False
