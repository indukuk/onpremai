"""FastAPI application for the observer service.

Orchestrates all observer components with lifespan management:
- Starts APScheduler on startup
- Includes admin routes, health/ready endpoints
- S2S auth on all endpoints (observer is internal-only)
- Graceful shutdown of scheduler and HTTP clients
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from common.auth.service_auth import ServiceAuthenticator

from observer.src.changes.applier import ChangeApplier
from observer.src.changes.proposal import ChangeProposer
from observer.src.changes.rollback import RollbackEngine
from observer.src.changes.validator import ChangeValidator
from observer.src.circuit_breaker import CircuitBreaker
from observer.src.config import ObserverSettings, get_settings
from observer.src.detection.aggregator import MetricAggregator
from observer.src.detection.detector import IssueDetector
from observer.src.detection.log_ingestor import LogIngestor
from observer.src.diagnosis.engine import DiagnosisEngine
from observer.src.governance.bias import BiasDetector
from observer.src.governance.drift import DriftDetector
from observer.src.governance.inventory import ModelInventoryManager
from observer.src.governance.reports import GovernanceReportGenerator
from observer.src.health import health_router
from observer.src.routes import router as observer_router
from observer.src.scheduler import ObserverScheduler
from observer.src.self_regulation import SelfRegulator

logger = structlog.get_logger(__name__)


class S2SAuthMiddleware(BaseHTTPMiddleware):
    """Service-to-service authentication middleware.

    The observer is internal-only. All requests must include valid
    X-Service-Id and X-Service-Key headers validated by ServiceAuthenticator.
    Health/ready endpoints are exempt.
    """

    EXEMPT_PATHS: set[str] = {"/health", "/ready", "/docs", "/openapi.json"}

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        """Validate S2S credentials on non-exempt paths."""
        if request.url.path in self.EXEMPT_PATHS:
            return await call_next(request)

        # Extract service credentials from headers
        service_id = request.headers.get("X-Service-Id", "")
        service_key = request.headers.get("X-Service-Key", "")

        if not service_id or not service_key:
            logger.warning(
                "s2s_auth_missing",
                path=request.url.path,
                method=request.method,
            )
            return Response(
                content='{"detail": "Missing service authentication"}',
                status_code=401,
                media_type="application/json",
            )

        # Validate credentials using ServiceAuthenticator from app state
        authenticator: ServiceAuthenticator = request.app.state.service_authenticator
        if not authenticator.validate(service_id=service_id, service_key=service_key):
            logger.warning(
                "s2s_auth_invalid",
                path=request.url.path,
                method=request.method,
                service_id=service_id,
            )
            return Response(
                content='{"detail": "Invalid service credentials"}',
                status_code=401,
                media_type="application/json",
            )

        return await call_next(request)


async def _run_quality_check(
    ingestor: LogIngestor,
    aggregator: MetricAggregator,
    detector: IssueDetector,
    diagnosis_engine: DiagnosisEngine,
    proposer: ChangeProposer,
    applier: ChangeApplier,
    circuit_breaker: CircuitBreaker,
    self_regulator: SelfRegulator,
) -> None:
    """Hourly quality check — detect and resolve issues in gateway metrics."""
    entries = await ingestor.ingest(since_minutes=60)
    if not entries:
        logger.info("quality_check_no_entries")
        return

    metrics = aggregator.aggregate(entries, window_minutes=60)
    issues = detector.detect(metrics)

    if not issues:
        logger.info("quality_check_no_issues")
        return

    diagnoses = await diagnosis_engine.diagnose_batch(issues)

    for diagnosis, issue in zip(diagnoses, issues):
        change = proposer.propose(diagnosis, issue)
        if change:
            applied_change = await applier.apply(change, circuit_breaker_open=circuit_breaker.is_open)
            self_regulator.record_change(applied_change)


async def _run_prompt_optimization(
    ingestor: LogIngestor,
    aggregator: MetricAggregator,
    diagnosis_engine: DiagnosisEngine,
) -> None:
    """6-hourly prompt optimization — analyze prompt patterns for improvements."""
    entries = await ingestor.ingest(since_minutes=360)
    if not entries:
        return

    metrics = aggregator.aggregate(entries, window_minutes=360)

    # Identify tasks with high escalation or low confidence that may benefit from prompt tuning
    for task, task_metrics in metrics.by_task.items():
        if task_metrics.sample_count < 20:
            continue
        if task_metrics.escalation_rate > 0.30 or task_metrics.avg_confidence < 0.75:
            logger.info(
                "prompt_optimization_candidate",
                task=task,
                escalation_rate=round(task_metrics.escalation_rate, 3),
                avg_confidence=round(task_metrics.avg_confidence, 3),
            )


async def _run_model_fit(
    ingestor: LogIngestor,
    inventory_manager: ModelInventoryManager,
    drift_detector: DriftDetector,
    bias_detector: BiasDetector,
    aggregator: MetricAggregator,
    report_generator: GovernanceReportGenerator,
    settings: ObserverSettings,
) -> None:
    """Daily model fit — drift detection, bias checks, inventory refresh."""
    # Refresh model inventory
    await inventory_manager.refresh()

    # Ingest data for drift detection
    drift_window_minutes = settings.drift_detection_window_days * 24 * 60
    entries = await ingestor.ingest(since_minutes=drift_window_minutes)

    if entries:
        # Split entries into baseline (first half) and current (second half)
        midpoint = len(entries) // 2
        baseline_entries = entries[:midpoint]
        current_entries = entries[midpoint:]

        drift_detector.ingest_baseline(baseline_entries)
        drift_detector.ingest_current(current_entries)
        drift_detector.detect()

        # Bias detection
        metrics = aggregator.aggregate(entries, window_minutes=drift_window_minutes)
        bias_detector.analyze(metrics.by_tenant)

    # Generate weekly report if enabled
    if settings.governance_report_weekly:
        await report_generator.generate_weekly()


async def _run_self_eval(self_regulator: SelfRegulator) -> None:
    """Weekly self-evaluation — assess success rate and adjust autonomy."""
    await self_regulator.evaluate()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan — start and stop all components."""
    settings = get_settings()

    # Initialize components
    log_ingestor = LogIngestor(settings)
    aggregator = MetricAggregator()
    detector = IssueDetector(settings, aggregator)
    diagnosis_engine = DiagnosisEngine(settings)
    proposer = ChangeProposer(settings)
    applier = ChangeApplier(settings)
    rollback_engine = RollbackEngine(settings)
    validator = ChangeValidator(settings)
    circuit_breaker = CircuitBreaker(settings)
    self_regulator = SelfRegulator(settings)
    inventory_manager = ModelInventoryManager(settings)
    drift_detector = DriftDetector(settings)
    bias_detector = BiasDetector(settings)
    report_generator = GovernanceReportGenerator(
        settings, inventory_manager, drift_detector, bias_detector
    )
    scheduler = ObserverScheduler(settings)

    # Start all async components
    await log_ingestor.start()
    await diagnosis_engine.start()
    await applier.start()
    await rollback_engine.start()
    await validator.start()
    await self_regulator.start()
    await inventory_manager.start()
    await report_generator.start()

    # Configure scheduler with bound closures
    async def quality_check() -> None:
        await _run_quality_check(
            ingestor=log_ingestor,
            aggregator=aggregator,
            detector=detector,
            diagnosis_engine=diagnosis_engine,
            proposer=proposer,
            applier=applier,
            circuit_breaker=circuit_breaker,
            self_regulator=self_regulator,
        )

    async def prompt_optimization() -> None:
        await _run_prompt_optimization(
            ingestor=log_ingestor,
            aggregator=aggregator,
            diagnosis_engine=diagnosis_engine,
        )

    async def model_fit() -> None:
        await _run_model_fit(
            ingestor=log_ingestor,
            inventory_manager=inventory_manager,
            drift_detector=drift_detector,
            bias_detector=bias_detector,
            aggregator=aggregator,
            report_generator=report_generator,
            settings=settings,
        )

    async def self_eval() -> None:
        await _run_self_eval(self_regulator=self_regulator)

    scheduler.configure(
        quality_check_fn=quality_check,
        prompt_optimization_fn=prompt_optimization,
        model_fit_fn=model_fit,
        self_eval_fn=self_eval,
    )
    scheduler.start()

    # Initialize S2S authenticator for middleware
    app.state.service_authenticator = ServiceAuthenticator(settings)

    # Store state for route handlers
    app.state.settings = settings
    app.state.scheduler = scheduler
    app.state.circuit_breaker = circuit_breaker
    app.state.self_regulator = self_regulator
    app.state.change_applier = applier
    app.state.report_generator = report_generator
    app.state.rollback_engine = rollback_engine
    app.state.validator = validator
    app.state.log_ingestor = log_ingestor
    app.state.aggregator = aggregator
    app.state.detector = detector
    app.state.diagnosis_engine = diagnosis_engine
    app.state.proposer = proposer
    app.state.inventory_manager = inventory_manager
    app.state.drift_detector = drift_detector
    app.state.bias_detector = bias_detector

    logger.info(
        "observer_started",
        port=settings.port,
        auto_apply_enabled=settings.auto_apply_enabled,
        governance_enabled=settings.model_governance_enabled,
    )

    yield

    # Graceful shutdown
    logger.info("observer_shutting_down")
    scheduler.stop()

    await log_ingestor.close()
    await diagnosis_engine.close()
    await applier.close()
    await rollback_engine.close()
    await validator.close()
    await self_regulator.close()
    await inventory_manager.close()
    await report_generator.close()

    logger.info("observer_shutdown_complete")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title="Observer Service",
        description="Autonomous self-tuning AI agent for LLM gateway optimization",
        version=settings.service_version,
        lifespan=lifespan,
    )

    # Add S2S auth middleware
    app.add_middleware(S2SAuthMiddleware)

    # Add CORS for internal admin tools
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include routers
    app.include_router(health_router)
    app.include_router(observer_router)

    return app


# Application instance
app = create_app()
