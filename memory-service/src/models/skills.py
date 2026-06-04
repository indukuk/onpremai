from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base


class Skill(Base):
    """Skill registry with versioned prompts."""

    __tablename__ = "skills"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1", default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=datetime.utcnow,
    )

    versions: Mapped[list[SkillVersion]] = relationship(
        back_populates="skill",
        lazy="selectin",
        order_by="SkillVersion.version.desc()",
    )


class SkillVersion(Base):
    """Versioned prompt template for a skill."""

    __tablename__ = "skill_versions"

    skill_id: Mapped[str] = mapped_column(
        Text, ForeignKey("skills.id"), primary_key=True
    )
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    prompt_template: Mapped[str] = mapped_column(Text, nullable=False)
    config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    author: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, server_default="active", default="active")
    metrics: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=datetime.utcnow,
    )

    skill: Mapped[Skill] = relationship(back_populates="versions")
