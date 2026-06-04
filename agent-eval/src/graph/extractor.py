"""Metadata extraction node.

Loads metadata.json for each evidence file from storage. If metadata
is missing, calls the preprocessor service to generate it. Falls back
to basic inline extraction if the preprocessor is unavailable.
"""

from __future__ import annotations

import time
from typing import Any

import httpx
import structlog

from common.clients import StorageClient
from common.errors import StorageNotFoundError

from src.config import get_settings
from src.graph.state import EvalGraphState
from src.models import EvidenceFile, EvidenceMetadata

logger = structlog.get_logger(__name__)


async def extractor_node(state: EvalGraphState) -> dict[str, Any]:
    """Extract metadata for each discovered evidence file.

    For each file:
    1. Try to load metadata.json from storage (preprocessor output)
    2. If missing, call preprocessor service to generate it
    3. If preprocessor unavailable, do basic inline extraction
    """
    start_time = time.time()

    evidence_files: list[EvidenceFile] = state.get("evidence_files", [])
    tenant_id = state.get("tenant_id", "")
    trace_id = state.get("trace_id", "")

    if not evidence_files:
        return {"evidence_metadata": []}

    settings = get_settings()
    storage = StorageClient()
    metadata_list: list[EvidenceMetadata] = []

    try:
        for evidence_file in evidence_files:
            metadata = await _extract_single_file(
                storage=storage,
                evidence_file=evidence_file,
                preprocessor_url=settings.preprocessor_url,
                trace_id=trace_id,
            )
            metadata_list.append(metadata)

        elapsed_ms = (time.time() - start_time) * 1000

        logger.info(
            "metadata_extracted",
            file_count=len(metadata_list),
            tenant_id=tenant_id,
            trace_id=trace_id,
            elapsed_ms=round(elapsed_ms, 1),
        )

        # Merge timing with existing
        existing_timing = state.get("timing")
        timing_dict: dict[str, float] = {}
        if existing_timing is not None:
            timing_dict["discovery_ms"] = existing_timing.discovery_ms
        timing_dict["extraction_ms"] = elapsed_ms

        from src.models import TimingStats

        return {
            "evidence_metadata": metadata_list,
            "timing": TimingStats(**timing_dict),
        }

    finally:
        await storage.close()


async def _extract_single_file(
    storage: StorageClient,
    evidence_file: EvidenceFile,
    preprocessor_url: str,
    trace_id: str,
) -> EvidenceMetadata:
    """Extract metadata for a single evidence file."""
    # Try to load existing metadata.json
    metadata_key = evidence_file.storage_key + ".metadata.json"

    try:
        metadata_json = await storage.get_json(metadata_key)
        return EvidenceMetadata(
            storage_key=evidence_file.storage_key,
            file_type=metadata_json.get("file_type", evidence_file.file_type),
            columns=metadata_json.get("columns", []),
            row_count=metadata_json.get("row_count", 0),
            sheet_names=metadata_json.get("sheet_names", []),
            text_content=metadata_json.get("text_content", "")[:5000],
            schema_info=metadata_json.get("schema_info", {}),
        )
    except StorageNotFoundError:
        pass
    except Exception as exc:
        logger.warning(
            "metadata_load_error",
            key=metadata_key,
            error=str(exc),
        )

    # Metadata not found, try preprocessor service
    preprocessed = await _call_preprocessor(
        storage_key=evidence_file.storage_key,
        preprocessor_url=preprocessor_url,
        trace_id=trace_id,
    )
    if preprocessed is not None:
        return EvidenceMetadata(
            storage_key=evidence_file.storage_key,
            file_type=preprocessed.get("file_type", evidence_file.file_type),
            columns=preprocessed.get("columns", []),
            row_count=preprocessed.get("row_count", 0),
            sheet_names=preprocessed.get("sheet_names", []),
            text_content=preprocessed.get("text_content", "")[:5000],
            schema_info=preprocessed.get("schema_info", {}),
        )

    # Fallback: basic inline extraction from file type
    return _inline_extraction(evidence_file)


async def _call_preprocessor(
    storage_key: str,
    preprocessor_url: str,
    trace_id: str,
) -> dict[str, Any] | None:
    """Call the preprocessor service to process a file and return metadata."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=5.0)) as client:
            response = await client.post(
                f"{preprocessor_url}/process",
                json={"storage_key": storage_key},
                headers={"X-Trace-Id": trace_id} if trace_id else {},
            )
            if response.status_code == 200:
                return response.json()
            logger.warning(
                "preprocessor_error",
                storage_key=storage_key,
                status=response.status_code,
            )
            return None
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        logger.warning(
            "preprocessor_unavailable",
            storage_key=storage_key,
            error=str(exc),
        )
        return None


def _inline_extraction(evidence_file: EvidenceFile) -> EvidenceMetadata:
    """Basic fallback extraction when preprocessor is unavailable.

    Provides minimal metadata from filename and type alone.
    """
    return EvidenceMetadata(
        storage_key=evidence_file.storage_key,
        file_type=evidence_file.file_type,
        columns=[],
        row_count=0,
        sheet_names=[],
        text_content="",
        schema_info={"source": "inline_fallback"},
    )
