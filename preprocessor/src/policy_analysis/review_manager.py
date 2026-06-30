"""Manage candidate criteria approval workflow.

Provides methods to list, approve, and reject generated testing criteria.
Only criteria with ``status="approved"`` are consumed by agent-eval.
"""

from __future__ import annotations

from typing import Any

import structlog

from common.clients import MemoryClient

logger = structlog.get_logger(__name__)


class ReviewManager:
    """Manages the review lifecycle for generated testing criteria.

    Generated criteria start with ``status="candidate"`` and must be
    explicitly approved before agent-eval will use them. This provides
    a human-in-the-loop checkpoint for AI-generated evaluation criteria.
    """

    def __init__(self, memory: MemoryClient) -> None:
        """Initialize the review manager.

        Args:
            memory: MemoryClient for reading/writing criteria state.
        """
        self._memory = memory

    async def list_pending(self, tenant_id: str) -> list[dict[str, Any]]:
        """List all criteria with status="candidate" for a tenant.

        Retrieves all skill records under the ``criteria/`` namespace
        and filters for those in candidate status.

        Args:
            tenant_id: Tenant identifier.

        Returns:
            List of criteria dicts that are pending approval. Returns
            empty list on memory failure.
        """
        try:
            skills = await self._memory.skill_recall(
                tenant_id=tenant_id,
                skill_name=None,  # Recall all skills
            )
        except Exception as exc:
            logger.warning(
                "review_list_failed",
                tenant_id=tenant_id,
                error=str(exc),
            )
            return []

        pending: list[dict[str, Any]] = []
        for skill in skills:
            skill_name = skill.get("skill_name", "")
            if not skill_name.startswith("criteria/"):
                continue

            skill_data = skill.get("skill_data", skill.get("data", {}))
            status = skill_data.get("status", "")

            if status == "candidate":
                pending.append(skill_data)

        logger.info(
            "review_list_pending",
            tenant_id=tenant_id,
            pending_count=len(pending),
        )
        return pending

    async def approve(
        self,
        tenant_id: str,
        framework: str,
        control_id: str,
    ) -> bool:
        """Approve a candidate criteria set for use by agent-eval.

        Updates the status from "candidate" to "approved". Only approved
        criteria are used during compliance evaluations.

        Args:
            tenant_id: Tenant identifier.
            framework: Framework name (e.g., "SOC2").
            control_id: Control identifier (e.g., "CC6.1").

        Returns:
            True if approved successfully, False on failure.
        """
        skill_name = f"criteria/{framework}/{control_id}"

        # Recall current criteria
        criteria_data = await self._recall_criteria(tenant_id, skill_name)
        if not criteria_data:
            logger.warning(
                "review_approve_not_found",
                tenant_id=tenant_id,
                framework=framework,
                control_id=control_id,
            )
            return False

        current_status = criteria_data.get("status", "")
        if current_status == "approved":
            logger.info(
                "review_already_approved",
                tenant_id=tenant_id,
                framework=framework,
                control_id=control_id,
            )
            return True

        if current_status == "rejected":
            logger.warning(
                "review_approve_rejected_criteria",
                tenant_id=tenant_id,
                framework=framework,
                control_id=control_id,
            )
            return False

        # Update status to approved
        criteria_data["status"] = "approved"

        # Also update status on each individual criterion
        for criterion in criteria_data.get("criteria", []):
            if isinstance(criterion, dict):
                criterion["status"] = "approved"

        success = await self._memory.skill_store(
            tenant_id=tenant_id,
            skill_name=skill_name,
            skill_data=criteria_data,
            metadata={
                "source": "policy_analysis",
                "status": "approved",
                "criteria_count": len(criteria_data.get("criteria", [])),
            },
        )

        if success:
            logger.info(
                "review_approved",
                tenant_id=tenant_id,
                framework=framework,
                control_id=control_id,
            )
        else:
            logger.warning(
                "review_approve_store_failed",
                tenant_id=tenant_id,
                framework=framework,
                control_id=control_id,
            )

        return success

    async def reject(
        self,
        tenant_id: str,
        framework: str,
        control_id: str,
        reason: str,
    ) -> bool:
        """Reject a candidate criteria set.

        Updates the status to "rejected" with a reason. Rejected criteria
        are never used by agent-eval.

        Args:
            tenant_id: Tenant identifier.
            framework: Framework name.
            control_id: Control identifier.
            reason: Human-readable rejection reason.

        Returns:
            True if rejected successfully, False on failure.
        """
        skill_name = f"criteria/{framework}/{control_id}"

        # Recall current criteria
        criteria_data = await self._recall_criteria(tenant_id, skill_name)
        if not criteria_data:
            logger.warning(
                "review_reject_not_found",
                tenant_id=tenant_id,
                framework=framework,
                control_id=control_id,
            )
            return False

        current_status = criteria_data.get("status", "")
        if current_status == "rejected":
            logger.info(
                "review_already_rejected",
                tenant_id=tenant_id,
                framework=framework,
                control_id=control_id,
            )
            return True

        # Update status to rejected with reason
        criteria_data["status"] = "rejected"
        criteria_data["rejection_reason"] = reason

        # Also update status on each individual criterion
        for criterion in criteria_data.get("criteria", []):
            if isinstance(criterion, dict):
                criterion["status"] = "rejected"

        success = await self._memory.skill_store(
            tenant_id=tenant_id,
            skill_name=skill_name,
            skill_data=criteria_data,
            metadata={
                "source": "policy_analysis",
                "status": "rejected",
                "rejection_reason": reason,
                "criteria_count": len(criteria_data.get("criteria", [])),
            },
        )

        if success:
            logger.info(
                "review_rejected",
                tenant_id=tenant_id,
                framework=framework,
                control_id=control_id,
                reason=reason,
            )
        else:
            logger.warning(
                "review_reject_store_failed",
                tenant_id=tenant_id,
                framework=framework,
                control_id=control_id,
            )

        return success

    async def _recall_criteria(
        self, tenant_id: str, skill_name: str
    ) -> dict[str, Any]:
        """Recall a specific criteria set from memory.

        Args:
            tenant_id: Tenant identifier.
            skill_name: Full skill name path (e.g., "criteria/SOC2/CC6.1").

        Returns:
            Criteria data dict, or empty dict if not found.
        """
        try:
            results = await self._memory.skill_recall(
                tenant_id=tenant_id,
                skill_name=skill_name,
            )
        except Exception as exc:
            logger.warning(
                "review_recall_failed",
                tenant_id=tenant_id,
                skill_name=skill_name,
                error=str(exc),
            )
            return {}

        if not results:
            return {}

        # skill_recall returns a list; take the first match
        first = results[0] if results else {}
        return first.get("skill_data", first.get("data", first))
