"""Log ingestor — reads gateway JSON logs from mounted volume or API.

Implements tail-based reading with offset tracking. Handles log rotation
gracefully by detecting inode changes.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import structlog

from observer.src.config import ObserverSettings

logger = structlog.get_logger(__name__)


@dataclass
class LogEntry:
    """Parsed gateway log entry."""

    timestamp: str
    trace_id: str
    agent: str
    task: str
    tier_requested: str
    tier_used: str
    model_used: str
    escalated: bool
    input_tokens: int
    output_tokens: int
    latency_ms: int
    confidence: float
    success: bool
    error: str | None
    tenant_id: str
    tool_calls_count: int
    parse_success: bool
    cost_usd: float

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LogEntry | None:
        """Parse a dict into a LogEntry, returning None on invalid data."""
        try:
            return cls(
                timestamp=str(data.get("timestamp", "")),
                trace_id=str(data.get("trace_id", "")),
                agent=str(data.get("agent", "")),
                task=str(data.get("task", "")),
                tier_requested=str(data.get("tier_requested", "")),
                tier_used=str(data.get("tier_used", "")),
                model_used=str(data.get("model_used", "")),
                escalated=bool(data.get("escalated", False)),
                input_tokens=int(data.get("input_tokens", 0)),
                output_tokens=int(data.get("output_tokens", 0)),
                latency_ms=int(data.get("latency_ms", 0)),
                confidence=float(data.get("confidence", 0.0)),
                success=bool(data.get("success", True)),
                error=data.get("error"),
                tenant_id=str(data.get("tenant_id", "")),
                tool_calls_count=int(data.get("tool_calls_count", 0)),
                parse_success=bool(data.get("parse_success", True)),
                cost_usd=float(data.get("cost_usd", 0.0)),
            )
        except (ValueError, TypeError, KeyError) as exc:
            logger.warning("failed_to_parse_log_entry", error=str(exc), data_keys=list(data.keys()))
            return None


@dataclass
class FileOffset:
    """Tracks read position in a log file."""

    path: str
    inode: int
    offset: int
    last_read: float = field(default_factory=time.time)


class LogIngestor:
    """Reads and parses structured JSON logs from the LLM gateway.

    The ingestor watches /logs/ for .jsonl files, tracks offsets per file,
    and handles log rotation gracefully (inode change = new file).
    """

    def __init__(self, settings: ObserverSettings) -> None:
        self._settings = settings
        self._log_path = Path(settings.log_path)
        self._offsets: dict[str, FileOffset] = {}
        self._http_client: httpx.AsyncClient | None = None

    async def start(self) -> None:
        """Initialize the HTTP client for supplementary API access."""
        self._http_client = httpx.AsyncClient(
            base_url=self._settings.llm_gateway_admin_url,
            timeout=httpx.Timeout(30.0),
        )

    async def close(self) -> None:
        """Shutdown the HTTP client."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None

    async def ingest(self, since_minutes: int = 60) -> list[LogEntry]:
        """Read all new log entries since last offset.

        Args:
            since_minutes: If no offset exists, only read entries from this many
                           minutes ago (prevents reading entire log history on first run).

        Returns:
            List of parsed LogEntry objects.
        """
        entries: list[LogEntry] = []

        if not self._log_path.exists():
            logger.warning("log_path_not_found", path=str(self._log_path))
            return entries

        jsonl_files = sorted(self._log_path.glob("*.jsonl"))
        if not jsonl_files:
            logger.debug("no_log_files_found", path=str(self._log_path))
            return entries

        cutoff_time = datetime.now(timezone.utc).timestamp() - (since_minutes * 60)

        for file_path in jsonl_files:
            file_entries = self._read_file(file_path, cutoff_time)
            entries.extend(file_entries)

        logger.info("log_ingestion_complete", entries_count=len(entries), files_scanned=len(jsonl_files))
        return entries

    def _read_file(self, file_path: Path, cutoff_time: float) -> list[LogEntry]:
        """Read new entries from a single log file."""
        entries: list[LogEntry] = []
        path_str = str(file_path)

        try:
            stat = file_path.stat()
            current_inode = stat.st_ino
        except OSError:
            return entries

        offset_info = self._offsets.get(path_str)

        # Detect log rotation (inode changed)
        if offset_info and offset_info.inode != current_inode:
            logger.info("log_rotation_detected", path=path_str)
            offset_info = None

        start_offset = offset_info.offset if offset_info else 0

        try:
            with open(file_path, "r", encoding="utf-8") as fh:
                fh.seek(start_offset)
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    # Skip entries older than cutoff if no prior offset
                    if not offset_info:
                        ts_str = data.get("timestamp", "")
                        try:
                            entry_time = datetime.fromisoformat(
                                ts_str.replace("Z", "+00:00")
                            ).timestamp()
                            if entry_time < cutoff_time:
                                continue
                        except (ValueError, TypeError):
                            pass

                    entry = LogEntry.from_dict(data)
                    if entry:
                        entries.append(entry)

                new_offset = fh.tell()
        except OSError as exc:
            logger.error("failed_to_read_log_file", path=path_str, error=str(exc))
            return entries

        self._offsets[path_str] = FileOffset(
            path=path_str,
            inode=current_inode,
            offset=new_offset,
        )

        return entries

    async def fetch_realtime_metrics(self, window: str = "1h") -> dict[str, Any]:
        """Fetch real-time metrics from gateway admin API.

        Supplements file-based ingestion for metrics not yet flushed to log.
        """
        if not self._http_client:
            return {}

        try:
            response = await self._http_client.get(
                "/admin/metrics",
                params={"window": window},
            )
            if response.status_code == 200:
                return response.json()
            logger.warning(
                "gateway_metrics_fetch_failed",
                status=response.status_code,
            )
        except httpx.HTTPError as exc:
            logger.warning("gateway_metrics_fetch_error", error=str(exc))

        return {}

    def get_offset_state(self) -> dict[str, dict[str, int]]:
        """Return current offset state for persistence."""
        return {
            path: {"inode": info.inode, "offset": info.offset}
            for path, info in self._offsets.items()
        }

    def restore_offsets(self, state: dict[str, dict[str, int]]) -> None:
        """Restore offset state from persistence."""
        for path, info in state.items():
            self._offsets[path] = FileOffset(
                path=path,
                inode=info["inode"],
                offset=info["offset"],
            )
