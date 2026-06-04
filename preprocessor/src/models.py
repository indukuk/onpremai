"""Domain models for the preprocessor service.

These Pydantic models define the structure of processing inputs, outputs,
and metadata that gets written to storage.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class FileType(str, Enum):
    """Detected file types the preprocessor handles."""

    EXCEL = "excel"
    CSV = "csv"
    PDF = "pdf"
    WORD = "word"
    POWERPOINT = "powerpoint"
    IMAGE = "image"
    JSON = "json"
    UNKNOWN = "unknown"


class EvidenceType(str, Enum):
    """Evidence classification based on content structure."""

    STRUCTURED = "structured"
    UNSTRUCTURED = "unstructured"
    MIXED = "mixed"


class ColumnType(str, Enum):
    """Detected column data types for structured files."""

    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    DATE = "date"
    BOOLEAN = "boolean"
    EMAIL = "email"
    ID = "id"
    UNKNOWN = "unknown"


class SheetSchema(BaseModel):
    """Schema information for a single sheet/table in a structured file."""

    name: str = Field(description="Sheet or table name")
    columns: list[str] = Field(default_factory=list, description="Column names")
    row_count: int = Field(default=0, description="Total row count")
    sample_rows: list[dict[str, Any]] = Field(
        default_factory=list,
        description="First N sample rows as dicts",
    )
    column_types: dict[str, str] = Field(
        default_factory=dict,
        description="Mapping of column name to detected type",
    )


class JoinCandidate(BaseModel):
    """A detected join possibility between two files."""

    other_file: str = Field(description="Key of the other file in storage")
    join_column: str = Field(description="Column name that can be joined on")
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Confidence score for this join candidate",
    )


class ProcessingError(BaseModel):
    """Structured error information when processing fails."""

    error_type: str = Field(description="Error classification")
    message: str = Field(description="Human-readable error message")
    recoverable: bool = Field(
        default=False,
        description="Whether retrying might succeed",
    )


class FileMetadata(BaseModel):
    """Complete metadata output for a processed file.

    This is what gets serialized to metadata.json alongside the original file.
    """

    filename: str = Field(description="Original filename")
    file_key: str = Field(description="Full storage key of the original file")
    file_type: FileType = Field(description="Detected file type")
    size_bytes: int = Field(description="File size in bytes")
    content_hash: str = Field(description="SHA-256 content hash for idempotency")
    processed_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO 8601 timestamp of processing",
    )
    evidence_type: EvidenceType = Field(
        default=EvidenceType.UNSTRUCTURED,
        description="Whether file contains structured data",
    )

    # Structured file fields
    sheets: list[SheetSchema] = Field(
        default_factory=list,
        description="Schema info per sheet (Excel/CSV)",
    )
    join_candidates: list[JoinCandidate] = Field(
        default_factory=list,
        description="Detected cross-file join candidates",
    )

    # Unstructured file fields
    extracted_text: str = Field(
        default="",
        description="Extracted text content (PDF, Word, image)",
    )
    page_count: int = Field(default=0, description="Number of pages (PDF/Word)")

    # Error state
    error: ProcessingError | None = Field(
        default=None,
        description="Error details if processing failed",
    )

    # Tenant context
    tenant_id: str = Field(default="", description="Tenant identifier from path")


class ProcessingResult(BaseModel):
    """Result of processing a single file through the pipeline."""

    success: bool = Field(description="Whether processing completed without error")
    file_key: str = Field(description="Storage key of the processed file")
    metadata: FileMetadata | None = Field(
        default=None,
        description="Generated metadata (None if skipped/failed)",
    )
    skipped: bool = Field(
        default=False,
        description="True if file was skipped (already processed, unchanged)",
    )
    error_message: str = Field(
        default="",
        description="Error description if success=False",
    )


class WebhookNotification(BaseModel):
    """S3/MinIO bucket notification payload."""

    event_name: str = Field(default="", description="Event type (e.g., s3:ObjectCreated:Put)")
    bucket_name: str = Field(default="", description="Source bucket name")
    object_key: str = Field(default="", description="Object key that triggered the event")
    object_size: int = Field(default=0, description="Object size in bytes")
    content_type: str = Field(default="", description="MIME type of the object")
