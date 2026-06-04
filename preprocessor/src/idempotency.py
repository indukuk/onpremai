"""Idempotency tracking via content hashing.

Ensures files are not re-processed if their content has not changed.
Uses SHA-256 content hash as the source of truth for change detection.
The processed state is tracked both in-memory (fast) and via metadata.json
existence in storage (durable across restarts).
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class IdempotencyTracker:
    """Tracks processed files by content hash to avoid redundant work.

    In-memory cache is populated from storage on first encounter.
    Survives restarts by checking metadata.json in storage.
    """

    def __init__(self) -> None:
        """Initialize with empty in-memory cache."""
        self._processed: dict[str, _ProcessedEntry] = {}

    @staticmethod
    def compute_hash(file_bytes: bytes) -> str:
        """Compute SHA-256 hash of file content.

        Args:
            file_bytes: Raw file bytes.

        Returns:
            Hex-encoded SHA-256 hash string.
        """
        return hashlib.sha256(file_bytes).hexdigest()

    def is_processed(self, file_key: str, content_hash: str) -> bool:
        """Check if a file has already been processed with this content hash.

        Args:
            file_key: Storage key of the file.
            content_hash: SHA-256 hash of current file content.

        Returns:
            True if file was previously processed with identical content.
        """
        entry = self._processed.get(file_key)
        if entry is None:
            return False
        return entry.content_hash == content_hash

    def mark_processed(self, file_key: str, content_hash: str) -> None:
        """Record that a file has been successfully processed.

        Args:
            file_key: Storage key of the file.
            content_hash: SHA-256 hash of the file content at processing time.
        """
        self._processed[file_key] = _ProcessedEntry(
            content_hash=content_hash,
            processed_at=datetime.now(timezone.utc).isoformat(),
        )
        logger.debug(
            "file_marked_processed",
            file_key=file_key,
            content_hash=content_hash[:16],
        )

    def mark_from_metadata(self, file_key: str, metadata: dict[str, Any]) -> None:
        """Populate cache from existing metadata.json found in storage.

        Called during poll cycle to avoid re-processing files that were
        processed in a prior service lifetime.

        Args:
            file_key: Storage key of the original file.
            metadata: Parsed metadata.json content.
        """
        content_hash = metadata.get("content_hash", "")
        if content_hash:
            self._processed[file_key] = _ProcessedEntry(
                content_hash=content_hash,
                processed_at=metadata.get("processed_at", ""),
            )

    def remove(self, file_key: str) -> None:
        """Remove a file from the processed cache (force re-processing)."""
        self._processed.pop(file_key, None)

    @property
    def processed_count(self) -> int:
        """Number of tracked processed files."""
        return len(self._processed)


class _ProcessedEntry:
    """Internal record of a processed file."""

    __slots__ = ("content_hash", "processed_at")

    def __init__(self, content_hash: str, processed_at: str) -> None:
        self.content_hash = content_hash
        self.processed_at = processed_at
