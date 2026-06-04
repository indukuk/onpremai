"""Client package for all service-to-service communication.

All clients follow the same patterns:
- Async-first (httpx.AsyncClient)
- Graceful degradation (memory/registry never crash on failure)
- Environment-based configuration with override kwargs
- Thread-safe: instantiate once at startup, share across requests
- close() method for clean shutdown

Usage:
    from common.clients import (
        LLMClient, LLMResponse,
        MemoryClient,
        StorageClient,
        SandboxClient, ExecutionResult,
        StateClient,
        RegistryClient,
    )
"""

from __future__ import annotations

from common.clients.llm_client import LLMClient, LLMResponse
from common.clients.memory_client import MemoryClient
from common.clients.registry_client import RegistryClient
from common.clients.sandbox_client import ExecutionResult, SandboxClient
from common.clients.state_client import StateClient
from common.clients.storage_client import StorageClient

__all__ = [
    "ExecutionResult",
    "LLMClient",
    "LLMResponse",
    "MemoryClient",
    "RegistryClient",
    "SandboxClient",
    "StateClient",
    "StorageClient",
]
