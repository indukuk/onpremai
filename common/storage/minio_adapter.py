"""MinIO storage adapter.

Wraps the minio Python SDK. All synchronous SDK calls are dispatched
via asyncio.to_thread() for async compatibility.
"""

from __future__ import annotations

import asyncio
import io
import json
from datetime import timedelta
from typing import Any

from minio import Minio
from minio.error import S3Error

from common.errors import StorageError, StorageNotFoundError
from common.storage.base import StorageAdapter


class MinIOAdapter(StorageAdapter):
    """MinIO/S3-compatible storage backend.

    Args:
        endpoint: MinIO server endpoint (host:port).
        access_key: Access key for authentication.
        secret_key: Secret key for authentication.
        bucket: Bucket name.
        secure: Whether to use HTTPS. Defaults to False for local dev.
    """

    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        secure: bool = False,
    ) -> None:
        self._bucket = bucket
        self._endpoint = endpoint
        self._client: Any = Minio(
            endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
        )

    def _is_not_found(self, error: S3Error) -> bool:
        """Check if an S3Error represents a missing key."""
        return error.code in ("NoSuchKey", "NoSuchBucket")

    async def get(self, key: str) -> bytes:
        """Retrieve raw bytes from MinIO."""
        response = None
        try:
            response = await asyncio.to_thread(
                self._client.get_object,
                self._bucket,
                key,
            )
            data: bytes = await asyncio.to_thread(response.read)
            return data
        except S3Error as exc:
            if self._is_not_found(exc):
                raise StorageNotFoundError(
                    f"Key not found: {key}", bucket=self._bucket, key=key
                ) from exc
            raise StorageError(
                f"MinIO get failed: {exc}", bucket=self._bucket, key=key
            ) from exc
        except StorageNotFoundError:
            raise
        except StorageError:
            raise
        except Exception as exc:
            raise StorageError(
                f"MinIO get failed: {exc}", bucket=self._bucket, key=key
            ) from exc
        finally:
            if response is not None:
                response.close()
                response.release_conn()

    async def get_json(self, key: str) -> dict:
        """Retrieve and JSON-decode an object from MinIO."""
        raw = await self.get(key)
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise StorageError(
                f"Invalid JSON at key: {key}", bucket=self._bucket, key=key
            ) from exc

    async def put(self, key: str, data: bytes, content_type: str | None = None) -> None:
        """Store raw bytes in MinIO."""
        resolved_content_type = content_type or "application/octet-stream"
        stream = io.BytesIO(data)
        try:
            await asyncio.to_thread(
                self._client.put_object,
                self._bucket,
                key,
                stream,
                length=len(data),
                content_type=resolved_content_type,
            )
        except S3Error as exc:
            raise StorageError(
                f"MinIO put failed: {exc}", bucket=self._bucket, key=key
            ) from exc
        except Exception as exc:
            raise StorageError(
                f"MinIO put failed: {exc}", bucket=self._bucket, key=key
            ) from exc

    async def put_json(self, key: str, obj: dict) -> None:
        """JSON-encode and store an object in MinIO."""
        data = json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        await self.put(key, data, content_type="application/json")

    async def list_objects(self, prefix: str) -> list[str]:
        """List all object keys with the given prefix in MinIO."""
        try:
            objects = await asyncio.to_thread(
                lambda: list(self._client.list_objects(self._bucket, prefix=prefix, recursive=True))
            )
            return [obj.object_name for obj in objects if obj.object_name is not None]
        except S3Error as exc:
            raise StorageError(
                f"MinIO list failed: {exc}", bucket=self._bucket, prefix=prefix
            ) from exc
        except Exception as exc:
            raise StorageError(
                f"MinIO list failed: {exc}", bucket=self._bucket, prefix=prefix
            ) from exc

    async def exists(self, key: str) -> bool:
        """Check if an object exists in MinIO."""
        try:
            await asyncio.to_thread(
                self._client.stat_object,
                self._bucket,
                key,
            )
            return True
        except S3Error as exc:
            if self._is_not_found(exc):
                return False
            raise StorageError(
                f"MinIO exists check failed: {exc}", bucket=self._bucket, key=key
            ) from exc
        except Exception as exc:
            raise StorageError(
                f"MinIO exists check failed: {exc}", bucket=self._bucket, key=key
            ) from exc

    async def delete(self, key: str) -> None:
        """Delete an object from MinIO (idempotent)."""
        try:
            await asyncio.to_thread(
                self._client.remove_object,
                self._bucket,
                key,
            )
        except S3Error as exc:
            if self._is_not_found(exc):
                return
            raise StorageError(
                f"MinIO delete failed: {exc}", bucket=self._bucket, key=key
            ) from exc
        except Exception as exc:
            raise StorageError(
                f"MinIO delete failed: {exc}", bucket=self._bucket, key=key
            ) from exc

    async def presigned_upload_url(self, key: str, expires_sec: int = 3600) -> str:
        """Generate a presigned PUT URL for MinIO."""
        try:
            url: str = await asyncio.to_thread(
                self._client.presigned_put_object,
                self._bucket,
                key,
                expires=timedelta(seconds=expires_sec),
            )
            return url
        except S3Error as exc:
            raise StorageError(
                f"MinIO presigned upload URL failed: {exc}", bucket=self._bucket, key=key
            ) from exc
        except Exception as exc:
            raise StorageError(
                f"MinIO presigned upload URL failed: {exc}", bucket=self._bucket, key=key
            ) from exc

    async def presigned_download_url(self, key: str, expires_sec: int = 3600) -> str:
        """Generate a presigned GET URL for MinIO."""
        try:
            url: str = await asyncio.to_thread(
                self._client.presigned_get_object,
                self._bucket,
                key,
                expires=timedelta(seconds=expires_sec),
            )
            return url
        except S3Error as exc:
            raise StorageError(
                f"MinIO presigned download URL failed: {exc}", bucket=self._bucket, key=key
            ) from exc
        except Exception as exc:
            raise StorageError(
                f"MinIO presigned download URL failed: {exc}", bucket=self._bucket, key=key
            ) from exc
