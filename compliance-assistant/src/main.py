"""FastAPI application for the compliance-assistant service.

Endpoints:
- POST /chat     - Send message, get response (may include tool results)
- POST /init     - Initialize session (greeting, skill selection)
- POST /confirm  - Approve pending destructive action
- POST /cancel   - Reject pending action
- GET  /health   - Liveness check
- GET  /ready    - Readiness check (true when tool registry loaded)
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import structlog
import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from common.auth.cognito import UserContext
from common.auth.rbac import get_current_user
from common.clients import LLMClient, MemoryClient
from common.logging.logger import configure_logging
from src.agent.context_builder import ContextBuilder
from src.agent.event_queue import EventQueueHandler
from src.agent.loop import AgentLoop
from src.agent.reflection import SessionReflector
from src.agent.user_state import UserStateManager
from src.config import settings
from src.health import mark_tools_loaded, router as health_router
from src.mcp.client import MCPClient
from src.mcp.confirmation import ConfirmationHandler
from src.models import (
    CancelRequest,
    ChatRequest,
    ChatResponse,
    ConfirmRequest,
    InitRequest,
)
from src.session import SessionManager
from src.skills.loader import SkillLoader
from src.skills.matcher import SkillMatcher
from src.skills.playbook_engine import PlaybookEngine

logger = structlog.get_logger(__name__)

# Global service instances (initialized in lifespan)
_llm: LLMClient | None = None
_memory: MemoryClient | None = None
_mcp: MCPClient | None = None
_sessions: SessionManager | None = None
_agent_loop: AgentLoop | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: initialize and cleanup service dependencies."""
    global _llm, _memory, _mcp, _sessions, _agent_loop  # noqa: PLW0603

    configure_logging(
        service_name=settings.service_name,
        log_level=settings.log_level.upper(),
        json_output=settings.log_format == "json",
        pii_hmac_key=settings.pii_hmac_key,
    )

    logger.info(
        "compliance_assistant_starting",
        version=settings.chat_version,
        mcp_url=settings.mcp_server_url,
        gateway_url=settings.llm_gateway_url,
        memory_url=settings.memory_url,
    )

    # Initialize clients
    _llm = LLMClient(gateway_url=settings.llm_gateway_url)
    _memory = MemoryClient(memory_url=settings.memory_url)
    _mcp = MCPClient(mcp_url=settings.mcp_server_url, timeout=settings.tool_timeout_sec)
    _sessions = SessionManager(memory=_memory)

    # Initialize skill/playbook systems
    skill_loader = SkillLoader(memory=_memory)
    skill_matcher = SkillMatcher()
    playbook_engine = PlaybookEngine(memory=_memory)
    context_builder = ContextBuilder(memory=_memory, mcp=_mcp)
    confirmation_handler = ConfirmationHandler(mcp=_mcp)

    # V2: Shadow agent persistent intelligence
    reflector = SessionReflector(llm=_llm, memory=_memory)
    user_state_mgr = UserStateManager(memory=_memory)
    event_handler = EventQueueHandler(memory=_memory)

    _agent_loop = AgentLoop(
        llm=_llm,
        memory=_memory,
        mcp=_mcp,
        sessions=_sessions,
        context_builder=context_builder,
        skill_loader=skill_loader,
        skill_matcher=skill_matcher,
        playbook_engine=playbook_engine,
        confirmation_handler=confirmation_handler,
        reflector=reflector,
        user_state_mgr=user_state_mgr,
        event_handler=event_handler,
    )

    # Attempt initial tool discovery
    tools = await _mcp.list_tools(jwt_token="")
    if tools:
        mark_tools_loaded()
        skill_matcher.load_skills(
            await skill_loader.load_for_role(role="admin", tenant_id="__default__")
        )
        logger.info("tools_loaded", count=len(tools))
    else:
        logger.warning("tools_not_loaded_at_startup")

    logger.info("compliance_assistant_ready")

    yield

    # Cleanup
    if _llm:
        await _llm.close()
    if _mcp:
        await _mcp.close()
    if _memory:
        await _memory.close()

    logger.info("compliance_assistant_shutdown")


app = FastAPI(
    title="Compliance Assistant",
    description="User-facing Shadow AI agent for compliance platform",
    version=settings.chat_version,
    lifespan=lifespan,
)

app.include_router(health_router)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all exception handler to prevent 500 stack traces."""
    logger.error(
        "unhandled_exception",
        path=request.url.path,
        error_type=type(exc).__name__,
        error=str(exc),
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error. Please try again."},
    )


@app.post("/init", response_model=ChatResponse)
async def init_session(
    request: InitRequest,
    current_user: UserContext = Depends(get_current_user),
) -> ChatResponse:
    """Initialize a new session with a proactive greeting.

    Loads skills, builds context, and generates an opener via LLM.
    Uses JWT-validated identity instead of request body user_context.
    """
    if not _agent_loop or not _sessions:
        raise HTTPException(status_code=503, detail="Service not ready")

    session = await _sessions.get_or_create(
        session_id=request.session_id,
        tenant_id=current_user.tenant_id,
        user_id=current_user.user_id,
        role=current_user.role,
    )

    return await _agent_loop.handle_init(
        session=session,
        user=current_user,
    )


@app.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    current_user: UserContext = Depends(get_current_user),
) -> ChatResponse:
    """Process a user message through the agent loop.

    May involve multiple LLM rounds and tool executions.
    Returns the final response, any actions taken, and pending confirmations.
    Uses JWT-validated identity instead of request body user_context.
    """
    if not _agent_loop or not _sessions:
        raise HTTPException(status_code=503, detail="Service not ready")

    session = await _sessions.get_or_create(
        session_id=request.session_id,
        tenant_id=current_user.tenant_id,
        user_id=current_user.user_id,
        role=current_user.role,
    )

    return await _agent_loop.handle_message(
        message=request.message,
        session=session,
        user=current_user,
    )


@app.post("/confirm", response_model=ChatResponse)
async def confirm_action(
    request: ConfirmRequest,
    current_user: UserContext = Depends(get_current_user),
) -> ChatResponse:
    """Approve a pending destructive action.

    Re-executes the tool with confirmed=True via MCP.
    Uses JWT-validated identity instead of request body user_context.
    """
    if not _agent_loop or not _sessions:
        raise HTTPException(status_code=503, detail="Service not ready")

    session = await _sessions.get_or_create(
        session_id=request.session_id,
        tenant_id=current_user.tenant_id,
        user_id=current_user.user_id,
        role=current_user.role,
    )

    return await _agent_loop.handle_confirm(
        session=session,
        user=current_user,
        confirmation_id=request.confirmation_id,
    )


@app.post("/cancel", response_model=ChatResponse)
async def cancel_action(
    request: CancelRequest,
    current_user: UserContext = Depends(get_current_user),
) -> ChatResponse:
    """Reject a pending destructive action.

    Uses JWT-validated identity instead of request body user_context.
    """
    if not _agent_loop or not _sessions:
        raise HTTPException(status_code=503, detail="Service not ready")

    session = await _sessions.get_or_create(
        session_id=request.session_id,
        tenant_id=current_user.tenant_id,
        user_id=current_user.user_id,
        role=current_user.role,
    )

    return await _agent_loop.handle_cancel(
        session=session,
        user=current_user,
        confirmation_id=request.confirmation_id,
    )


def main() -> None:
    """Entry point for running the service directly."""
    uvicorn.run(
        "src.main:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
        reload=settings.environment != "production",
    )


if __name__ == "__main__":
    main()
