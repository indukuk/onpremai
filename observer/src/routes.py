"""Admin API routes for the observer service.

Provides endpoints for:
- GET /observer/status — current autonomy level, last run times, circuit breaker state
- GET /observer/changes — history of applied changes with outcomes
- GET /observer/governance/latest — latest governance report
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

import structlog

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/observer", tags=["observer"])


class ObserverStatusResponse(BaseModel):
    """Response model for /observer/status endpoint."""

    service_name: str
    service_version: str
    autonomy_level: str
    autonomy_details: dict[str, Any]
    circuit_breaker: dict[str, Any]
    scheduler_running: bool
    last_run_times: dict[str, str]
    job_status: list[dict[str, Any]]


class ChangeHistoryResponse(BaseModel):
    """Response model for /observer/changes endpoint."""

    total_changes: int
    changes: list[dict[str, Any]]


class GovernanceReportResponse(BaseModel):
    """Response model for /observer/governance/latest endpoint."""

    report: dict[str, Any]


def _get_app_state(request: Request) -> dict[str, Any]:
    """Extract application state from the request.

    The FastAPI app stores component references in app.state during lifespan.
    """
    state = request.app.state
    return {
        "settings": state.settings,
        "scheduler": state.scheduler,
        "circuit_breaker": state.circuit_breaker,
        "self_regulator": state.self_regulator,
        "change_applier": state.change_applier,
        "report_generator": state.report_generator,
    }


@router.get("/status", response_model=ObserverStatusResponse)
async def get_status(request: Request) -> ObserverStatusResponse:
    """Get current observer status including autonomy and circuit breaker state."""
    app_state = _get_app_state(request)
    settings = app_state["settings"]
    scheduler = app_state["scheduler"]
    circuit_breaker = app_state["circuit_breaker"]
    self_regulator = app_state["self_regulator"]

    cb_status = circuit_breaker.get_status()

    return ObserverStatusResponse(
        service_name=settings.service_name,
        service_version=settings.service_version,
        autonomy_level=self_regulator.autonomy.level,
        autonomy_details=self_regulator.get_status(),
        circuit_breaker={
            "state": cb_status.state.value,
            "rollback_count_in_window": cb_status.rollback_count_in_window,
            "max_rollbacks": cb_status.max_rollbacks,
            "window_hours": cb_status.window_hours,
            "cooldown_hours": cb_status.cooldown_hours,
            "tripped_at": cb_status.tripped_at,
            "cooldown_ends_at": cb_status.cooldown_ends_at,
        },
        scheduler_running=scheduler.is_running,
        last_run_times=scheduler.last_run_times,
        job_status=scheduler.get_job_status(),
    )


@router.get("/changes", response_model=ChangeHistoryResponse)
async def get_changes(request: Request) -> ChangeHistoryResponse:
    """Get history of applied changes with their outcomes."""
    app_state = _get_app_state(request)
    change_applier = app_state["change_applier"]

    # Get pending validations and human queue
    pending = change_applier.get_pending_validations()
    human_queue = change_applier.get_human_queue()

    changes: list[dict[str, Any]] = []

    # Add pending validations
    for validation in pending:
        changes.append({
            "change_id": validation["change_id"],
            "status": "pending_validation",
            "scheduled_at": validation.get("scheduled_at", ""),
        })

    # Add human queue items
    for change in human_queue:
        changes.append({
            "change_id": change.id,
            "change_type": change.change_type.value,
            "apply_tier": change.apply_tier.value,
            "status": change.status.value,
            "task": change.task,
            "model": change.model,
            "description": change.description,
            "confidence": change.confidence,
            "proposed_at": change.proposed_at,
        })

    # Add self-regulator change history
    self_regulator = app_state["self_regulator"]
    for recorded_change in self_regulator._change_history[-50:]:
        changes.append({
            "change_id": recorded_change.id,
            "change_type": recorded_change.change_type.value,
            "apply_tier": recorded_change.apply_tier.value,
            "status": recorded_change.status.value,
            "task": recorded_change.task,
            "model": recorded_change.model,
            "description": recorded_change.description,
            "confidence": recorded_change.confidence,
            "proposed_at": recorded_change.proposed_at,
            "applied_at": recorded_change.applied_at,
            "validated_at": recorded_change.validated_at,
            "rolled_back_at": recorded_change.rolled_back_at,
        })

    return ChangeHistoryResponse(
        total_changes=len(changes),
        changes=changes,
    )


@router.get("/governance/latest", response_model=GovernanceReportResponse)
async def get_latest_governance_report(request: Request) -> GovernanceReportResponse:
    """Get the latest governance report (model inventory + drift + bias)."""
    app_state = _get_app_state(request)
    report_generator = app_state["report_generator"]

    report_data = report_generator.get_latest_serialized()

    return GovernanceReportResponse(report=report_data)


@router.post("/circuit-breaker/reset")
async def reset_circuit_breaker(request: Request) -> dict[str, str]:
    """Manually reset the circuit breaker (admin action)."""
    app_state = _get_app_state(request)
    circuit_breaker = app_state["circuit_breaker"]

    result = circuit_breaker.reset()
    logger.info("circuit_breaker_reset_via_api")
    return result


@router.post("/trigger/{job_id}")
async def trigger_job(request: Request, job_id: str) -> dict[str, Any]:
    """Manually trigger a scheduled job to run immediately."""
    app_state = _get_app_state(request)
    scheduler = app_state["scheduler"]

    valid_jobs = ["quality_check", "prompt_optimization", "model_fit", "self_eval"]
    if job_id not in valid_jobs:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid job_id. Must be one of: {valid_jobs}",
        )

    success = scheduler.trigger_job(job_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

    return {"status": "triggered", "job_id": job_id}


@router.get("/self-eval/history")
async def get_self_eval_history(request: Request) -> dict[str, Any]:
    """Get self-evaluation history."""
    app_state = _get_app_state(request)
    self_regulator = app_state["self_regulator"]

    return {
        "current_autonomy": self_regulator.get_status(),
        "evaluations": self_regulator.get_eval_history(),
    }
