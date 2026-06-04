from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, JSON, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, IdMixin


class AuditTrail(Base, IdMixin):
    """Immutable audit trail. Append-only, no update/delete."""

    __tablename__ = "audit_trail"

    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=datetime.utcnow,
    )
    operation: Mapped[str] = mapped_column(Text, nullable=False)
    tenant_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    trace_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    data: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    __table_args__ = (
        Index("idx_audit_tenant_ts", "tenant_id", "timestamp"),
    )
