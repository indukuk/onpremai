"""Storage adapter package.

Provides a unified async interface for object storage. The active backend
is selected at runtime via the get_adapter() factory, controlled by the
STORAGE_BACKEND environment variable (values: "s3" or "minio").

Usage:
    from common.storage import get_adapter, StorageAdapter

    adapter = get_adapter("s3", bucket="my-bucket", region="us-west-2")
    data = await adapter.get("tenant/evidence/file.json")
"""

from __future__ import annotations

from common.storage.base import StorageAdapter
from common.storage.minio_adapter import MinIOAdapter
from common.storage.s3_adapter import S3Adapter


def get_adapter(backend: str, **kwargs: object) -> StorageAdapter:
    """Factory function to create the appropriate storage adapter.

    Args:
        backend: Storage backend type. Must be "s3" or "minio".
        **kwargs: Backend-specific configuration passed to the adapter constructor.

    For S3:
        bucket (str): S3 bucket name. Required.
        region (str): AWS region. Defaults to "us-east-1".

    For MinIO:
        endpoint (str): MinIO server endpoint (host:port). Required.
        access_key (str): Access key. Required.
        secret_key (str): Secret key. Required.
        bucket (str): Bucket name. Required.
        secure (bool): Use HTTPS. Defaults to False.

    Returns:
        A configured StorageAdapter instance.

    Raises:
        ValueError: If backend is not "s3" or "minio".
        TypeError: If required kwargs are missing for the chosen backend.
    """
    if backend == "s3":
        bucket = kwargs.get("bucket")
        if not bucket or not isinstance(bucket, str):
            raise TypeError("S3Adapter requires 'bucket' (str) keyword argument")
        region = kwargs.get("region", "us-east-1")
        if not isinstance(region, str):
            raise TypeError("S3Adapter 'region' must be a string")
        return S3Adapter(bucket=bucket, region=region)

    if backend == "minio":
        endpoint = kwargs.get("endpoint")
        access_key = kwargs.get("access_key")
        secret_key = kwargs.get("secret_key")
        bucket = kwargs.get("bucket")
        secure = kwargs.get("secure", False)

        if not endpoint or not isinstance(endpoint, str):
            raise TypeError("MinIOAdapter requires 'endpoint' (str) keyword argument")
        if not access_key or not isinstance(access_key, str):
            raise TypeError("MinIOAdapter requires 'access_key' (str) keyword argument")
        if not secret_key or not isinstance(secret_key, str):
            raise TypeError("MinIOAdapter requires 'secret_key' (str) keyword argument")
        if not bucket or not isinstance(bucket, str):
            raise TypeError("MinIOAdapter requires 'bucket' (str) keyword argument")
        if not isinstance(secure, bool):
            raise TypeError("MinIOAdapter 'secure' must be a boolean")

        return MinIOAdapter(
            endpoint=endpoint,
            access_key=access_key,
            secret_key=secret_key,
            bucket=bucket,
            secure=secure,
        )

    raise ValueError(
        f"Unsupported storage backend: {backend!r}. Must be 's3' or 'minio'."
    )


__all__ = [
    "StorageAdapter",
    "S3Adapter",
    "MinIOAdapter",
    "get_adapter",
]
