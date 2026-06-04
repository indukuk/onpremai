"""RAG index loader.

Loads the compliance knowledge base chunks from storage on startup.
Indexes testing criteria by (framework, control_id) for fast lookup.
Supports both local filesystem and S3/MinIO-backed index loading.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import structlog

from common.clients import StorageClient
from common.errors import StorageNotFoundError

logger = structlog.get_logger(__name__)


class RAGIndex:
    """In-memory RAG index for compliance knowledge and testing criteria.

    Loads chunks from a JSON file and indexes them by type for fast access.
    The index is loaded once on startup and cached in memory.
    """

    def __init__(self) -> None:
        self._chunks: list[dict[str, Any]] = []
        self._criteria_index: dict[str, int] = {}  # "(framework, control_id)" -> chunk_index
        self._loaded = False

    @property
    def loaded(self) -> bool:
        """Whether the index has been loaded."""
        return self._loaded

    @property
    def chunk_count(self) -> int:
        """Total number of chunks in the index."""
        return len(self._chunks)

    async def load(self, index_path: str | None = None) -> None:
        """Load the RAG index from storage or local filesystem.

        Args:
            index_path: Path to the RAG index. Can be a local directory or
                       an S3/MinIO prefix. Reads RAG_INDEX_PATH env if None.
        """
        path = index_path or os.environ.get("RAG_INDEX_PATH", "/data/rag/")

        if path.startswith("s3://") or path.startswith("http"):
            await self._load_from_storage(path)
        else:
            self._load_from_filesystem(path)

        self._build_criteria_index()
        self._loaded = True

        logger.info(
            "rag_index_loaded",
            total_chunks=len(self._chunks),
            criteria_indexed=len(self._criteria_index),
        )

    def get_testing_criteria(self, framework: str, control_id: str) -> dict[str, Any] | None:
        """Get testing criteria for a specific control.

        Args:
            framework: Compliance framework (e.g., "soc2").
            control_id: Control identifier (e.g., "CC6.1").

        Returns:
            Testing criteria dict, or None if not found.
        """
        key = f"{framework.lower()}:{control_id.upper()}"
        chunk_idx = self._criteria_index.get(key)
        if chunk_idx is not None:
            return self._chunks[chunk_idx]

        # Try without case sensitivity
        for stored_key, idx in self._criteria_index.items():
            if stored_key.lower() == key.lower():
                return self._chunks[idx]

        return None

    def search(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        """Simple keyword search over chunks.

        For production, this would use embedding-based similarity search
        via LLMClient.embed(). This is a fallback for basic retrieval.
        """
        query_lower = query.lower()
        scored: list[tuple[float, dict[str, Any]]] = []

        for chunk in self._chunks:
            text = json.dumps(chunk).lower()
            # Simple scoring: count query terms in chunk
            terms = query_lower.split()
            score = sum(1.0 for term in terms if term in text)
            if score > 0:
                scored.append((score, chunk))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [chunk for _, chunk in scored[:top_k]]

    async def _load_from_storage(self, path: str) -> None:
        """Load chunks from S3/MinIO storage."""
        storage = StorageClient()
        try:
            # Try to load chunks.json
            if path.startswith("s3://"):
                key = path.replace("s3://", "").split("/", 1)[-1] + "chunks.json"
            else:
                key = path.rstrip("/") + "/chunks.json"

            try:
                data = await storage.get_json(key)
                if isinstance(data, list):
                    self._chunks = data
                elif isinstance(data, dict):
                    self._chunks = data.get("chunks", [])
            except StorageNotFoundError:
                logger.warning("rag_chunks_not_found", key=key)
                self._chunks = []
        finally:
            await storage.close()

    def _load_from_filesystem(self, path: str) -> None:
        """Load chunks from local filesystem."""
        chunks_path = Path(path) / "chunks.json"
        if chunks_path.exists():
            with open(chunks_path) as f:
                data = json.load(f)
                if isinstance(data, list):
                    self._chunks = data
                elif isinstance(data, dict):
                    self._chunks = data.get("chunks", [])
        else:
            logger.warning("rag_chunks_file_missing", path=str(chunks_path))
            self._chunks = []

    def _build_criteria_index(self) -> None:
        """Build the criteria lookup index from loaded chunks."""
        self._criteria_index.clear()
        for idx, chunk in enumerate(self._chunks):
            if chunk.get("chunk_type") == "testing_criteria":
                framework = chunk.get("framework", "").lower()
                control_id = chunk.get("control_id", "").upper()
                if framework and control_id:
                    key = f"{framework}:{control_id}"
                    self._criteria_index[key] = idx


# Module-level singleton
_rag_index: RAGIndex | None = None


def get_rag_index() -> RAGIndex:
    """Get the module-level RAG index singleton."""
    global _rag_index
    if _rag_index is None:
        _rag_index = RAGIndex()
    return _rag_index


async def initialize_rag_index(index_path: str | None = None) -> RAGIndex:
    """Initialize and load the RAG index."""
    index = get_rag_index()
    if not index.loaded:
        await index.load(index_path)
    return index
