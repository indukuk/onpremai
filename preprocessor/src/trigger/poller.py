"""Poll-based trigger for detecting new files in storage.

Periodically lists objects in the configured watch prefix and processes
any files that are new or have changed since the last poll cycle.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import structlog

from src.config import PreprocessorSettings
from src.idempotency import IdempotencyTracker

if TYPE_CHECKING:
    from src.processing.pipeline import ProcessingPipeline

logger = structlog.get_logger(__name__)


class Poller:
    """Background polling trigger that scans storage for new files.

    Runs as an asyncio background task, checking for new or changed files
    at the configured interval.
    """

    def __init__(
        self,
        settings: PreprocessorSettings,
        pipeline: "ProcessingPipeline",
        tracker: IdempotencyTracker,
    ) -> None:
        """Initialize the poller.

        Args:
            settings: Service configuration.
            pipeline: Processing pipeline to invoke for new files.
            tracker: Idempotency tracker for skip decisions.
        """
        self._settings = settings
        self._pipeline = pipeline
        self._tracker = tracker
        self._running = False
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Start the background polling loop."""
        if self._running:
            logger.warning("poller_already_running")
            return
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info(
            "poller_started",
            interval_sec=self._settings.poll_interval_sec,
            watch_prefix=self._settings.watch_prefix,
        )

    async def stop(self) -> None:
        """Stop the background polling loop gracefully."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("poller_stopped")

    async def _poll_loop(self) -> None:
        """Main polling loop - runs until stopped."""
        while self._running:
            try:
                await self._poll_once()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(
                    "poll_cycle_error",
                    error=str(exc),
                    error_type=type(exc).__name__,
                )
            await asyncio.sleep(self._settings.poll_interval_sec)

    async def _poll_once(self) -> None:
        """Execute a single poll cycle: list files and process new ones."""
        from common.clients import StorageClient

        storage = StorageClient(
            backend=self._settings.storage_backend,
            bucket=self._settings.storage_bucket,
            endpoint=self._settings.storage_endpoint,
            access_key=self._settings.storage_access_key,
            secret_key=self._settings.storage_secret_key,
        )

        try:
            keys = await storage.list_objects(self._settings.watch_prefix)
        except Exception as exc:
            logger.error(
                "storage_list_failed",
                prefix=self._settings.watch_prefix,
                error=str(exc),
            )
            return
        finally:
            await storage.close()

        # Filter to actual files (exclude directories and metadata files)
        file_keys = [
            k for k in keys
            if not k.endswith("/")
            and not k.endswith("metadata.json")
            and not k.endswith(".processed")
        ]

        if not file_keys:
            logger.debug("poll_no_files", prefix=self._settings.watch_prefix)
            return

        logger.info(
            "poll_found_files",
            count=len(file_keys),
            prefix=self._settings.watch_prefix,
        )

        for file_key in file_keys:
            try:
                await self._pipeline.process_file(file_key)
            except Exception as exc:
                logger.error(
                    "file_processing_error",
                    file_key=file_key,
                    error=str(exc),
                    error_type=type(exc).__name__,
                )

    @property
    def is_running(self) -> bool:
        """Whether the poller is currently active."""
        return self._running
