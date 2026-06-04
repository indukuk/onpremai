"""Configuration for the preprocessor service.

All settings are sourced from environment variables with sensible defaults
that work in a docker-compose environment.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings


class TriggerMode(str, Enum):
    """Supported trigger modes for file processing."""

    POLL = "poll"
    WEBHOOK = "webhook"
    EVENT = "event"


class OcrBackend(str, Enum):
    """Supported OCR backends."""

    TESSERACT = "tesseract"
    TEXTRACT = "textract"
    AZURE_DI = "azure_di"


class PdfBackend(str, Enum):
    """Supported PDF text extraction backends."""

    PDFPLUMBER = "pdfplumber"
    PYMUPDF = "pymupdf"
    TIKA = "tika"


class PreprocessorSettings(BaseSettings):
    """Preprocessor service configuration.

    All values read from environment variables with docker-compose-friendly defaults.
    """

    # Storage
    storage_endpoint: str = Field(
        default="http://minio:9000",
        description="Storage service URL (MinIO or S3-compatible)",
    )
    storage_bucket: str = Field(
        default="compliance-artifacts",
        description="Primary bucket name for artifacts",
    )
    storage_backend: Literal["s3", "minio"] = Field(
        default="minio",
        description="Storage backend type",
    )
    storage_access_key: str = Field(default="", description="Storage access key")
    storage_secret_key: str = Field(default="", description="Storage secret key")

    # External services
    memory_url: str = Field(
        default="http://memory-service:5000",
        description="Memory service URL",
    )
    llm_gateway_url: str = Field(
        default="",
        description="LLM gateway URL (optional - LLM features disabled if empty)",
    )

    # Trigger configuration
    trigger_mode: TriggerMode = Field(
        default=TriggerMode.POLL,
        description="How new files are detected: poll, webhook, or event",
    )
    poll_interval_sec: int = Field(
        default=30,
        ge=5,
        le=3600,
        description="Seconds between poll cycles",
    )
    watch_prefix: str = Field(
        default="uploads/",
        description="Storage prefix to watch for new files",
    )

    # Backend selection
    ocr_backend: OcrBackend = Field(
        default=OcrBackend.TESSERACT,
        description="OCR backend for scanned docs and images",
    )
    pdf_backend: PdfBackend = Field(
        default=PdfBackend.PDFPLUMBER,
        description="PDF text extraction backend for digital PDFs",
    )

    # Limits
    max_file_size_mb: int = Field(
        default=100,
        ge=1,
        le=1000,
        description="Maximum file size to process in MB",
    )

    # Service
    port: int = Field(default=7000, ge=1, le=65535, description="HTTP server port")
    log_level: str = Field(default="info", description="Logging verbosity level")
    service_name: str = Field(default="preprocessor", description="Service name for logging")

    model_config = {"env_prefix": "", "case_sensitive": False}

    @property
    def max_file_size_bytes(self) -> int:
        """Maximum file size in bytes."""
        return self.max_file_size_mb * 1024 * 1024

    @property
    def llm_enabled(self) -> bool:
        """Whether LLM gateway integration is available."""
        return bool(self.llm_gateway_url)


def get_settings() -> PreprocessorSettings:
    """Factory to create settings instance (supports testing overrides)."""
    return PreprocessorSettings()
