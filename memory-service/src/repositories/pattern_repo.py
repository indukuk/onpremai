from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.patterns import Pattern


class PatternRepository:
    """Repository for cross-tenant patterns. No RLS applied."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(
        self,
        pattern: str,
        context: dict | None,
        confidence: float,
        source: str,
        embedding: list[float] | None,
    ) -> Pattern:
        """Record a new pattern."""
        record = Pattern(
            pattern=pattern,
            context=context,
            confidence=confidence,
            source=source,
            embedding=embedding,
            needs_embedding=embedding is None,
        )
        self._session.add(record)
        await self._session.flush()
        return record

    async def query(
        self,
        query_embedding: list[float],
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """Semantic search over patterns."""
        embedding_str = f"[{','.join(str(v) for v in query_embedding)}]"
        sql = text(
            """
            SELECT id, pattern, context, confidence, hit_count, source,
                   1 - (embedding <=> :query_vec::vector) AS similarity
            FROM patterns
            WHERE embedding IS NOT NULL
            ORDER BY embedding <=> :query_vec::vector
            LIMIT :top_k
            """
        )
        result = await self._session.execute(
            sql,
            {"query_vec": embedding_str, "top_k": top_k},
        )
        rows = result.mappings().all()
        return [
            {
                "id": str(row["id"]),
                "pattern": row["pattern"],
                "context": row["context"],
                "confidence": row["confidence"],
                "hit_count": row["hit_count"],
                "source": row["source"],
                "similarity": float(row["similarity"]),
            }
            for row in rows
        ]

    async def list_patterns(
        self,
        source: str | None = None,
        min_confidence: float | None = None,
        limit: int = 100,
    ) -> list[Pattern]:
        """List patterns with optional filters."""
        stmt = select(Pattern)
        if source:
            stmt = stmt.where(Pattern.source == source)
        if min_confidence is not None:
            stmt = stmt.where(Pattern.confidence >= min_confidence)
        stmt = stmt.order_by(Pattern.hit_count.desc()).limit(limit)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def boost(self, pattern_id: uuid.UUID) -> Pattern | None:
        """Increment hit_count and reset last_used_at (pattern was useful)."""
        result = await self._session.execute(
            select(Pattern).where(Pattern.id == pattern_id)
        )
        pattern = result.scalar_one_or_none()
        if pattern is None:
            return None
        pattern.hit_count += 1
        pattern.last_used_at = datetime.utcnow()
        self._session.add(pattern)
        return pattern

    async def delete(self, pattern_id: uuid.UUID) -> bool:
        """Delete a pattern by ID."""
        result = await self._session.execute(
            select(Pattern).where(Pattern.id == pattern_id)
        )
        pattern = result.scalar_one_or_none()
        if pattern is None:
            return False
        await self._session.delete(pattern)
        return True

    async def get_by_id(self, pattern_id: uuid.UUID) -> Pattern | None:
        """Get a pattern by ID."""
        result = await self._session.execute(
            select(Pattern).where(Pattern.id == pattern_id)
        )
        return result.scalar_one_or_none()
