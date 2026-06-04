"""High-level storage client that delegates to the appropriate adapter.

Usage:
    from common.clients import StorageClient

    storage = StorageClient()  # Adapter auto-selected from STORAGE_BACKEND env
    data = await storage.get_json("tenant/evidence/control/metadata.json")
    await storage.put_json("tenant/results/eval.json", {"score": 0.95})

The client enforces tenant path scoping via tenant_prefix() and delegates
all actual I/O to the configured StorageAdapter (S3 or MinIO).
"""

from __future__ import annotations

import os

from common.storage import StorageAdapter, get_adapter


class StorageClient:
    """Unified async storage client with adapter pattern.

    Reads STORAGE_BACKEND from environment to select the adapter at init.
    All methods delegate directly to the adapter. Agents interact only with
    this client, never with boto3 or minio SDK directly.
    """

    def __init__(
        self,
        backend: str | None = None,
        bucket: str | None = None,
        **kwargs: object,
    ) -> None:
        """Initialize the storage client.

        Args:
            backend: Storage backend ("s3" or "minio"). Reads STORAGE_BACKEND env if None.
            bucket: Bucket name. Reads STORAGE_BUCKET env if None.
            **kwargs: Additional adapter-specific config (endpoint, access_key, etc.).
        """
        self._backend = backend or os.environ.get("STORAGE_BACKEND", "s3")
        self._bucket = bucket or os.environ.get("STORAGE_BUCKET", "compliance-artifacts")

        adapter_kwargs: dict[str, object] = {"bucket": self._bucket}

        if self._backend == "s3":
            adapter_kwargs["region"] = kwargs.get(
                "region", os.environ.get("AWS_REGION", "us-east-1")
            )
        elif self._backend == "minio":
            adapter_kwargs["endpoint"] = kwargs.get(
                "endpoint", os.environ.get("STORAGE_ENDPOINT", "minio:9000")
            )
            adapter_kwargs["access_key"] = kwargs.get(
                "access_key", os.environ.get("STORAGE_ACCESS_KEY", "")
            )
            adapter_kwargs["secret_key"] = kwargs.get(
                "secret_key", os.environ.get("STORAGE_SECRET_KEY", "")
            )
            adapter_kwargs["secure"] = kwargs.get(
                "secure", os.environ.get("STORAGE_SECURE", "false").lower() == "true"
            )

        self._adapter: StorageAdapter = get_adapter(self._backend, **adapter_kwargs)

    @staticmethod
    def tenant_prefix(tenant_id: str, key: str) -> str:
        """Build a tenant-scoped key path.

        Ensures all storage access is scoped to the tenant's namespace.

        Args:
            tenant_id: Tenant identifier.
            key: Object key (relative path within tenant scope).

        Returns:
            Full key path prefixed with tenant ID.
        """
        clean_tenant = tenant_id.strip("/")
        clean_key = key.lstrip("/")
        return f"{clean_tenant}/{clean_key}"

    async def get(self, key: str) -> bytes:
        """Retrieve raw bytes for the given key.

        Raises:
            StorageNotFoundError: Key does not exist.
            StorageError: Backend unreachable or unrecoverable error.
        """
        return await self._adapter.get(key)

    async def get_json(self, key: str) -> dict:
        """Retrieve and JSON-decode the object at key.

        Raises:
            StorageNotFoundError: Key does not exist.
            StorageError: Backend unreachable or unrecoverable error.
        """
        return await self._adapter.get_json(key)

    async def put(self, key: str, data: bytes, content_type: str | None = None) -> None:
        """Store raw bytes at the given key.

        Raises:
            StorageError: Backend unreachable or unrecoverable error.
        """
        await self._adapter.put(key, data, content_type=content_type)

    async def put_json(self, key: str, obj: dict) -> None:
        """JSON-encode and store an object at the given key.

        Raises:
            StorageError: Backend unreachable or unrecoverable error.
        """
        await self._adapter.put_json(key, obj)

    async def list_objects(self, prefix: str) -> list[str]:
        """List all object keys matching the given prefix.

        Returns:
            List of matching keys, empty if none found.

        Raises:
            StorageError: Backend unreachable or unrecoverable error.
        """
        return await self._adapter.list_objects(prefix)

    async def exists(self, key: str) -> bool:
        """Check whether an object exists at the given key.

        Raises:
            StorageError: Backend unreachable or unrecoverable error.
        """
        return await self._adapter.exists(key)

    async def delete(self, key: str) -> None:
        """Delete the object at the given key (idempotent).

        Raises:
            StorageError: Backend unreachable or unrecoverable error.
        """
        await self._adapter.delete(key)

    async def presigned_upload_url(self, key: str, expires_sec: int = 3600) -> str:
        """Generate a presigned URL for uploading to the given key.

        Raises:
            StorageError: Backend unreachable or unrecoverable error.
        """
        return await self._adapter.presigned_upload_url(key, expires_sec=expires_sec)

    async def presigned_download_url(self, key: str, expires_sec: int = 3600) -> str:
        """Generate a presigned URL for downloading the given key.

        Raises:
            StorageError: Backend unreachable or unrecoverable error.
        """
        return await self._adapter.presigned_download_url(key, expires_sec=expires_sec)

    async def close(self) -> None:
        """Release any held resources in the underlying adapter."""
        await self._adapter.close()
