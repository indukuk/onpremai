from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.user_memory import UserMemory
from src.repositories.base import TenantScopedRepository


class UserMemoryRepository(TenantScopedRepository):
    """Repository for per-user memory facts with vector search and deduplication."""

    def __init__(self, session: AsyncSession, tenant_id: str, user_id: str) -> None:
        super().__init__(session, tenant_id)
        self._user_id = user_id

    async def remember(
        self,
        fact: str,
        category: str,
        source: str,
        confidence: float,
        embedding: list[float] | None,
    ) -> tuple[UserMemory, str]:
        """
        Store a user fact. Returns (record, action) where action is 'created' or 'updated'.
        Performs deduplication if embedding is provided.
        """
        await self._set_tenant_context()

        if embedding is not None:
            existing = await self._find_similar(embedding)
            if existing is not None:
                existing.fact = fact
                existing.confidence = max(existing.confidence, confidence)
                existing.embedding = embedding
                existing.updated_at = datetime.utcnow()
                existing.needs_embedding = False
                self._session.add(existing)
                return existing, "updated"

        record = UserMemory(
            tenant_id=self._tenant_id,
            user_id=self._user_id,
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
        """Semantic search over user facts using cosine similarity."""
        await self._set_tenant_context()

        embedding_str = f"[{','.join(str(v) for v in query_embedding)}]"
        sql = text(
            """
            SELECT id, fact, category, source, confidence,
                   1 - (embedding <=> :query_vec::vector) AS similarity
            FROM user_memory
            WHERE tenant_id = :tenant_id
              AND user_id = :user_id
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
                "user_id": self._user_id,
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

    async def facts(self, category: str | None = None) -> list[UserMemory]:
        """List all facts for this user, optionally filtered by category."""
        await self._set_tenant_context()

        stmt = select(UserMemory).where(
            UserMemory.tenant_id == self._tenant_id,
            UserMemory.user_id == self._user_id,
        )
        if category:
            stmt = stmt.where(UserMemory.category == category)
        stmt = stmt.order_by(UserMemory.created_at.desc())
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def delete_fact(self, fact_id: uuid.UUID) -> bool:
        """Delete a fact by ID, scoped to this user."""
        await self._set_tenant_context()
        result = await self._session.execute(
            select(UserMemory).where(
                UserMemory.id == fact_id,
                UserMemory.tenant_id == self._tenant_id,
                UserMemory.user_id == self._user_id,
            )
        )
        obj = result.scalar_one_or_none()
        if obj is None:
            return False
        await self._session.delete(obj)
        return True

    async def _find_similar(
        self, embedding: list[float], threshold: float = 0.9
    ) -> UserMemory | None:
        """Find the most similar existing user fact above threshold."""
        embedding_str = f"[{','.join(str(v) for v in embedding)}]"
        sql = text(
            """
            SELECT id, 1 - (embedding <=> :query_vec::vector) AS similarity
            FROM user_memory
            WHERE tenant_id = :tenant_id
              AND user_id = :user_id
              AND embedding IS NOT NULL
            ORDER BY embedding <=> :query_vec::vector
            LIMIT 1
            """
        )
        result = await self._session.execute(
            sql,
            {
                "query_vec": embedding_str,
                "tenant_id": self._tenant_id,
                "user_id": self._user_id,
            },
        )
        row = result.mappings().first()
        if row is None:
            return None
        if float(row["similarity"]) < threshold:
            return None

        stmt = select(UserMemory).where(UserMemory.id == row["id"])
        orm_result = await self._session.execute(stmt)
        return orm_result.scalar_one_or_none()
