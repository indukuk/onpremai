"""Shared fixtures for sandbox-service tests.

Provides mock Docker client, mock storage downloader, and settings.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Insert project root into path for imports
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "sandbox-service"))

from src.config import SandboxSettings
from src.execution.docker_backend import DockerBackend, DockerExecutionResult
from src.execution.manager import ExecutionManager
from src.models import ExecutionRequest, FileReference, FileType
from src.storage import FileDownloader


@pytest.fixture
def sandbox_settings() -> SandboxSettings:
    """Return sandbox settings with small limits for fast testing."""
    return SandboxSettings(
        max_concurrent_executions=2,
        queue_size=3,
        max_timeout_sec=60,
        max_memory_mb=512,
        sandbox_tmp_dir="/tmp/sandbox_test",
        docker_socket="/var/run/docker.sock",
        runtime_image="test/runtime:latest",
        storage_endpoint="http://localhost:9000",
        storage_bucket="test-bucket",
        storage_access_key="minioadmin",
        storage_secret_key="minioadmin",
    )


@pytest.fixture
def mock_docker_result_success() -> DockerExecutionResult:
    """A successful Docker execution result."""
    return DockerExecutionResult(
        exit_code=0,
        stdout="result: 42\n",
        stderr="",
        duration_ms=1500,
        oom_killed=False,
        timed_out=False,
    )


@pytest.fixture
def mock_docker_result_timeout() -> DockerExecutionResult:
    """A timed-out Docker execution result."""
    return DockerExecutionResult(
        exit_code=137,
        stdout="",
        stderr="Execution timed out after 60 seconds",
        duration_ms=60000,
        oom_killed=False,
        timed_out=True,
    )


@pytest.fixture
def mock_docker_result_oom() -> DockerExecutionResult:
    """An OOM-killed Docker execution result."""
    return DockerExecutionResult(
        exit_code=137,
        stdout="",
        stderr="Out of memory - killed (limit: 512MB)",
        duration_ms=3200,
        oom_killed=True,
        timed_out=False,
    )


@pytest.fixture
def sample_execution_request() -> ExecutionRequest:
    """A valid execution request with one CSV file."""
    return ExecutionRequest(
        code="print(df.shape)",
        files=[
            FileReference(
                storage_key="tenant1/evidence/data.csv",
                load_as="df",
                type=FileType.csv,
            )
        ],
        timeout_sec=30,
        memory_limit_mb=256,
        agent="agent-eval",
        trace_id="trace-abc123",
    )


@pytest.fixture
def sample_execution_request_no_files() -> ExecutionRequest:
    """A valid execution request with no files."""
    return ExecutionRequest(
        code="print(1 + 1)",
        files=[],
        timeout_sec=10,
        memory_limit_mb=128,
        agent="test-agent",
        trace_id="trace-xyz",
    )


@pytest.fixture
def mock_docker_backend(mock_docker_result_success):
    """A mocked DockerBackend that returns success by default."""
    backend = MagicMock(spec=DockerBackend)
    backend.execute = AsyncMock(return_value=mock_docker_result_success)
    backend.is_available.return_value = True
    backend.runtime_image_exists.return_value = True
    backend.close.return_value = None
    return backend


@pytest.fixture
def mock_file_downloader():
    """A mocked FileDownloader that does nothing."""
    downloader = MagicMock(spec=FileDownloader)
    downloader.download_files = AsyncMock(return_value=None)
    return downloader


@pytest.fixture
def execution_manager(sandbox_settings, mock_docker_backend, mock_file_downloader):
    """ExecutionManager with mocked backend and downloader."""
    manager = ExecutionManager(sandbox_settings)
    manager._backend = mock_docker_backend
    manager._downloader = mock_file_downloader
    return manager
