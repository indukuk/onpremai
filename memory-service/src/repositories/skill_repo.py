from __future__ import annotations

from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.skills import Skill, SkillVersion


class SkillRepository:
    """Repository for skill version management."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_active(self, skill_id: str) -> SkillVersion | None:
        """Get the current active version of a skill."""
        result = await self._session.execute(
            select(SkillVersion).where(
                SkillVersion.skill_id == skill_id,
                SkillVersion.status == "active",
            )
        )
        return result.scalar_one_or_none()

    async def get_version(self, skill_id: str, version: int) -> SkillVersion | None:
        """Get a specific version of a skill."""
        result = await self._session.execute(
            select(SkillVersion).where(
                SkillVersion.skill_id == skill_id,
                SkillVersion.version == version,
            )
        )
        return result.scalar_one_or_none()

    async def get_history(self, skill_id: str) -> list[SkillVersion]:
        """Get all versions of a skill."""
        result = await self._session.execute(
            select(SkillVersion)
            .where(SkillVersion.skill_id == skill_id)
            .order_by(SkillVersion.version.desc())
        )
        return list(result.scalars().all())

    async def create_version(
        self,
        skill_id: str,
        prompt_template: str,
        config: dict | None,
        author: str,
        reason: str | None,
        status: str = "active",
    ) -> SkillVersion:
        """Create a new version for a skill. Creates the skill if it does not exist."""
        # Check if skill exists
        skill_result = await self._session.execute(
            select(Skill).where(Skill.id == skill_id)
        )
        skill = skill_result.scalar_one_or_none()

        if skill is None:
            # Create the skill
            skill = Skill(id=skill_id, current_version=1)
            self._session.add(skill)
            new_version = 1
        else:
            new_version = skill.current_version + 1
            skill.current_version = new_version
            self._session.add(skill)

        # If the new version is 'active', retire the current active version
        if status == "active":
            await self._session.execute(
                update(SkillVersion)
                .where(
                    SkillVersion.skill_id == skill_id,
                    SkillVersion.status == "active",
                )
                .values(status="retired")
            )

        version = SkillVersion(
            skill_id=skill_id,
            version=new_version,
            prompt_template=prompt_template,
            config=config,
            author=author,
            reason=reason,
            status=status,
        )
        self._session.add(version)
        await self._session.flush()
        return version

    async def rollback(self, skill_id: str, target_version: int) -> SkillVersion | None:
        """Rollback to a previous version (set it active, retire current)."""
        target = await self.get_version(skill_id, target_version)
        if target is None:
            return None

        # Retire current active
        await self._session.execute(
            update(SkillVersion)
            .where(
                SkillVersion.skill_id == skill_id,
                SkillVersion.status == "active",
            )
            .values(status="retired")
        )

        # Activate target
        target.status = "active"
        self._session.add(target)

        # Update skill.current_version
        skill_result = await self._session.execute(
            select(Skill).where(Skill.id == skill_id)
        )
        skill = skill_result.scalar_one_or_none()
        if skill:
            skill.current_version = target_version
            self._session.add(skill)

        return target

    async def search(
        self,
        role: str | None = None,
        trigger: str | None = None,
        limit: int = 50,
    ) -> list[SkillVersion]:
        """Search skills by role or trigger in config."""
        stmt = select(SkillVersion).where(SkillVersion.status.in_(["active", "canary"]))
        if role:
            stmt = stmt.where(
                SkillVersion.config["role"].as_string() == role
            )
        stmt = stmt.limit(limit)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
