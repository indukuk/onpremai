"""FastAPI application for agent-eval service.

Endpoints:
- POST /evaluate: Start async compliance evaluation, returns job_id
- GET /status/{job_id}: Poll for evaluation result
- POST /chat: Synchronous compliance chat
- GET /health: Container liveness
- GET /ready: Readiness (RAG loaded)
"""

from __future__ import annotations

import asyncio
import signal
import uuid
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import structlog
import uvicorn
from fastapi import Depends, FastAPI, HTTPException

from common.auth.service_auth import verify_service
from common.clients import MemoryClient, StateClient, StorageClient
from common.errors import StorageError

from src.config import EvalSettings, get_settings
from src.graph.graph import build_eval_graph
from src.graph.state import EvalGraphState
from src.health import router as health_router
from src.health import set_rag_ready
from src.jobs import JobManager
from src.models import (
    ChatRequest,
    ChatResponse,
    ComplianceStatus,
    EvalRequest,
    EvalResult,
    EvalStartResponse,
    JobStatus,
    JobStatusEnum,
    TimingStats,
)
from src.rag.index import initialize_rag_index

logger = structlog.get_logger(__name__)

# Module-level references
_job_manager: JobManager | None = None
_eval_graph: object | None = None
_settings: EvalSettings | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: startup and shutdown logic."""
    global _job_manager, _eval_graph, _settings

    _settings = get_settings()

    # Initialize state client and job manager
    state_client = StateClient()
    _job_manager = JobManager(
        state_client=state_client,
        max_concurrent=_settings.max_concurrent_evaluations,
    )

    # Build the evaluation graph
    _eval_graph = build_eval_graph()
    logger.info("eval_graph_compiled")

    # Load RAG index
    try:
        await initialize_rag_index(_settings.rag_index_path)
        set_rag_ready(True)
        logger.info("rag_index_ready")
    except Exception as exc:
        logger.warning("rag_index_load_failed", error=str(exc))
        # Service can start without RAG (uses default criteria)
        set_rag_ready(True)

    logger.info(
        "agent_eval_started",
        max_concurrent=_settings.max_concurrent_evaluations,
        max_timeout_sec=_settings.max_eval_timeout_sec,
    )

    yield

    # Shutdown: wait for active evaluations to finish
    if _job_manager is not None:
        await _job_manager.shutdown(timeout=30.0)
    logger.info("agent_eval_shutdown")


app = FastAPI(
    title="agent-eval",
    description="3-layer compliance evaluation pipeline",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(health_router)


@app.post("/evaluate", response_model=EvalStartResponse)
async def evaluate(
    request: EvalRequest,
    service_id: str = Depends(verify_service),
) -> EvalStartResponse:
    """Start an async compliance evaluation.

    Creates a background job that runs the 3-layer evaluation pipeline
    (rules -> LLM judgment -> scoring) and returns immediately with a
    job_id for polling.
    """
    if _job_manager is None:
        raise HTTPException(status_code=503, detail="Service not ready")

    trace_id = request.trace_id or str(uuid.uuid4())

    async def run_evaluation(job_id: str) -> EvalResult:
        """Execute the evaluation graph as a background task."""
        return await _execute_evaluation(
            control_id=request.control_id,
            framework=request.framework,
            tenant_id=request.tenant_id,
            bypass_cache=request.bypass_cache,
            trace_id=trace_id,
        )

    job_id = await _job_manager.start_job(
        coro_factory=run_evaluation,
        tenant_id=request.tenant_id,
        control_id=request.control_id,
        framework=request.framework,
    )

    logger.info(
        "evaluation_started",
        job_id=job_id,
        control_id=request.control_id,
        framework=request.framework,
        tenant_id=request.tenant_id,
        trace_id=trace_id,
    )

    return EvalStartResponse(job_id=job_id, status=JobStatusEnum.PROCESSING)


@app.get("/status/{job_id}", response_model=JobStatus)
async def get_status(job_id: str) -> JobStatus:
    """Poll for evaluation job status and results."""
    if _job_manager is None:
        raise HTTPException(status_code=503, detail="Service not ready")

    status = await _job_manager.get_status(job_id)
    return status


@app.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    service_id: str = Depends(verify_service),
) -> ChatResponse:
    """Synchronous compliance chat endpoint.

    For general compliance questions that do not require full evaluation.
    Routes through the graph's chat path (router -> formatter).
    """
    from common.clients import LLMClient

    session_id = request.session_id or str(uuid.uuid4())
    trace_id = str(uuid.uuid4())

    llm = LLMClient()
    memory = MemoryClient()

    try:
        # Get tenant context for better responses
        tenant_context = await memory.tenant_recall(
            tenant_id=request.tenant_id,
            query=request.message,
            top_k=3,
        )

        context_text = ""
        if tenant_context:
            context_text = "\n".join(
                item.get("fact", str(item)) for item in tenant_context[:3]
            )

        system_prompt = (
            "You are a compliance assistant. Answer questions about regulatory compliance, "
            "controls, frameworks, and evidence requirements. Be specific and actionable.\n"
        )
        if context_text:
            system_prompt += f"\nTenant context:\n{context_text}"

        response = await llm.complete(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": request.message},
            ],
            task="chat_response",
            tenant_id=request.tenant_id,
            trace_id=trace_id,
            temperature=0.3,
            max_tokens=1000,
        )

        return ChatResponse(
            response=response.content,
            session_id=session_id,
            sources=[],
        )

    except Exception as exc:
        logger.warning("chat_error", error=str(exc), trace_id=trace_id)
        return ChatResponse(
            response="I apologize, but I am unable to process your question at this time. Please try again later.",
            session_id=session_id,
            sources=[],
        )
    finally:
        await llm.close()
        await memory.close()


async def _execute_evaluation(
    control_id: str,
    framework: str,
    tenant_id: str,
    bypass_cache: bool,
    trace_id: str,
) -> EvalResult:
    """Execute the full evaluation graph and return the result.

    This runs as a background task within the job manager.
    """
    if _eval_graph is None:
        raise RuntimeError("Evaluation graph not initialized")

    settings = get_settings()

    # Build initial state
    initial_state: EvalGraphState = {
        "control_id": control_id,
        "framework": framework,
        "tenant_id": tenant_id,
        "trace_id": trace_id,
        "bypass_cache": bypass_cache,
        "intent": "evaluate",
        "evidence_files": [],
        "evidence_hash": "",
        "evidence_metadata": [],
        "testing_criteria": None,
        "rule_results": {},
        "needs_judgment": [],
        "judgment_results": {},
        "final_score": 0.0,
        "final_status": ComplianceStatus.INSUFFICIENT_EVIDENCE,
        "sandbox_code": "",
        "sandbox_output": "",
        "sandbox_retries": 0,
        "evaluation_result": None,
        "error": None,
        "partial_evaluation": False,
        "chat_message": "",
        "chat_response": "",
        "timing": TimingStats(),
        "layer_stats": None,
        "tenant_context": [],
        "patterns": [],
        "cached_result": None,
    }

    # Execute graph with timeout
    try:
        result_state = await asyncio.wait_for(
            _eval_graph.ainvoke(initial_state),
            timeout=settings.max_eval_timeout_sec,
        )
    except asyncio.TimeoutError:
        logger.error(
            "evaluation_timeout",
            control_id=control_id,
            framework=framework,
            tenant_id=tenant_id,
            trace_id=trace_id,
            timeout_sec=settings.max_eval_timeout_sec,
        )
        return EvalResult(
            control_id=control_id,
            framework=framework,
            tenant_id=tenant_id,
            status=ComplianceStatus.INSUFFICIENT_EVIDENCE,
            metadata={"error": f"Evaluation timed out after {settings.max_eval_timeout_sec}s"},
        )

    # Extract result from final state
    eval_result = result_state.get("evaluation_result")
    if eval_result is not None:
        return eval_result

    # Fallback: construct result from state
    return EvalResult(
        control_id=control_id,
        framework=framework,
        tenant_id=tenant_id,
        score=result_state.get("final_score", 0.0),
        status=result_state.get("final_status", ComplianceStatus.INSUFFICIENT_EVIDENCE),
        evidence_hash=result_state.get("evidence_hash", ""),
        metadata={"error": result_state.get("error", "Unknown error")},
    )


def main() -> None:
    """Run the agent-eval service."""
    settings = get_settings()
    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=8080,
        log_level=settings.log_level,
        workers=1,  # Single worker to manage graph state
    )


if __name__ == "__main__":
    main()
