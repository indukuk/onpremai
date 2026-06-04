"""S3 storage adapter using boto3.

Uses the default AWS credential chain (IAM role on AWS, env vars or
~/.aws/credentials locally). All boto3 calls are wrapped in
asyncio.to_thread() for async compatibility.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import boto3
from botocore.exceptions import ClientError

from common.errors import StorageError, StorageNotFoundError
from common.storage.base import StorageAdapter


class S3Adapter(StorageAdapter):
    """AWS S3 storage backend.

    Args:
        bucket: S3 bucket name.
        region: AWS region. Defaults to us-east-1.
    """

    def __init__(self, bucket: str, region: str = "us-east-1") -> None:
        self._bucket = bucket
        self._region = region
        self._client: Any = boto3.client("s3", region_name=region)

    def _is_not_found(self, error: ClientError) -> bool:
        """Check if a ClientError represents a missing key."""
        code = error.response.get("Error", {}).get("Code", "")
        return code in ("NoSuchKey", "404", "NoSuchBucket")

    async def get(self, key: str) -> bytes:
        """Retrieve raw bytes from S3."""
        try:
            response = await asyncio.to_thread(
                self._client.get_object,
                Bucket=self._bucket,
                Key=key,
            )
            body = await asyncio.to_thread(response["Body"].read)
            return body
        except ClientError as exc:
            if self._is_not_found(exc):
                raise StorageNotFoundError(
                    f"Key not found: {key}", bucket=self._bucket, key=key
                ) from exc
            raise StorageError(
                f"S3 get failed: {exc}", bucket=self._bucket, key=key
            ) from exc
        except Exception as exc:
            raise StorageError(
                f"S3 get failed: {exc}", bucket=self._bucket, key=key
            ) from exc

    async def get_json(self, key: str) -> dict:
        """Retrieve and JSON-decode an object from S3."""
        raw = await self.get(key)
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise StorageError(
                f"Invalid JSON at key: {key}", bucket=self._bucket, key=key
            ) from exc

    async def put(self, key: str, data: bytes, content_type: str | None = None) -> None:
        """Store raw bytes in S3."""
        kwargs: dict[str, Any] = {
            "Bucket": self._bucket,
            "Key": key,
            "Body": data,
        }
        if content_type:
            kwargs["ContentType"] = content_type
        else:
            kwargs["ContentType"] = "application/octet-stream"
        try:
            await asyncio.to_thread(self._client.put_object, **kwargs)
        except ClientError as exc:
            raise StorageError(
                f"S3 put failed: {exc}", bucket=self._bucket, key=key
            ) from exc
        except Exception as exc:
            raise StorageError(
                f"S3 put failed: {exc}", bucket=self._bucket, key=key
            ) from exc

    async def put_json(self, key: str, obj: dict) -> None:
        """JSON-encode and store an object in S3."""
        data = json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        await self.put(key, data, content_type="application/json")

    async def list_objects(self, prefix: str) -> list[str]:
        """List all object keys with the given prefix in S3."""
        keys: list[str] = []
        try:
            paginator = self._client.get_paginator("list_objects_v2")
            async_pages = await asyncio.to_thread(
                paginator.paginate,
                Bucket=self._bucket,
                Prefix=prefix,
            )
            pages = await asyncio.to_thread(lambda: list(async_pages))
            for page in pages:
                for obj in page.get("Contents", []):
                    keys.append(obj["Key"])
        except ClientError as exc:
            raise StorageError(
                f"S3 list failed: {exc}", bucket=self._bucket, prefix=prefix
            ) from exc
        except Exception as exc:
            raise StorageError(
                f"S3 list failed: {exc}", bucket=self._bucket, prefix=prefix
            ) from exc
        return keys

    async def exists(self, key: str) -> bool:
        """Check if an object exists in S3."""
        try:
            await asyncio.to_thread(
                self._client.head_object,
                Bucket=self._bucket,
                Key=key,
            )
            return True
        except ClientError as exc:
            if self._is_not_found(exc):
                return False
            raise StorageError(
                f"S3 exists check failed: {exc}", bucket=self._bucket, key=key
            ) from exc
        except Exception as exc:
            raise StorageError(
                f"S3 exists check failed: {exc}", bucket=self._bucket, key=key
            ) from exc

    async def delete(self, key: str) -> None:
        """Delete an object from S3 (idempotent)."""
        try:
            await asyncio.to_thread(
                self._client.delete_object,
                Bucket=self._bucket,
                Key=key,
            )
        except ClientError as exc:
            if self._is_not_found(exc):
                return
            raise StorageError(
                f"S3 delete failed: {exc}", bucket=self._bucket, key=key
            ) from exc
        except Exception as exc:
            raise StorageError(
                f"S3 delete failed: {exc}", bucket=self._bucket, key=key
            ) from exc

    async def presigned_upload_url(self, key: str, expires_sec: int = 3600) -> str:
        """Generate a presigned PUT URL for S3."""
        try:
            url: str = await asyncio.to_thread(
                self._client.generate_presigned_url,
                "put_object",
                Params={"Bucket": self._bucket, "Key": key},
                ExpiresIn=expires_sec,
            )
            return url
        except ClientError as exc:
            raise StorageError(
                f"S3 presigned upload URL failed: {exc}", bucket=self._bucket, key=key
            ) from exc
        except Exception as exc:
            raise StorageError(
                f"S3 presigned upload URL failed: {exc}", bucket=self._bucket, key=key
            ) from exc

    async def presigned_download_url(self, key: str, expires_sec: int = 3600) -> str:
        """Generate a presigned GET URL for S3."""
        try:
            url: str = await asyncio.to_thread(
                self._client.generate_presigned_url,
                "get_object",
                Params={"Bucket": self._bucket, "Key": key},
                ExpiresIn=expires_sec,
            )
            return url
        except ClientError as exc:
            raise StorageError(
                f"S3 presigned download URL failed: {exc}", bucket=self._bucket, key=key
            ) from exc
        except Exception as exc:
            raise StorageError(
                f"S3 presigned download URL failed: {exc}", bucket=self._bucket, key=key
            ) from exc

    async def close(self) -> None:
        """Close the underlying boto3 client."""
        await asyncio.to_thread(self._client.close)
