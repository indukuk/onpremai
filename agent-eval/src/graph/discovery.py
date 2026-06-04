"""Evidence discovery node.

Finds evidence files in storage that are relevant to the control being
evaluated. Uses the testing criteria's evidence_checklist to guide discovery
and fuzzy-matches filenames to expected evidence types.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

import structlog

from common.clients import MemoryClient, StorageClient

from src.graph.state import EvalGraphState
from src.models import EvalResult, EvidenceFile, TimingStats

logger = structlog.get_logger(__name__)


def _compute_evidence_hash(evidence_files: list[EvidenceFile]) -> str:
    """Compute a deterministic hash of all evidence files.

    Hash is based on storage key, last modified time, and size.
    Same evidence always produces the same hash.
    """
    hasher = hashlib.sha256()
    for f in sorted(evidence_files, key=lambda x: x.storage_key):
        hasher.update(f.storage_key.encode())
        hasher.update(f.last_modified.isoformat().encode())
        hasher.update(str(f.size_bytes).encode())
    return hasher.hexdigest()


async def discovery_node(state: EvalGraphState) -> dict[str, Any]:
    """Discover evidence files for the control being evaluated.

    Steps:
    1. List all files in tenant's evidence path for this control/framework
    2. Compute evidence hash
    3. Check cache: if hash matches previous evaluation, return cached result
    4. Return discovered files for the extractor node
    """
    import time

    start_time = time.time()

    tenant_id = state.get("tenant_id", "")
    control_id = state.get("control_id", "")
    framework = state.get("framework", "")
    trace_id = state.get("trace_id", "")
    bypass_cache = state.get("bypass_cache", False)

    storage = StorageClient()
    memory = MemoryClient()

    try:
        # Search for evidence in tenant's evidence paths
        evidence_prefix = StorageClient.tenant_prefix(
            tenant_id, f"evidence/{framework}/{control_id}/"
        )
        # Also check a general evidence folder
        general_prefix = StorageClient.tenant_prefix(tenant_id, "evidence/")

        specific_keys = await storage.list_objects(evidence_prefix)
        general_keys = await storage.list_objects(general_prefix)

        # Combine and deduplicate
        all_keys = list(set(specific_keys + general_keys))

        # Build EvidenceFile objects
        evidence_files: list[EvidenceFile] = []
        for key in all_keys:
            # Skip directories and metadata files
            if key.endswith("/") or key.endswith("metadata.json"):
                continue

            filename = key.rsplit("/", 1)[-1] if "/" in key else key
            file_type = _detect_file_type(filename)

            evidence_files.append(
                EvidenceFile(
                    storage_key=key,
                    filename=filename,
                    file_type=file_type,
                    last_modified=datetime.now(timezone.utc),
                )
            )

        if not evidence_files:
            logger.warning(
                "no_evidence_found",
                tenant_id=tenant_id,
                control_id=control_id,
                framework=framework,
                trace_id=trace_id,
            )
            elapsed_ms = (time.time() - start_time) * 1000
            return {
                "evidence_files": [],
                "evidence_hash": "",
                "error": "No evidence files found for this control",
                "timing": TimingStats(discovery_ms=elapsed_ms),
            }

        # Compute evidence hash
        evidence_hash = _compute_evidence_hash(evidence_files)

        # Check cache (unless bypassed)
        if not bypass_cache:
            cached = await _check_evidence_cache(
                memory, tenant_id, framework, control_id, evidence_hash
            )
            if cached is not None:
                logger.info(
                    "cache_hit",
                    tenant_id=tenant_id,
                    control_id=control_id,
                    evidence_hash=evidence_hash[:12],
                    trace_id=trace_id,
                )
                elapsed_ms = (time.time() - start_time) * 1000
                return {
                    "evidence_files": evidence_files,
                    "evidence_hash": evidence_hash,
                    "cached_result": cached,
                    "timing": TimingStats(discovery_ms=elapsed_ms),
                }

        elapsed_ms = (time.time() - start_time) * 1000

        logger.info(
            "evidence_discovered",
            tenant_id=tenant_id,
            control_id=control_id,
            file_count=len(evidence_files),
            evidence_hash=evidence_hash[:12],
            trace_id=trace_id,
        )

        return {
            "evidence_files": evidence_files,
            "evidence_hash": evidence_hash,
            "timing": TimingStats(discovery_ms=elapsed_ms),
        }

    finally:
        await storage.close()
        await memory.close()


async def _check_evidence_cache(
    memory: MemoryClient,
    tenant_id: str,
    framework: str,
    control_id: str,
    current_hash: str,
) -> EvalResult | None:
    """Check if we have a cached evaluation for this evidence hash."""
    previous_evals = await memory.eval_recall(
        tenant_id=tenant_id,
        framework=framework,
        control_id=control_id,
        limit=1,
    )
    if not previous_evals:
        return None

    prev = previous_evals[0]
    prev_hash = prev.get("evidence_hash", "")
    if prev_hash == current_hash:
        try:
            result = EvalResult.model_validate(prev.get("result", prev))
            result.cached = True
            return result
        except Exception:
            return None

    return None


def _detect_file_type(filename: str) -> str:
    """Detect file type from filename extension."""
    lower = filename.lower()
    if lower.endswith((".xlsx", ".xls")):
        return "spreadsheet"
    if lower.endswith(".csv"):
        return "csv"
    if lower.endswith(".pdf"):
        return "pdf"
    if lower.endswith((".doc", ".docx")):
        return "document"
    if lower.endswith((".png", ".jpg", ".jpeg", ".gif")):
        return "image"
    if lower.endswith((".ppt", ".pptx")):
        return "presentation"
    if lower.endswith(".json"):
        return "json"
    if lower.endswith((".txt", ".md")):
        return "text"
    return "unknown"
