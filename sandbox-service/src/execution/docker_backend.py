"""Docker execution backend using the Docker SDK (docker-py).

Creates ephemeral containers from the runtime image with:
- No network access (network_mode="none")
- Read-only filesystem
- Memory and CPU limits
- Timeout enforcement via container kill

Each execution gets its own container that is removed after completion.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import docker
import docker.errors
from docker.models.containers import Container

from src.config import SandboxSettings


@dataclass(frozen=True, slots=True)
class DockerExecutionResult:
    """Raw result from Docker container execution."""

    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    oom_killed: bool
    timed_out: bool


class DockerBackend:
    """Manages ephemeral Docker container lifecycle for code execution.

    The backend creates containers with --network=none, resource limits,
    and read-only mounts for code and data. Containers are always removed
    after execution regardless of outcome.
    """

    def __init__(self, settings: SandboxSettings) -> None:
        self._settings = settings
        self._client: docker.DockerClient | None = None

    @property
    def client(self) -> docker.DockerClient:
        """Lazy-initialize Docker client."""
        if self._client is None:
            self._client = docker.DockerClient(
                base_url=f"unix://{self._settings.docker_socket}",
                timeout=30,
            )
        return self._client

    def is_available(self) -> bool:
        """Check if Docker engine is reachable and runtime image exists."""
        try:
            self.client.ping()
            return True
        except (docker.errors.DockerException, Exception):
            return False

    def runtime_image_exists(self) -> bool:
        """Check if the runtime image is available locally."""
        try:
            self.client.images.get(self._settings.runtime_image)
            return True
        except docker.errors.ImageNotFound:
            return False
        except docker.errors.DockerException:
            return False

    async def execute(
        self,
        code_path: Path,
        data_dir: Path,
        timeout_sec: int,
        memory_limit_mb: int,
        cpus: float | None = None,
    ) -> DockerExecutionResult:
        """Run code in an ephemeral Docker container.

        Args:
            code_path: Absolute path to the Python script to execute.
            data_dir: Absolute path to the data directory (mounted read-only).
            timeout_sec: Maximum execution time before SIGKILL.
            memory_limit_mb: Memory limit in megabytes.
            cpus: CPU limit (number of cores). Defaults to settings default.

        Returns:
            DockerExecutionResult with stdout, stderr, exit code, and metrics.
        """
        effective_cpus = cpus if cpus is not None else self._settings.default_cpus
        memory_bytes = memory_limit_mb * 1024 * 1024
        max_output_bytes = self._settings.max_output_size_mb * 1024 * 1024

        container: Container | None = None
        start_time = time.monotonic()

        try:
            container = self.client.containers.create(
                image=self._settings.runtime_image,
                command=["python", "/tmp/code.py"],
                volumes={
                    str(code_path): {"bind": "/tmp/code.py", "mode": "ro"},
                    str(data_dir): {"bind": "/tmp/data", "mode": "ro"},
                },
                network_mode="none",
                mem_limit=memory_bytes,
                memswap_limit=memory_bytes,  # no swap
                nano_cpus=int(effective_cpus * 1e9),
                read_only=True,
                tmpfs={"/tmp/work": "size=50m,noexec"},
                user="65534",
                security_opt=["no-new-privileges"],
                environment={},  # clean env, no host vars
                detach=True,
                auto_remove=False,
            )

            container.start()

            # Wait for container to finish or timeout
            try:
                exit_info = container.wait(timeout=timeout_sec)
                exit_code = exit_info.get("StatusCode", 1)
                timed_out = False
            except Exception:
                # Timeout or connection error -- kill the container
                try:
                    container.kill()
                except docker.errors.APIError:
                    pass
                exit_code = 137
                timed_out = True

            duration_ms = int((time.monotonic() - start_time) * 1000)

            # Check OOM status
            oom_killed = False
            try:
                container.reload()
                state = container.attrs.get("State", {})
                oom_killed = state.get("OOMKilled", False)
                if not timed_out and exit_code == 137:
                    oom_killed = True
            except docker.errors.DockerException:
                pass

            # Capture logs
            stdout_raw = ""
            stderr_raw = ""
            try:
                stdout_bytes = container.logs(stdout=True, stderr=False)
                stderr_bytes = container.logs(stdout=False, stderr=True)
                stdout_raw = stdout_bytes.decode("utf-8", errors="replace")[:max_output_bytes]
                stderr_raw = stderr_bytes.decode("utf-8", errors="replace")[:max_output_bytes]
            except docker.errors.DockerException:
                pass

            # Add contextual error messages
            if timed_out:
                stderr_raw = f"Execution timed out after {timeout_sec} seconds"
            elif oom_killed:
                stderr_raw = (
                    f"Out of memory - killed (limit: {memory_limit_mb}MB)"
                    if not stderr_raw
                    else stderr_raw
                )

            return DockerExecutionResult(
                exit_code=exit_code,
                stdout=stdout_raw,
                stderr=stderr_raw,
                duration_ms=duration_ms,
                oom_killed=oom_killed,
                timed_out=timed_out,
            )

        finally:
            # Always remove container
            if container is not None:
                try:
                    container.remove(force=True)
                except docker.errors.DockerException:
                    pass

    def close(self) -> None:
        """Close the Docker client connection."""
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None
