"""Pydantic models for the Sandbox Service API.

Defines ExecutionRequest (POST /execute body) and ExecutionResult (response).
FileReference describes a storage object to load into the sandbox.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated

from pydantic import BaseModel, Field, field_validator


class FileType(str, Enum):
    """Supported file types for automatic DataFrame loading."""

    csv = "csv"
    excel = "excel"
    parquet = "parquet"
    json = "json"
    pdf = "pdf"


class FileReference(BaseModel):
    """Reference to a file in object storage to be loaded into the sandbox."""

    storage_key: str = Field(
        ...,
        min_length=1,
        description="Object path in storage (e.g. 'acme/soc2/cc8.1/processed/file.csv')",
    )
    load_as: str = Field(
        ...,
        min_length=1,
        max_length=64,
        pattern=r"^[a-zA-Z_][a-zA-Z0-9_]*$",
        description="Python variable name for this data (valid identifier)",
    )
    type: FileType = Field(
        ...,
        description="File type determines the pandas reader used",
    )

    @field_validator("storage_key")
    @classmethod
    def validate_storage_key(cls, v: str) -> str:
        """Reject path traversal attempts in storage_key."""
        if ".." in v:
            msg = "storage_key must not contain '..'"
            raise ValueError(msg)
        if v.startswith("/"):
            msg = "storage_key must not start with '/'"
            raise ValueError(msg)
        if "\x00" in v:
            msg = "storage_key must not contain null bytes"
            raise ValueError(msg)
        return v


class ExecutionRequest(BaseModel):
    """Request body for POST /execute."""

    code: str = Field(
        ...,
        min_length=1,
        max_length=1_000_000,
        description="Python code to execute in the sandbox",
    )
    files: list[FileReference] = Field(
        default_factory=list,
        description="Evidence files to download and load before execution",
    )
    timeout_sec: Annotated[int, Field(ge=1, le=300)] = 60
    memory_limit_mb: Annotated[int, Field(ge=64, le=2048)] = 512
    agent: str = Field(
        default="unknown",
        description="Name of the calling agent (for logging)",
    )
    trace_id: str = Field(
        default="",
        description="Distributed trace ID for correlation",
    )

    @field_validator("files")
    @classmethod
    def validate_file_count(cls, v: list[FileReference]) -> list[FileReference]:
        """Ensure no duplicate load_as names."""
        names = [f.load_as for f in v]
        if len(names) != len(set(names)):
            msg = "Duplicate load_as variable names in files array"
            raise ValueError(msg)
        return v


class ExecutionResult(BaseModel):
    """Response body returned from POST /execute."""

    success: bool = Field(
        ...,
        description="True if code exited with code 0 and no timeout/OOM",
    )
    stdout: str = Field(
        default="",
        description="Captured standard output (truncated at max_output_size_mb)",
    )
    stderr: str = Field(
        default="",
        description="Captured standard error",
    )
    duration_ms: int = Field(
        default=0,
        ge=0,
        description="Wall-clock execution time in milliseconds",
    )
    memory_used_mb: int = Field(
        default=0,
        ge=0,
        description="Peak resident memory in MB",
    )


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = "ok"
    service: str = "sandbox-service"


class MetricsResponse(BaseModel):
    """Operational metrics response."""

    total_executions: int = 0
    success_rate: float = 0.0
    avg_duration_ms: float = 0.0
    active_executions: int = 0
    queued: int = 0
    timeouts_last_hour: int = 0
    oom_kills_last_hour: int = 0
