from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, Index, Integer, JSON, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, IdMixin, TenantMixin


class EvalHistory(Base, IdMixin, TenantMixin):
    """Stores every evaluation result for trend analysis and caching."""

    __tablename__ = "eval_history"

    framework: Mapped[str] = mapped_column(Text, nullable=False)
    control_id: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    evidence_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    result: Mapped[dict] = mapped_column(JSON, nullable=False)
    model_used: Mapped[str | None] = mapped_column(Text, nullable=True)
    tier_used: Mapped[str | None] = mapped_column(Text, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=datetime.utcnow,
    )

    __table_args__ = (
        Index("idx_eval_tenant_fw_ctrl", "tenant_id", "framework", "control_id"),
    )
