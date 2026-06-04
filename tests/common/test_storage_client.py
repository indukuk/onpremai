"""Tests for common.clients.storage_client StorageClient."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from common.clients.storage_client import StorageClient
from common.storage import StorageAdapter, get_adapter


class TestAdapterSelection:
    """Test that the correct adapter is selected based on backend config."""

    @patch.dict("os.environ", {"STORAGE_BACKEND": "s3", "STORAGE_BUCKET": "my-bucket"})
    @patch("common.clients.storage_client.get_adapter")
    def test_s3_adapter_selected_from_env(self, mock_get_adapter):
        mock_adapter = AsyncMock(spec=StorageAdapter)
        mock_get_adapter.return_value = mock_adapter

        client = StorageClient()

        mock_get_adapter.assert_called_once()
        call_kwargs = mock_get_adapter.call_args
        assert call_kwargs.args[0] == "s3"
        assert call_kwargs.kwargs["bucket"] == "my-bucket"

    @patch.dict("os.environ", {
        "STORAGE_BACKEND": "minio",
        "STORAGE_BUCKET": "test-bucket",
        "STORAGE_ENDPOINT": "localhost:9000",
        "STORAGE_ACCESS_KEY": "minio-key",
        "STORAGE_SECRET_KEY": "minio-secret",
    })
    @patch("common.clients.storage_client.get_adapter")
    def test_minio_adapter_selected_from_env(self, mock_get_adapter):
        mock_adapter = AsyncMock(spec=StorageAdapter)
        mock_get_adapter.return_value = mock_adapter

        client = StorageClient()

        mock_get_adapter.assert_called_once()
        call_kwargs = mock_get_adapter.call_args
        assert call_kwargs.args[0] == "minio"
        assert call_kwargs.kwargs["bucket"] == "test-bucket"
        assert call_kwargs.kwargs["endpoint"] == "localhost:9000"
        assert call_kwargs.kwargs["access_key"] == "minio-key"
        assert call_kwargs.kwargs["secret_key"] == "minio-secret"

    @patch("common.clients.storage_client.get_adapter")
    def test_explicit_backend_overrides_env(self, mock_get_adapter):
        mock_adapter = AsyncMock(spec=StorageAdapter)
        mock_get_adapter.return_value = mock_adapter

        client = StorageClient(backend="minio", bucket="explicit-bucket",
                               endpoint="my-minio:9000", access_key="ak", secret_key="sk")

        call_kwargs = mock_get_adapter.call_args
        assert call_kwargs.args[0] == "minio"
        assert call_kwargs.kwargs["bucket"] == "explicit-bucket"


class TestTenantPrefixEnforcement:
    """Test that tenant_prefix ensures proper path scoping."""

    def test_basic_prefix(self):
        result = StorageClient.tenant_prefix("tenant-123", "evidence/file.json")
        assert result == "tenant-123/evidence/file.json"

    def test_strips_leading_slash_from_key(self):
        result = StorageClient.tenant_prefix("tenant-123", "/evidence/file.json")
        assert result == "tenant-123/evidence/file.json"

    def test_strips_trailing_slash_from_tenant(self):
        result = StorageClient.tenant_prefix("tenant-123/", "evidence/file.json")
        assert result == "tenant-123/evidence/file.json"

    def test_handles_both_slashes(self):
        result = StorageClient.tenant_prefix("/tenant-123/", "/evidence/file.json")
        assert result == "tenant-123/evidence/file.json"

    def test_nested_key_path(self):
        result = StorageClient.tenant_prefix("t-1", "evidence/SOC2/CC6.1/metadata.json")
        assert result == "t-1/evidence/SOC2/CC6.1/metadata.json"

    def test_empty_key(self):
        result = StorageClient.tenant_prefix("t-1", "")
        assert result == "t-1/"


class TestStorageClientDelegation:
    """Test that StorageClient delegates all calls to the adapter."""

    @pytest.fixture
    def storage_client(self) -> StorageClient:
        """Create a StorageClient with a mocked adapter."""
        with patch("common.clients.storage_client.get_adapter") as mock_get_adapter:
            mock_adapter = AsyncMock(spec=StorageAdapter)
            mock_get_adapter.return_value = mock_adapter
            client = StorageClient(backend="s3", bucket="test")
            client._mock_adapter = mock_adapter  # type: ignore[attr-defined]
            return client

    @pytest.mark.asyncio
    async def test_get_delegates(self, storage_client):
        storage_client._mock_adapter.get.return_value = b"data"  # type: ignore[attr-defined]
        result = await storage_client.get("key/path")
        storage_client._mock_adapter.get.assert_awaited_once_with("key/path")  # type: ignore[attr-defined]
        assert result == b"data"

    @pytest.mark.asyncio
    async def test_get_json_delegates(self, storage_client):
        storage_client._mock_adapter.get_json.return_value = {"score": 0.9}  # type: ignore[attr-defined]
        result = await storage_client.get_json("key.json")
        storage_client._mock_adapter.get_json.assert_awaited_once_with("key.json")  # type: ignore[attr-defined]
        assert result == {"score": 0.9}

    @pytest.mark.asyncio
    async def test_put_delegates(self, storage_client):
        await storage_client.put("key", b"bytes", content_type="text/plain")
        storage_client._mock_adapter.put.assert_awaited_once_with(  # type: ignore[attr-defined]
            "key", b"bytes", content_type="text/plain"
        )

    @pytest.mark.asyncio
    async def test_put_json_delegates(self, storage_client):
        await storage_client.put_json("key.json", {"data": True})
        storage_client._mock_adapter.put_json.assert_awaited_once_with(  # type: ignore[attr-defined]
            "key.json", {"data": True}
        )

    @pytest.mark.asyncio
    async def test_list_objects_delegates(self, storage_client):
        storage_client._mock_adapter.list_objects.return_value = ["a.json", "b.json"]  # type: ignore[attr-defined]
        result = await storage_client.list_objects("prefix/")
        assert result == ["a.json", "b.json"]

    @pytest.mark.asyncio
    async def test_exists_delegates(self, storage_client):
        storage_client._mock_adapter.exists.return_value = True  # type: ignore[attr-defined]
        result = await storage_client.exists("key")
        assert result is True

    @pytest.mark.asyncio
    async def test_delete_delegates(self, storage_client):
        await storage_client.delete("key")
        storage_client._mock_adapter.delete.assert_awaited_once_with("key")  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_presigned_upload_url_delegates(self, storage_client):
        storage_client._mock_adapter.presigned_upload_url.return_value = "https://upload.url"  # type: ignore[attr-defined]
        result = await storage_client.presigned_upload_url("key", expires_sec=600)
        storage_client._mock_adapter.presigned_upload_url.assert_awaited_once_with(  # type: ignore[attr-defined]
            "key", expires_sec=600
        )
        assert result == "https://upload.url"

    @pytest.mark.asyncio
    async def test_presigned_download_url_delegates(self, storage_client):
        storage_client._mock_adapter.presigned_download_url.return_value = "https://download.url"  # type: ignore[attr-defined]
        result = await storage_client.presigned_download_url("key", expires_sec=300)
        assert result == "https://download.url"

    @pytest.mark.asyncio
    async def test_close_delegates(self, storage_client):
        await storage_client.close()
        storage_client._mock_adapter.close.assert_awaited_once()  # type: ignore[attr-defined]


class TestGetAdapterFactory:
    """Test the get_adapter factory function directly."""

    def test_invalid_backend_raises_value_error(self):
        with pytest.raises(ValueError, match="Unsupported storage backend"):
            get_adapter("gcs")

    def test_s3_missing_bucket_raises_type_error(self):
        with pytest.raises(TypeError, match="requires 'bucket'"):
            get_adapter("s3")

    def test_minio_missing_endpoint_raises_type_error(self):
        with pytest.raises(TypeError, match="requires 'endpoint'"):
            get_adapter("minio", bucket="b", access_key="a", secret_key="s")

    def test_minio_missing_access_key_raises_type_error(self):
        with pytest.raises(TypeError, match="requires 'access_key'"):
            get_adapter("minio", bucket="b", endpoint="e:9000", secret_key="s")

    def test_minio_missing_secret_key_raises_type_error(self):
        with pytest.raises(TypeError, match="requires 'secret_key'"):
            get_adapter("minio", bucket="b", endpoint="e:9000", access_key="a")
