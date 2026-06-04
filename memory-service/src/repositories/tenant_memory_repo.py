from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.tenant_memory import TenantMemory
from src.repositories.base import TenantScopedRepository


class TenantMemoryRepository(TenantScopedRepository):
    """Repository for tenant-wide memory facts with vector search and deduplication."""

    async def remember(
        self,
        fact: str,
        category: str,
        source: str,
        confidence: float,
        embedding: list[float] | None,
    ) -> tuple[TenantMemory, str]:
        """
        Store a tenant fact. Returns (record, action) where action is 'created' or 'updated'.
        Performs deduplication check if embedding is provided.
        """
        await self._set_tenant_context()

        # Check for duplicates via semantic similarity if embedding is available
        if embedding is not None:
            existing = await self._find_similar(embedding)
            if existing is not None:
                # Update existing fact
                existing.fact = fact
                existing.confidence = max(existing.confidence, confidence)
                existing.embedding = embedding
                existing.updated_at = datetime.utcnow()
                existing.needs_embedding = False
                self._session.add(existing)
                return existing, "updated"

        # Insert new fact
        record = TenantMemory(
            tenant_id=self._tenant_id,
            fact=fact,
            category=category,
            source=source,
            confidence=confidence,
            embedding=embedding,
            needs_embedding=embedding is None,
        )
        self._session.add(record)
        await self._session.flush()
        return record, "created"

    async def recall(
        self,
        query_embedding: list[float],
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """Semantic search over tenant facts using cosine similarity."""
        await self._set_tenant_context()

        embedding_str = f"[{','.join(str(v) for v in query_embedding)}]"
        sql = text(
            """
            SELECT id, fact, category, source, confidence,
                   1 - (embedding <=> :query_vec::vector) AS similarity
            FROM tenant_memory
            WHERE tenant_id = :tenant_id
              AND embedding IS NOT NULL
            ORDER BY embedding <=> :query_vec::vector
            LIMIT :top_k
            """
        )
        result = await self._session.execute(
            sql,
            {
                "query_vec": embedding_str,
                "tenant_id": self._tenant_id,
                "top_k": top_k,
            },
        )
        rows = result.mappings().all()
        return [
            {
                "id": str(row["id"]),
                "fact": row["fact"],
                "category": row["category"],
                "source": row["source"],
                "confidence": row["confidence"],
                "similarity": float(row["similarity"]),
            }
            for row in rows
        ]

    async def facts(self, category: str | None = None) -> list[TenantMemory]:
        """List all facts for this tenant, optionally filtered by category."""
        await self._set_tenant_context()

        stmt = select(TenantMemory).where(TenantMemory.tenant_id == self._tenant_id)
        if category:
            stmt = stmt.where(TenantMemory.category == category)
        stmt = stmt.order_by(TenantMemory.created_at.desc())
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_id(self, fact_id: uuid.UUID) -> TenantMemory | None:
        """Get a specific fact by ID."""
        return await self._get_by_id(TenantMemory, fact_id)

    async def update_fact(
        self,
        fact_id: uuid.UUID,
        fact: str | None = None,
        confidence: float | None = None,
    ) -> TenantMemory | None:
        """Update an existing fact."""
        await self._set_tenant_context()
        record = await self._get_by_id(TenantMemory, fact_id)
        if record is None:
            return None
        if fact is not None:
            record.fact = fact
            record.needs_embedding = True
        if confidence is not None:
            record.confidence = confidence
        record.updated_at = datetime.utcnow()
        self._session.add(record)
        return record

    async def delete_fact(self, fact_id: uuid.UUID) -> bool:
        """Delete a fact by ID."""
        return await self._delete_by_id(TenantMemory, fact_id)

    async def _find_similar(
        self, embedding: list[float], threshold: float = 0.9
    ) -> TenantMemory | None:
        """Find the most similar existing fact above the dedup threshold."""
        embedding_str = f"[{','.join(str(v) for v in embedding)}]"
        sql = text(
            """
            SELECT id, fact, category, source, confidence, embedding, needs_embedding,
                   tenant_id, created_at, updated_at,
                   1 - (embedding <=> :query_vec::vector) AS similarity
            FROM tenant_memory
            WHERE tenant_id = :tenant_id
              AND embedding IS NOT NULL
            ORDER BY embedding <=> :query_vec::vector
            LIMIT 1
            """
        )
        result = await self._session.execute(
            sql,
            {"query_vec": embedding_str, "tenant_id": self._tenant_id},
        )
        row = result.mappings().first()
        if row is None:
            return None
        if float(row["similarity"]) < threshold:
            return None

        # Load the actual ORM object
        stmt = select(TenantMemory).where(TenantMemory.id == row["id"])
        orm_result = await self._session.execute(stmt)
        return orm_result.scalar_one_or_none()
