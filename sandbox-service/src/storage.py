"""File download from object storage into the sandbox temp directory.

Downloads evidence files referenced in the execution request from MinIO/S3
into a local temp directory. These files are then bind-mounted read-only
into the runtime container.

The sandbox service process (not the container) has storage credentials.
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx
import structlog

from src.config import SandboxSettings
from src.models import FileReference

logger = structlog.get_logger(__name__)


class StorageDownloadError(Exception):
    """Raised when a file cannot be downloaded from storage."""

    def __init__(self, message: str, storage_key: str = "", status_code: int = 0) -> None:
        self.storage_key = storage_key
        self.status_code = status_code
        super().__init__(message)


class FileDownloader:
    """Downloads files from object storage (MinIO/S3) to a local directory.

    Uses httpx to make HTTP requests against the S3-compatible API.
    Authentication uses access key + secret key for signing.
    """

    def __init__(self, settings: SandboxSettings) -> None:
        self._settings = settings
        self._endpoint = settings.storage_endpoint.rstrip("/")
        self._bucket = settings.storage_bucket
        self._access_key = settings.storage_access_key
        self._secret_key = settings.storage_secret_key
        self._max_total_size = settings.max_total_file_size_mb * 1024 * 1024

    async def download_files(
        self,
        files: list[FileReference],
        target_dir: Path,
    ) -> None:
        """Download all referenced files from storage to the target directory.

        Files are named by their last path component (filename) from the storage_key.
        If a file exceeds the total size limit, a StorageDownloadError is raised.

        Args:
            files: List of file references to download.
            target_dir: Local directory to write files into.

        Raises:
            StorageDownloadError: If any file cannot be retrieved or size limits exceeded.
        """
        target_dir.mkdir(parents=True, exist_ok=True)
        total_bytes = 0

        async with httpx.AsyncClient(timeout=60.0) as client:
            for file_ref in files:
                filename = file_ref.storage_key.rsplit("/", 1)[-1]
                file_path = target_dir / filename
                url = f"{self._endpoint}/{self._bucket}/{file_ref.storage_key}"

                try:
                    response = await client.get(
                        url,
                        auth=(self._access_key, self._secret_key)
                        if self._access_key
                        else None,
                    )
                except httpx.RequestError as exc:
                    raise StorageDownloadError(
                        f"Storage unreachable: {exc}",
                        storage_key=file_ref.storage_key,
                        status_code=502,
                    ) from exc

                if response.status_code == 404:
                    raise StorageDownloadError(
                        f"File not found in storage: {file_ref.storage_key}",
                        storage_key=file_ref.storage_key,
                        status_code=404,
                    )

                if response.status_code != 200:
                    raise StorageDownloadError(
                        f"Storage returned {response.status_code} for {file_ref.storage_key}",
                        storage_key=file_ref.storage_key,
                        status_code=response.status_code,
                    )

                content = response.content
                total_bytes += len(content)

                if total_bytes > self._max_total_size:
                    raise StorageDownloadError(
                        f"Total file size exceeds limit of {self._settings.max_total_file_size_mb}MB",
                        storage_key=file_ref.storage_key,
                        status_code=413,
                    )

                file_path.write_bytes(content)

                logger.debug(
                    "file_downloaded",
                    storage_key=file_ref.storage_key,
                    size_bytes=len(content),
                    target=str(file_path),
                )

    async def check_reachable(self) -> bool:
        """Check if storage endpoint is reachable.

        Returns:
            True if the endpoint responds, False otherwise.
        """
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.head(
                    f"{self._endpoint}/{self._bucket}",
                    auth=(self._access_key, self._secret_key)
                    if self._access_key
                    else None,
                )
                # MinIO returns 200 for bucket head, S3 might return 200 or 403
                return response.status_code in (200, 403, 404)
        except httpx.RequestError:
            return False
