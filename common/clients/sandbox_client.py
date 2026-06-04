"""Sandbox service client for isolated code execution.

Usage:
    from common.clients import SandboxClient, ExecutionResult

    sandbox = SandboxClient()
    result = await sandbox.execute(
        code="print('hello world')",
        timeout_sec=30,
    )
    if result.success:
        print(result.stdout)

On connection failure, returns ExecutionResult(success=False) -- agents
handle sandbox unavailability gracefully without crashing.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

import httpx
import structlog

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class ExecutionResult:
    """Result from sandbox code execution.

    Attributes:
        success: Whether execution completed without error.
        stdout: Standard output captured during execution.
        stderr: Standard error captured during execution.
        duration_ms: Execution time in milliseconds.
        memory_used_mb: Peak memory usage in megabytes.
        files: Output files produced by the execution.
    """

    success: bool
    stdout: str = ""
    stderr: str = ""
    duration_ms: int = 0
    memory_used_mb: int = 0
    files: dict[str, str] = field(default_factory=dict)


class SandboxClient:
    """Async client for the Sandbox Service.

    Provides isolated code execution in ephemeral containers. On any
    connection failure, returns a failed ExecutionResult rather than raising,
    allowing agents to degrade gracefully.
    """

    def __init__(
        self,
        sandbox_url: str | None = None,
        timeout: float = 60.0,
    ) -> None:
        self._sandbox_url = (
            sandbox_url or os.environ.get("SANDBOX_URL", "http://sandbox-service:6000")
        ).rstrip("/")
        self._timeout = timeout
        self._http = httpx.AsyncClient(
            base_url=self._sandbox_url,
            timeout=httpx.Timeout(timeout, connect=5.0),
            headers={"Content-Type": "application/json"},
        )

    async def execute(
        self,
        code: str,
        files: dict[str, str] | None = None,
        timeout_sec: int = 60,
        memory_limit_mb: int = 512,
        trace_id: str | None = None,
    ) -> ExecutionResult:
        """Execute code in an isolated sandbox container.

        Args:
            code: Python source code to execute.
            files: Optional dict of filename -> content to make available.
            timeout_sec: Maximum execution time in seconds.
            memory_limit_mb: Memory limit for the container.
            trace_id: Distributed trace identifier.

        Returns:
            ExecutionResult with captured output and metadata.
            Returns ExecutionResult(success=False) on connection failure.
        """
        payload: dict = {
            "code": code,
            "timeout_sec": timeout_sec,
            "memory_limit_mb": memory_limit_mb,
        }
        if files is not None:
            payload["files"] = files

        headers: dict[str, str] = {}
        if trace_id is not None:
            headers["X-Trace-Id"] = trace_id

        try:
            response = await self._http.post(
                "/execute",
                json=payload,
                headers=headers,
            )
        except httpx.TimeoutException:
            logger.warning(
                "sandbox_timeout",
                timeout_sec=timeout_sec,
                trace_id=trace_id,
            )
            return ExecutionResult(
                success=False,
                stderr=f"Sandbox execution timed out after {timeout_sec}s",
                duration_ms=timeout_sec * 1000,
            )
        except (httpx.ConnectError, httpx.NetworkError) as exc:
            logger.warning(
                "sandbox_unavailable",
                url=self._sandbox_url,
                error=str(exc),
            )
            return ExecutionResult(
                success=False,
                stderr="Sandbox unavailable",
            )

        if response.status_code >= 500:
            logger.warning(
                "sandbox_server_error",
                status=response.status_code,
                trace_id=trace_id,
            )
            return ExecutionResult(
                success=False,
                stderr=f"Sandbox returned HTTP {response.status_code}",
            )

        try:
            data = response.json()
        except Exception:
            return ExecutionResult(
                success=False,
                stderr="Sandbox returned invalid JSON response",
            )

        return ExecutionResult(
            success=data.get("success", False),
            stdout=data.get("stdout", ""),
            stderr=data.get("stderr", ""),
            duration_ms=data.get("duration_ms", 0),
            memory_used_mb=data.get("memory_used_mb", 0),
            files=data.get("files", {}),
        )

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._http.aclose()
