from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import get_session
from src.repositories.skill_repo import SkillRepository
from src.repositories.audit_repo import AuditRepository

router = APIRouter(prefix="/skills", tags=["skills"])


class CreateSkillVersionBody(BaseModel):
    prompt_template: str
    config: dict | None = None
    author: str
    reason: str | None = None
    status: str = "active"


def _version_to_dict(v: Any) -> dict[str, Any]:
    return {
        "skill_id": v.skill_id,
        "version": v.version,
        "prompt_template": v.prompt_template,
        "config": v.config,
        "author": v.author,
        "reason": v.reason,
        "status": v.status,
        "metrics": v.metrics,
        "created_at": v.created_at.isoformat() if v.created_at else None,
    }


@router.get("/{skill_id}")
async def get_active_skill(
    skill_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get the current active version of a skill."""
    repo = SkillRepository(session)
    version = await repo.get_active(skill_id)
    if version is None:
        raise HTTPException(status_code=404, detail="Skill not found or no active version")
    return _version_to_dict(version)


@router.get("/{skill_id}/version/{version}")
async def get_skill_version(
    skill_id: str,
    version: int,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get a specific version of a skill."""
    repo = SkillRepository(session)
    v = await repo.get_version(skill_id, version)
    if v is None:
        raise HTTPException(status_code=404, detail="Skill version not found")
    return _version_to_dict(v)


@router.get("/{skill_id}/history")
async def get_skill_history(
    skill_id: str,
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    """Get all versions of a skill."""
    repo = SkillRepository(session)
    versions = await repo.get_history(skill_id)
    if not versions:
        raise HTTPException(status_code=404, detail="Skill not found")
    return [_version_to_dict(v) for v in versions]


@router.post("/{skill_id}")
async def create_skill_version(
    skill_id: str,
    body: CreateSkillVersionBody,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Create a new version for a skill."""
    repo = SkillRepository(session)
    version = await repo.create_version(
        skill_id=skill_id,
        prompt_template=body.prompt_template,
        config=body.config,
        author=body.author,
        reason=body.reason,
        status=body.status,
    )

    audit_repo = AuditRepository(session)
    await audit_repo.append(
        operation="skill_create_version",
        data={
            "skill_id": skill_id,
            "version": version.version,
            "status": body.status,
            "author": body.author,
        },
    )
    return _version_to_dict(version)


@router.post("/{skill_id}/rollback/{version}")
async def rollback_skill(
    skill_id: str,
    version: int,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Rollback to a previous version."""
    repo = SkillRepository(session)
    v = await repo.rollback(skill_id, version)
    if v is None:
        raise HTTPException(status_code=404, detail="Target version not found")

    audit_repo = AuditRepository(session)
    await audit_repo.append(
        operation="skill_rollback",
        data={"skill_id": skill_id, "rolled_back_to": version},
    )
    return _version_to_dict(v)


@router.get("")
async def search_skills(
    role: str | None = Query(default=None),
    trigger: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    """Search skills by role or trigger."""
    repo = SkillRepository(session)
    versions = await repo.search(role=role, trigger=trigger)
    return [_version_to_dict(v) for v in versions]
