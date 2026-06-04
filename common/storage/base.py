"""Abstract base class for storage adapters.

All storage backends (S3, MinIO, future local/GCS) implement this interface.
Agents use StorageAdapter via the common.StorageClient and never interact
with infrastructure directly.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class StorageAdapter(ABC):
    """Async storage adapter interface.

    All methods are async. Implementations that wrap synchronous SDKs
    (boto3, minio) use asyncio.to_thread() for non-blocking I/O.
    """

    @abstractmethod
    async def get(self, key: str) -> bytes:
        """Retrieve raw bytes for the given key.

        Raises:
            StorageNotFoundError: Key does not exist.
            StorageError: Backend unreachable or unrecoverable error.
        """

    @abstractmethod
    async def get_json(self, key: str) -> dict:
        """Retrieve and JSON-decode the object at key.

        Raises:
            StorageNotFoundError: Key does not exist.
            StorageError: Backend unreachable, unrecoverable, or invalid JSON.
        """

    @abstractmethod
    async def put(self, key: str, data: bytes, content_type: str | None = None) -> None:
        """Store raw bytes at the given key.

        Args:
            key: Object key (path) within the bucket.
            data: Raw bytes to store.
            content_type: Optional MIME type. Defaults to application/octet-stream.

        Raises:
            StorageError: Backend unreachable or unrecoverable error.
        """

    @abstractmethod
    async def put_json(self, key: str, obj: dict) -> None:
        """JSON-encode and store an object at the given key.

        Raises:
            StorageError: Backend unreachable or unrecoverable error.
        """

    @abstractmethod
    async def list_objects(self, prefix: str) -> list[str]:
        """List all object keys matching the given prefix.

        Returns an empty list if no objects match (never raises for empty results).

        Raises:
            StorageError: Backend unreachable or unrecoverable error.
        """

    @abstractmethod
    async def exists(self, key: str) -> bool:
        """Check whether an object exists at the given key.

        Returns:
            True if the object exists, False otherwise.

        Raises:
            StorageError: Backend unreachable or unrecoverable error.
        """

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Delete the object at the given key.

        Does not raise if the key does not exist (idempotent delete).

        Raises:
            StorageError: Backend unreachable or unrecoverable error.
        """

    @abstractmethod
    async def presigned_upload_url(self, key: str, expires_sec: int = 3600) -> str:
        """Generate a presigned URL for uploading to the given key.

        Args:
            key: Object key (path) within the bucket.
            expires_sec: URL validity duration in seconds. Defaults to 3600.

        Returns:
            A presigned URL string that allows HTTP PUT upload.

        Raises:
            StorageError: Backend unreachable or unrecoverable error.
        """

    @abstractmethod
    async def presigned_download_url(self, key: str, expires_sec: int = 3600) -> str:
        """Generate a presigned URL for downloading the given key.

        Args:
            key: Object key (path) within the bucket.
            expires_sec: URL validity duration in seconds. Defaults to 3600.

        Returns:
            A presigned URL string that allows HTTP GET download.

        Raises:
            StorageError: Backend unreachable or unrecoverable error.
        """

    async def close(self) -> None:
        """Release any held resources (connections, sessions).

        Default implementation is a no-op. Override if the backend holds
        persistent connections that need cleanup.
        """
