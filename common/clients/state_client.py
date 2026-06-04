"""State client for async job tracking.

Usage:
    from common.clients import StateClient

    state = StateClient()
    await state.set_job_status("job-123", "running", data={"progress": 50})
    status = await state.get_job_status("job-123")

The state client communicates with the Memory Service's /jobs endpoints
for lightweight job status and result persistence.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
import structlog

logger = structlog.get_logger(__name__)


class StateClient:
    """Async client for job state tracking via the Memory Service.

    Provides CRUD operations for job status and results. Uses the
    Memory Service's /jobs path as the backend. All methods handle
    errors gracefully with warnings.
    """

    def __init__(
        self,
        state_url: str | None = None,
        timeout: float = 5.0,
    ) -> None:
        base_url = (
            state_url
            or os.environ.get("MEMORY_URL", "http://memory-service:5000")
        ).rstrip("/")
        self._state_url = f"{base_url}/jobs"
        self._timeout = timeout
        self._http = httpx.AsyncClient(
            base_url=self._state_url,
            timeout=httpx.Timeout(timeout, connect=3.0),
            headers={"Content-Type": "application/json"},
        )

    async def set_job_status(
        self,
        job_id: str,
        status: str,
        data: dict | None = None,
    ) -> bool:
        """Set the status of a job.

        Args:
            job_id: Unique job identifier.
            status: Job status string (e.g., "pending", "running", "completed", "failed").
            data: Optional metadata/progress data.

        Returns:
            True on success, False on failure.
        """
        payload: dict[str, Any] = {
            "job_id": job_id,
            "status": status,
        }
        if data is not None:
            payload["data"] = data

        try:
            response = await self._http.put(f"/status/{job_id}", json=payload)
            if response.status_code >= 400:
                logger.warning(
                    "state_set_status_failed",
                    job_id=job_id,
                    status_code=response.status_code,
                )
                return False
            return True
        except Exception as exc:
            logger.warning(
                "state_set_status_error",
                job_id=job_id,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return False

    async def get_job_status(self, job_id: str) -> dict | None:
        """Get the current status of a job.

        Args:
            job_id: Unique job identifier.

        Returns:
            Status dict with keys like "status", "data", "updated_at",
            or None if not found or on error.
        """
        try:
            response = await self._http.get(f"/status/{job_id}")
            if response.status_code == 404:
                return None
            if response.status_code >= 400:
                logger.warning(
                    "state_get_status_failed",
                    job_id=job_id,
                    status_code=response.status_code,
                )
                return None
            return response.json()
        except Exception as exc:
            logger.warning(
                "state_get_status_error",
                job_id=job_id,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return None

    async def set_job_result(
        self,
        job_id: str,
        result: dict,
    ) -> bool:
        """Store the final result of a completed job.

        Args:
            job_id: Unique job identifier.
            result: The job result payload.

        Returns:
            True on success, False on failure.
        """
        payload: dict[str, Any] = {
            "job_id": job_id,
            "result": result,
        }

        try:
            response = await self._http.put(f"/result/{job_id}", json=payload)
            if response.status_code >= 400:
                logger.warning(
                    "state_set_result_failed",
                    job_id=job_id,
                    status_code=response.status_code,
                )
                return False
            return True
        except Exception as exc:
            logger.warning(
                "state_set_result_error",
                job_id=job_id,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return False

    async def get_job_result(self, job_id: str) -> dict | None:
        """Retrieve the result of a completed job.

        Args:
            job_id: Unique job identifier.

        Returns:
            Result dict, or None if not found or on error.
        """
        try:
            response = await self._http.get(f"/result/{job_id}")
            if response.status_code == 404:
                return None
            if response.status_code >= 400:
                logger.warning(
                    "state_get_result_failed",
                    job_id=job_id,
                    status_code=response.status_code,
                )
                return None
            return response.json()
        except Exception as exc:
            logger.warning(
                "state_get_result_error",
                job_id=job_id,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return None

    async def cleanup_expired(self, ttl_hours: int = 24) -> int:
        """Clean up expired job records.

        Args:
            ttl_hours: Time-to-live in hours. Records older than this are removed.

        Returns:
            Number of records cleaned up, or 0 on failure.
        """
        payload = {"ttl_hours": ttl_hours}

        try:
            response = await self._http.post("/cleanup", json=payload)
            if response.status_code >= 400:
                logger.warning(
                    "state_cleanup_failed",
                    status_code=response.status_code,
                )
                return 0
            data = response.json()
            return data.get("deleted_count", 0)
        except Exception as exc:
            logger.warning(
                "state_cleanup_error",
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return 0

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._http.aclose()
