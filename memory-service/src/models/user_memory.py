from __future__ import annotations

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, DateTime, Float, Index, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, IdMixin, TenantMixin, TimestampMixin


class UserMemory(Base, IdMixin, TenantMixin, TimestampMixin):
    """Per-user facts stored with vector embeddings for semantic search."""

    __tablename__ = "user_memory"

    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    fact: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, server_default="1.0", default=1.0)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1024), nullable=True)
    needs_embedding: Mapped[bool] = mapped_column(Boolean, server_default="false", default=False)

    __table_args__ = (
        Index("idx_user_mem_tenant_user", "tenant_id", "user_id"),
        Index(
            "idx_user_mem_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )
