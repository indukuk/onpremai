"""Agent registry client for service discovery and health tracking.

Usage:
    from common.clients import RegistryClient

    registry = RegistryClient()
    info = await registry.register(
        agent_type="agent-eval",
        version="1.0.0",
        capabilities=["evaluate_control", "score_framework"],
        endpoint="http://agent-eval:8080",
    )
    # Periodic heartbeat
    await registry.heartbeat(agent_id=info["agent_id"], health="healthy")
    # Discover other agents
    agents = await registry.discover(task="preprocess_document")

All methods are soft dependencies -- they return empty/None on failure and
log a warning. Agent operation continues even if registry is down.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
import structlog

logger = structlog.get_logger(__name__)


class RegistryClient:
    """Async client for the Agent Registry (via Memory Service).

    Provides agent registration, heartbeat, discovery, and deregistration.
    All methods degrade gracefully: on any failure they log a warning and
    return empty/None. Agents must not crash if registry is unavailable.
    """

    def __init__(
        self,
        registry_url: str | None = None,
        timeout: float = 5.0,
    ) -> None:
        base_url = (
            registry_url
            or os.environ.get("MEMORY_URL", "http://memory-service:5000")
        ).rstrip("/")
        self._registry_url = f"{base_url}/registry"
        self._timeout = timeout
        self._http = httpx.AsyncClient(
            base_url=self._registry_url,
            timeout=httpx.Timeout(timeout, connect=3.0),
            headers={"Content-Type": "application/json"},
        )

    async def register(
        self,
        agent_type: str,
        version: str,
        capabilities: list[str],
        endpoint: str,
        max_concurrency: int = 10,
        tenant_scope: str | None = None,
        metadata: dict | None = None,
    ) -> dict:
        """Register this agent with the registry.

        Args:
            agent_type: Agent type identifier (e.g., "agent-eval").
            version: Agent version string.
            capabilities: List of task names this agent can handle.
            endpoint: Network endpoint for this agent instance.
            max_concurrency: Maximum concurrent requests this agent handles.
            tenant_scope: Optional tenant restriction (None = serves all tenants).
            metadata: Optional additional metadata.

        Returns:
            Registration response dict (contains agent_id, lease_expires, etc.),
            or empty dict on failure.
        """
        payload: dict[str, Any] = {
            "agent_type": agent_type,
            "version": version,
            "capabilities": capabilities,
            "endpoint": endpoint,
            "max_concurrency": max_concurrency,
        }
        if tenant_scope is not None:
            payload["tenant_scope"] = tenant_scope
        if metadata is not None:
            payload["metadata"] = metadata

        try:
            response = await self._http.post("/agents", json=payload)
            if response.status_code >= 400:
                logger.warning(
                    "registry_register_failed",
                    agent_type=agent_type,
                    status_code=response.status_code,
                )
                return {}
            return response.json()
        except Exception as exc:
            logger.warning(
                "registry_register_error",
                agent_type=agent_type,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return {}

    async def heartbeat(
        self,
        agent_id: str,
        health: str = "healthy",
        current_load: int = 0,
        queue_depth: int = 0,
        degradation_reason: str | None = None,
    ) -> None:
        """Send a heartbeat to keep the agent's lease alive.

        Args:
            agent_id: Agent identifier from registration.
            health: Current health status ("healthy", "degraded", "unhealthy").
            current_load: Number of requests currently being processed.
            queue_depth: Number of requests queued for processing.
            degradation_reason: If health is "degraded", the reason why.
        """
        payload: dict[str, Any] = {
            "health": health,
            "current_load": current_load,
            "queue_depth": queue_depth,
        }
        if degradation_reason is not None:
            payload["degradation_reason"] = degradation_reason

        try:
            response = await self._http.put(f"/agents/{agent_id}/heartbeat", json=payload)
            if response.status_code >= 400:
                logger.warning(
                    "registry_heartbeat_failed",
                    agent_id=agent_id,
                    status_code=response.status_code,
                )
        except Exception as exc:
            logger.warning(
                "registry_heartbeat_error",
                agent_id=agent_id,
                error=str(exc),
                error_type=type(exc).__name__,
            )

    async def discover(
        self,
        task: str,
        tenant_id: str | None = None,
        health_filter: str | None = None,
    ) -> list[dict]:
        """Discover agents capable of handling a specific task.

        Args:
            task: Task name to find agents for.
            tenant_id: Optional tenant filter for scoped agents.
            health_filter: Optional health status filter ("healthy", "degraded").

        Returns:
            List of agent info dicts, or empty list on failure.
        """
        params: dict[str, str] = {"task": task}
        if tenant_id is not None:
            params["tenant_id"] = tenant_id
        if health_filter is not None:
            params["health"] = health_filter

        try:
            response = await self._http.get("/agents/discover", params=params)
            if response.status_code >= 400:
                logger.warning(
                    "registry_discover_failed",
                    task=task,
                    status_code=response.status_code,
                )
                return []
            data = response.json()
            if isinstance(data, list):
                return data
            return data.get("agents", [])
        except Exception as exc:
            logger.warning(
                "registry_discover_error",
                task=task,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return []

    async def deregister(self, agent_id: str) -> None:
        """Remove this agent from the registry.

        Args:
            agent_id: Agent identifier from registration.
        """
        try:
            response = await self._http.delete(f"/agents/{agent_id}")
            if response.status_code >= 400:
                logger.warning(
                    "registry_deregister_failed",
                    agent_id=agent_id,
                    status_code=response.status_code,
                )
        except Exception as exc:
            logger.warning(
                "registry_deregister_error",
                agent_id=agent_id,
                error=str(exc),
                error_type=type(exc).__name__,
            )

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._http.aclose()
