"""Governance report generation — weekly and monthly structured reports.

Combines model inventory, drift detection, and bias analysis into
comprehensive governance reports for audit and oversight.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx
import structlog

from observer.src.config import ObserverSettings
from observer.src.governance.bias import BiasDetector, BiasReport
from observer.src.governance.drift import DriftDetector, DriftReport
from observer.src.governance.inventory import ModelInventory, ModelInventoryManager

logger = structlog.get_logger(__name__)


@dataclass
class GovernanceReport:
    """Complete governance report combining all governance checks."""

    report_id: str = ""
    report_type: str = "weekly"  # "weekly" or "monthly"
    generated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    period_start: str = ""
    period_end: str = ""

    # Model inventory section
    inventory_summary: dict[str, Any] = field(default_factory=dict)

    # Drift detection section
    drift_summary: dict[str, Any] = field(default_factory=dict)

    # Bias detection section
    bias_summary: dict[str, Any] = field(default_factory=dict)

    # Overall risk assessment
    overall_risk_level: str = "low"  # "low", "medium", "high", "critical"
    risk_factors: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)

    # Metadata
    models_total: int = 0
    models_drifted: int = 0
    tenants_biased: int = 0
    config_changes_detected: bool = False


class GovernanceReportGenerator:
    """Generates periodic governance reports.

    Orchestrates model inventory, drift detection, and bias analysis
    to produce structured reports for compliance and oversight.
    """

    def __init__(
        self,
        settings: ObserverSettings,
        inventory_manager: ModelInventoryManager,
        drift_detector: DriftDetector,
        bias_detector: BiasDetector,
    ) -> None:
        self._settings = settings
        self._inventory_manager = inventory_manager
        self._drift_detector = drift_detector
        self._bias_detector = bias_detector
        self._reports: list[GovernanceReport] = []
        self._memory_client: httpx.AsyncClient | None = None

    async def start(self) -> None:
        """Initialize the memory service client for report storage."""
        self._memory_client = httpx.AsyncClient(
            base_url=self._settings.memory_url,
            timeout=httpx.Timeout(30.0),
        )

    async def close(self) -> None:
        """Shutdown the memory service client."""
        if self._memory_client:
            await self._memory_client.aclose()
            self._memory_client = None

    async def generate_weekly(self) -> GovernanceReport:
        """Generate a weekly governance report.

        Returns:
            Complete GovernanceReport for the past week.
        """
        from uuid import uuid4

        now = datetime.now(timezone.utc)
        from datetime import timedelta

        period_start = (now - timedelta(days=7)).isoformat()
        period_end = now.isoformat()

        report = GovernanceReport(
            report_id=f"gov_weekly_{uuid4().hex[:8]}",
            report_type="weekly",
            period_start=period_start,
            period_end=period_end,
        )

        # Populate sections
        report.inventory_summary = self._build_inventory_summary()
        report.drift_summary = self._build_drift_summary()
        report.bias_summary = self._build_bias_summary()

        # Compute overall risk
        report = self._assess_risk(report)

        # Store the report
        self._reports.append(report)
        if len(self._reports) > 52:  # Keep ~1 year of weekly reports
            self._reports = self._reports[-52:]

        # Persist to memory service
        await self._persist_report(report)

        logger.info(
            "governance_weekly_report_generated",
            report_id=report.report_id,
            risk_level=report.overall_risk_level,
            models_drifted=report.models_drifted,
            tenants_biased=report.tenants_biased,
        )

        return report

    async def generate_monthly(self) -> GovernanceReport:
        """Generate a monthly governance report with trend analysis.

        Returns:
            Complete GovernanceReport for the past month.
        """
        from uuid import uuid4

        now = datetime.now(timezone.utc)
        from datetime import timedelta

        period_start = (now - timedelta(days=30)).isoformat()
        period_end = now.isoformat()

        report = GovernanceReport(
            report_id=f"gov_monthly_{uuid4().hex[:8]}",
            report_type="monthly",
            period_start=period_start,
            period_end=period_end,
        )

        # Populate sections with extended data
        report.inventory_summary = self._build_inventory_summary(include_history=True)
        report.drift_summary = self._build_drift_summary()
        report.bias_summary = self._build_bias_summary()

        # Add trend data from weekly reports
        weekly_reports = [r for r in self._reports if r.report_type == "weekly"]
        recent_weekly = weekly_reports[-4:] if len(weekly_reports) >= 4 else weekly_reports
        if recent_weekly:
            report.inventory_summary["trend"] = {
                "weeks_analyzed": len(recent_weekly),
                "drift_trend": [r.models_drifted for r in recent_weekly],
                "bias_trend": [r.tenants_biased for r in recent_weekly],
                "risk_trend": [r.overall_risk_level for r in recent_weekly],
            }

        # Compute overall risk
        report = self._assess_risk(report)

        # Store the report
        self._reports.append(report)

        # Persist to memory service
        await self._persist_report(report)

        logger.info(
            "governance_monthly_report_generated",
            report_id=report.report_id,
            risk_level=report.overall_risk_level,
        )

        return report

    def _build_inventory_summary(self, include_history: bool = False) -> dict[str, Any]:
        """Build the model inventory section of the report."""
        inventory = self._inventory_manager.current
        summary: dict[str, Any] = {
            "total_models": inventory.total_models,
            "active_models": inventory.active_models,
            "degraded_models": inventory.degraded_models,
            "inactive_models": inventory.inactive_models,
            "last_refreshed": inventory.last_refreshed,
            "routing_config_hash": inventory.routing_config_hash,
        }

        # Add per-model details
        model_details: list[dict[str, Any]] = []
        for model_id, record in inventory.models.items():
            model_details.append({
                "model_id": model_id,
                "provider": record.provider,
                "tier": record.tier,
                "status": record.status,
                "tasks": record.tasks,
                "error_rate": round(record.error_rate, 4),
                "avg_latency_ms": round(record.avg_latency_ms, 1),
                "requests_24h": record.total_requests_24h,
            })
        summary["models"] = model_details

        if include_history:
            history = self._inventory_manager.history
            summary["history_snapshots"] = len(history)
            if history:
                summary["first_snapshot"] = history[0].last_refreshed
                summary["latest_snapshot"] = history[-1].last_refreshed

        return summary

    def _build_drift_summary(self) -> dict[str, Any]:
        """Build the drift detection section of the report."""
        return self._drift_detector.to_dict()

    def _build_bias_summary(self) -> dict[str, Any]:
        """Build the bias detection section of the report."""
        return self._bias_detector.to_dict()

    def _assess_risk(self, report: GovernanceReport) -> GovernanceReport:
        """Compute overall risk level based on all governance signals."""
        risk_factors: list[str] = []
        recommendations: list[str] = []
        risk_score = 0

        # Check drift
        drift_report = self._drift_detector.last_report
        if drift_report and drift_report.drifted_entities > 0:
            report.models_drifted = drift_report.drifted_entities
            risk_score += drift_report.drifted_entities * 2
            risk_factors.append(
                f"{drift_report.drifted_entities} entities show statistical drift"
            )
            recommendations.append(
                "Investigate drifted models/tasks for underlying changes in input distribution or model updates"
            )

        # Check bias
        bias_report = self._bias_detector.last_report
        if bias_report and bias_report.outlier_count > 0:
            report.tenants_biased = bias_report.outlier_count
            risk_score += bias_report.outlier_count * 3
            risk_factors.append(
                f"{bias_report.outlier_count} tenants show bias indicators"
            )
            underperforming = self._bias_detector.get_underperforming_tenants()
            if underperforming:
                tenant_ids = [r.tenant_id for r in underperforming[:5]]
                recommendations.append(
                    f"Review routing configuration for underperforming tenants: {', '.join(tenant_ids)}"
                )

        # Check inventory health
        inventory = self._inventory_manager.current
        if inventory.degraded_models > 0:
            risk_score += inventory.degraded_models * 2
            risk_factors.append(
                f"{inventory.degraded_models} models in degraded state"
            )
            degraded = self._inventory_manager.get_degraded_models()
            if degraded:
                model_ids = [m.model_id for m in degraded[:5]]
                recommendations.append(
                    f"Investigate degraded models: {', '.join(model_ids)}"
                )

        report.models_total = inventory.total_models

        # Determine risk level
        if risk_score >= 10:
            report.overall_risk_level = "critical"
        elif risk_score >= 6:
            report.overall_risk_level = "high"
        elif risk_score >= 3:
            report.overall_risk_level = "medium"
        else:
            report.overall_risk_level = "low"

        report.risk_factors = risk_factors
        report.recommendations = recommendations

        return report

    async def _persist_report(self, report: GovernanceReport) -> None:
        """Store the report in memory service for retrieval."""
        if not self._memory_client:
            return

        payload = {
            "type": "governance_report",
            "report_id": report.report_id,
            "report_type": report.report_type,
            "data": self._serialize_report(report),
        }

        try:
            response = await self._memory_client.post(
                "/patterns",
                json=payload,
            )
            if response.status_code not in (200, 201):
                logger.warning(
                    "governance_report_persist_failed",
                    report_id=report.report_id,
                    status=response.status_code,
                )
        except httpx.HTTPError as exc:
            logger.warning(
                "governance_report_persist_error",
                report_id=report.report_id,
                error=str(exc),
            )

    @property
    def latest_report(self) -> GovernanceReport | None:
        """Get the most recent governance report."""
        return self._reports[-1] if self._reports else None

    @property
    def all_reports(self) -> list[GovernanceReport]:
        """Get all stored reports."""
        return list(self._reports)

    def _serialize_report(self, report: GovernanceReport) -> dict[str, Any]:
        """Serialize a GovernanceReport to a plain dict."""
        return {
            "report_id": report.report_id,
            "report_type": report.report_type,
            "generated_at": report.generated_at,
            "period_start": report.period_start,
            "period_end": report.period_end,
            "inventory_summary": report.inventory_summary,
            "drift_summary": report.drift_summary,
            "bias_summary": report.bias_summary,
            "overall_risk_level": report.overall_risk_level,
            "risk_factors": report.risk_factors,
            "recommendations": report.recommendations,
            "models_total": report.models_total,
            "models_drifted": report.models_drifted,
            "tenants_biased": report.tenants_biased,
            "config_changes_detected": report.config_changes_detected,
        }

    def get_latest_serialized(self) -> dict[str, Any]:
        """Get the latest report serialized for API response."""
        report = self.latest_report
        if not report:
            return {"status": "no_reports_generated"}
        return self._serialize_report(report)
