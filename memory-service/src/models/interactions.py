from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, JSON, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, IdMixin, TenantMixin


class Interaction(Base, IdMixin, TenantMixin):
    """Conversation log entry for learning and memory extraction."""

    __tablename__ = "interactions"

    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    session_id: Mapped[str] = mapped_column(Text, nullable=False)
    messages: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=datetime.utcnow,
    )

    __table_args__ = (
        Index("idx_interactions_tenant_user", "tenant_id", "user_id"),
        Index("idx_interactions_tenant_created", "tenant_id", "created_at"),
    )
