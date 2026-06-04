"""Shared fixtures for memory-service unit tests."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fake domain objects
# ---------------------------------------------------------------------------

TENANT_A = "tenant-alpha"
TENANT_B = "tenant-beta"
USER_A = "user-001"


def make_tenant_memory(
    tenant_id: str = TENANT_A,
    fact: str = "SOC2 annual audit is due Q4",
    category: str = "compliance",
    source: str = "agent-eval",
    confidence: float = 0.95,
    embedding: list[float] | None = None,
    needs_embedding: bool = False,
    fact_id: uuid.UUID | None = None,
) -> MagicMock:
    """Return a MagicMock that looks like a TenantMemory ORM object."""
    obj = MagicMock()
    obj.id = fact_id or uuid.uuid4()
    obj.tenant_id = tenant_id
    obj.fact = fact
    obj.category = category
    obj.source = source
    obj.confidence = confidence
    obj.embedding = embedding or [0.1] * 1024
    obj.needs_embedding = needs_embedding
    obj.created_at = datetime(2026, 1, 15, 10, 0, 0)
    obj.updated_at = datetime(2026, 1, 15, 10, 0, 0)
    return obj


# ---------------------------------------------------------------------------
# Mock AsyncSession
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_session() -> AsyncMock:
    """Create a mock AsyncSession with standard methods."""
    session = AsyncMock()
    session.execute = AsyncMock()
    session.flush = AsyncMock()
    session.add = MagicMock()
    session.delete = AsyncMock()
    session.begin = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    return session


# ---------------------------------------------------------------------------
# Mock Redis
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_redis() -> AsyncMock:
    """Create a mock async Redis client."""
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock(return_value=True)
    redis.delete = AsyncMock(return_value=1)
    redis.expire = AsyncMock(return_value=True)
    redis.exists = AsyncMock(return_value=0)
    return redis


# ---------------------------------------------------------------------------
# Embedding helper
# ---------------------------------------------------------------------------


def fake_embedding(dim: int = 1024) -> list[float]:
    """Return a dummy embedding vector."""
    return [0.01 * i % 1.0 for i in range(dim)]
