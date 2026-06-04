"""Health and readiness check logic for the sandbox service.

/health - liveness probe (service process alive)
/ready  - readiness probe (storage reachable + Docker accessible + runtime image present)
"""

from __future__ import annotations

from dataclasses import dataclass

from src.config import SandboxSettings
from src.execution.docker_backend import DockerBackend
from src.storage import FileDownloader


@dataclass(frozen=True, slots=True)
class ReadinessStatus:
    """Result of readiness checks."""

    ready: bool
    storage_reachable: bool
    docker_available: bool
    runtime_image_available: bool

    @property
    def details(self) -> dict[str, bool]:
        """Return details as a dict for JSON serialization."""
        return {
            "storage_reachable": self.storage_reachable,
            "docker_available": self.docker_available,
            "runtime_image_available": self.runtime_image_available,
        }


class HealthChecker:
    """Performs health and readiness checks for the service."""

    def __init__(self, settings: SandboxSettings) -> None:
        self._settings = settings
        self._backend = DockerBackend(settings)
        self._downloader = FileDownloader(settings)

    async def check_ready(self) -> ReadinessStatus:
        """Perform full readiness check.

        Checks:
        1. Storage endpoint is reachable
        2. Docker engine is accessible
        3. Runtime image is available locally

        Returns:
            ReadinessStatus with individual check results.
        """
        storage_ok = await self._downloader.check_reachable()
        docker_ok = self._backend.is_available()
        image_ok = self._backend.runtime_image_exists() if docker_ok else False

        return ReadinessStatus(
            ready=storage_ok and docker_ok and image_ok,
            storage_reachable=storage_ok,
            docker_available=docker_ok,
            runtime_image_available=image_ok,
        )

    def close(self) -> None:
        """Release resources."""
        self._backend.close()
