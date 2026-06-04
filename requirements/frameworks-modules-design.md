# Frameworks & Module Low-Level Design

## Overview

This document specifies the technology stack, framework choices, and module-level implementation details for each service.

---

## Technology Stack

### Core Frameworks

| Layer | Choice | Version | Why |
|-------|--------|---------|-----|
| **Web framework** | FastAPI | 0.115+ | Async-native, Pydantic validation, OpenAPI, dependency injection for auth |
| **ASGI server** | Uvicorn | 0.30+ | Production-grade, works with Fargate health checks |
| **HTTP client** | httpx | 0.27+ | Async, connection pooling, timeout control |
| **ORM / DB** | SQLAlchemy 2.0 + asyncpg | 2.0+ | Async PostgreSQL, type-safe queries, migration support |
| **Migrations** | Alembic | 1.13+ | Schema versioning, auto-generate from models |
| **Validation** | Pydantic v2 | 2.7+ | Request/response models, settings, structured output schemas |
| **Settings** | pydantic-settings | 2.3+ | Env var loading with type coercion and defaults |
| **Task queue** | None (async background tasks) | — | FastAPI BackgroundTasks + asyncio for simplicity |
| **Scheduling** | APScheduler | 3.10+ | Observer cron jobs (quality, prompts, model-fit, self-eval) |
| **LLM orchestration** | LangGraph | 0.2+ | Agent-eval graph (existing, ported from current code) |
| **Vector search** | pgvector | 0.7+ | Embeddings in PostgreSQL (no separate vector DB) |
| **Redis client** | redis-py (async) | 5.0+ | Sessions, rate limits, budget queue |
| **AWS SDK** | boto3 + aiobotocore | 1.35+ | Bedrock, S3, Textract, Secrets Manager |
| **JWT validation** | python-jose | 3.3+ | RS256 JWKS validation for Cognito tokens |
| **Logging** | structlog | 24.1+ | Structured JSON output, processor pipeline for PII redaction |
| **Testing** | pytest + pytest-asyncio | 8.0+ | Async test support, fixtures |
| **Linting** | ruff | 0.5+ | Fast, replaces flake8 + isort + black |
| **Containerization** | Docker (multi-stage) | 24+ | Slim Python 3.12 base |

### Why These Choices

**FastAPI over Flask/Django:**
- Native async (all our calls are async — LLM, storage, memory)
- Pydantic models double as API docs and validation
- Dependency injection is perfect for auth (inject UserContext per request)
- OpenAPI spec auto-generated (useful for MCP tool discovery)

**SQLAlchemy 2.0 over raw asyncpg:**
- Type-safe query building
- Alembic migrations (critical for memory-service schema evolution)
- Repository pattern maps cleanly to tenant-scoped queries
- ORM optional — can use Core for performance-critical queries

**LangGraph over raw LLM calls:**
- Agent-eval already uses LangGraph (port, don't rewrite)
- Graph structure maps to the 3-layer pipeline
- State management for multi-step evaluation
- Conditional edges for routing (Layer 1 → skip Layer 2 if all resolved)

**structlog over stdlib logging:**
- Processor pipeline enables PII redaction as a log processor
- Native JSON output without custom formatters
- Context binding (trace_id, tenant_id) without threading.local hacks
- Drop-in replacement for stdlib (compatible with libraries that use logging)

---

## Module Low-Level Designs

### common/ — Shared Client Libraries

```
common/
├── __init__.py              # Re-exports: LLMClient, MemoryClient, StorageClient, etc.
├── auth/
│   ├── __init__.py
│   ├── cognito.py           # CognitoTokenValidator, UserContext dataclass
│   ├── service_auth.py      # ServiceAuthenticator (S2S API keys)
│   └── rbac.py              # require_role(), require_scope() dependencies
├── clients/
│   ├── __init__.py
│   ├── llm_client.py        # LLMClient → talks to llm-gateway
│   ├── memory_client.py     # MemoryClient → talks to memory-service
│   ├── storage_client.py    # StorageClient → S3Adapter or MinIOAdapter
│   ├── state_client.py      # StateClient → PostgreSQL (job tracking)
│   └── sandbox_client.py    # SandboxClient → talks to sandbox-service
├── storage/
│   ├── __init__.py
│   ├── base.py              # StorageAdapter ABC
│   ├── s3_adapter.py        # boto3 S3 implementation
│   └── minio_adapter.py     # minio SDK implementation
├── logging/
│   ├── __init__.py
│   ├── logger.py            # AgentLogger (structlog-based)
│   ├── pii.py               # PII() wrapper, HMAC hashing, regex patterns
│   └── processors.py        # structlog processors for redaction
├── errors.py                # Exception hierarchy
├── config.py                # Shared pydantic-settings base
├── retry.py                 # @retry decorator with exponential backoff
└── middleware.py            # Common FastAPI middleware (trace_id, tenant context)
```

**Key implementation detail — structlog PII processor:**

```python
import structlog
from common.logging.pii import PII, redact_pii_fields, redact_pii_patterns

def configure_logging(service_name: str):
    """Configure structlog with PII-aware processors."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            add_service_info(service_name),
            redact_pii_fields,          # Hash PII() wrapped values
            redact_pii_patterns,        # Regex scrub emails/phones in messages
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
    )
```

---

### llm-gateway

```
llm-gateway/
├── Dockerfile
├── requirements.txt
├── src/
│   ├── __init__.py
│   ├── main.py                  # FastAPI app, lifespan, routes
│   ├── config.py                # Settings (gateway URL, ports, config path)
│   ├── models.py                # Request/Response Pydantic models
│   ├── routing/
│   │   ├── __init__.py
│   │   ├── resolver.py          # 3-level routing: tenant > agent > task → model
│   │   ├── config_loader.py     # YAML hot-reload (watchdog file watcher)
│   │   └── canary.py            # Traffic splitting for A/B tests
│   ├── providers/
│   │   ├── __init__.py
│   │   ├── base.py              # ProviderAdapter ABC
│   │   ├── bedrock.py           # BedrockAdapter (Converse API via boto3)
│   │   ├── anthropic.py         # AnthropicAdapter (Messages API via httpx)
│   │   └── openai_compat.py     # OpenAI-compatible (vLLM, Ollama, etc.)
│   ├── budget/
│   │   ├── __init__.py
│   │   ├── tracker.py           # Per-tenant cost accumulator (Redis-backed)
│   │   ├── queue.py             # Persistent request queue (Redis + StateClient)
│   │   └── degradation.py       # Level 0-4 cascade logic
│   ├── escalation.py            # Confidence check, tier escalation
│   ├── tools.py                 # Tool format translation (OpenAI ↔ Anthropic ↔ ReAct)
│   ├── admin/
│   │   ├── __init__.py
│   │   ├── routes.py            # Admin API (:4001) — metrics, routing, budget
│   │   └── auth.py              # Admin API auth (S2S key, observer only)
│   └── health.py                # /health, /ready, model health checks
├── tests/
│   ├── unit/
│   │   ├── test_resolver.py
│   │   ├── test_budget.py
│   │   ├── test_escalation.py
│   │   └── test_tools.py
│   └── integration/
│       ├── test_bedrock.py
│       └── test_routing_e2e.py
└── common/                      # COPY'd from /common
```

**Key implementation detail — dual-port FastAPI:**

```python
# main.py — two FastAPI apps on different ports
from fastapi import FastAPI
import uvicorn

agent_app = FastAPI(title="LLM Gateway - Agent API")  # port 4000
admin_app = FastAPI(title="LLM Gateway - Admin API")  # port 4001

# Agent-facing routes (port 4000)
@agent_app.post("/v1/complete")
async def complete(request: CompletionRequest, service: ServiceIdentity = Depends(verify_service)):
    ...

# Admin routes (port 4001, observer only)
@admin_app.get("/admin/metrics")
async def metrics(service: ServiceIdentity = Depends(verify_admin_service)):
    ...

# Run both in lifespan
async def lifespan(app):
    # Start admin server on separate port
    admin_server = uvicorn.Server(uvicorn.Config(admin_app, port=4001, host="0.0.0.0"))
    asyncio.create_task(admin_server.serve())
    yield
```

---

### memory-service

```
memory-service/
├── Dockerfile
├── requirements.txt
├── alembic/                     # Schema migrations
│   ├── versions/
│   │   ├── 001_initial.py
│   │   └── ...
│   └── env.py
├── src/
│   ├── __init__.py
│   ├── main.py                  # FastAPI app, lifespan (run migrations on startup)
│   ├── config.py                # DB_HOST, REDIS_URL, etc.
│   ├── models/
│   │   ├── __init__.py
│   │   ├── tenant_memory.py     # SQLAlchemy model + pgvector column
│   │   ├── user_memory.py
│   │   ├── tasks.py
│   │   ├── eval_history.py
│   │   ├── patterns.py
│   │   ├── skills.py
│   │   ├── interactions.py
│   │   └── audit_trail.py       # Append-only (no update/delete methods)
│   ├── repositories/
│   │   ├── __init__.py
│   │   ├── base.py              # TenantScopedRepository (sets RLS context)
│   │   ├── tenant_memory_repo.py
│   │   ├── user_memory_repo.py
│   │   ├── task_repo.py
│   │   ├── eval_repo.py
│   │   ├── pattern_repo.py      # Cross-tenant (no RLS)
│   │   ├── skill_repo.py
│   │   └── audit_repo.py        # Insert-only
│   ├── services/
│   │   ├── __init__.py
│   │   ├── embedding.py         # Calls LLM gateway /v1/embed
│   │   ├── dedup.py             # Semantic deduplication (>0.9 similarity = update)
│   │   └── decay.py             # Pattern confidence decay (cron)
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── session.py           # Redis-backed session CRUD
│   │   ├── tenant.py            # /tenant/{id}/remember, /recall, /facts
│   │   ├── user.py              # /user/{tenant}/{user}/remember, /recall
│   │   ├── tasks.py             # /tasks/{tenant} CRUD
│   │   ├── eval.py              # /eval/{tenant}/{framework}/{control}
│   │   ├── patterns.py          # /patterns/record, /query, /boost
│   │   ├── skills.py            # /skills/{id} CRUD + versioning
│   │   ├── interactions.py      # /interactions/{tenant}/{user}
│   │   └── audit.py             # /audit/{tenant} (read-only)
│   ├── db.py                    # AsyncSession factory, connection pool
│   └── health.py                # /health, /ready (DB + Redis check)
├── tests/
└── common/
```

**Key implementation detail — RLS middleware:**

```python
# db.py
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy import text

engine = create_async_engine(settings.database_url, pool_size=20)

async def get_tenant_session(tenant_id: str) -> AsyncSession:
    """Create a session with RLS tenant context set."""
    session = AsyncSession(engine)
    await session.execute(text("SET app.current_tenant = :tid"), {"tid": tenant_id})
    return session
```

---

### agent-eval

```
agent-eval/
├── Dockerfile
├── requirements.txt
├── src/
│   ├── __init__.py
│   ├── main.py                  # FastAPI app: POST /evaluate, GET /status, POST /chat
│   ├── config.py
│   ├── models.py                # EvalRequest, EvalResult, JobStatus
│   ├── graph/
│   │   ├── __init__.py
│   │   ├── state.py             # LangGraph state schema
│   │   ├── graph.py             # Graph definition (nodes + edges)
│   │   ├── router.py            # Intent classification node
│   │   ├── discovery.py         # Evidence discovery node
│   │   ├── extractor.py         # Metadata extraction node
│   │   ├── rules_engine.py      # Layer 1: deterministic rule checks
│   │   ├── evaluation.py        # Layer 2: LLM judgment node
│   │   ├── scoring.py           # Layer 3: deterministic scoring formula
│   │   ├── sandbox_node.py      # Code generation + sandbox execution
│   │   ├── code_fixer.py        # Fix sandbox errors node
│   │   └── formatter.py         # Output formatting node
│   ├── rules/
│   │   ├── __init__.py
│   │   ├── engine.py            # Rule dispatch (8 check types)
│   │   ├── file_existence.py
│   │   ├── freshness.py
│   │   ├── schema_presence.py
│   │   ├── row_count.py
│   │   ├── null_rate.py
│   │   ├── cross_reference.py
│   │   ├── quantitative.py
│   │   └── keyword_presence.py
│   ├── rag/
│   │   ├── __init__.py
│   │   ├── index.py             # RAG index loader (from S3)
│   │   └── retriever.py         # Similarity search for testing criteria
│   ├── jobs.py                  # Background job management (asyncio)
│   └── health.py
├── tests/
│   ├── unit/
│   │   ├── test_rules_engine.py # Test each rule check with known inputs
│   │   ├── test_scoring.py      # Verify floor rules, weight formula
│   │   └── test_graph.py        # Mock LLM, verify routing
│   └── integration/
│       └── test_full_eval.py    # End-to-end with real services
└── common/
```

**Key implementation detail — partial evaluation on credit exhaustion:**

```python
# graph/evaluation.py
async def evaluation_node(state: EvalState) -> EvalState:
    needs_judgment = [c for c in state.criteria_results if c.status == "NEEDS_JUDGMENT"]
    
    if not needs_judgment:
        return state  # All resolved by rules, skip LLM
    
    try:
        for criterion in needs_judgment:
            response = await state.llm_client.complete(
                messages=build_judgment_prompt(criterion, state.evidence),
                task="evaluate_control",
                tenant_id=state.tenant_id,
                trace_id=state.trace_id,
            )
            criterion.status = parse_judgment(response.content)
            criterion.confidence = response.confidence
    except LLMCreditExhaustedError as e:
        # Mark remaining as insufficient, continue to scoring
        for criterion in needs_judgment:
            if criterion.status == "NEEDS_JUDGMENT":
                criterion.status = "INSUFFICIENT_EVIDENCE"
        state.partial_evaluation = True
        state.degradation_level = e.degradation_level
    
    return state
```

---

### compliance-assistant

```
compliance-assistant/
├── Dockerfile
├── requirements.txt
├── src/
│   ├── __init__.py
│   ├── main.py                  # FastAPI app: POST /chat, /init, /confirm, /cancel
│   ├── config.py
│   ├── models.py                # ChatRequest, ChatResponse, Confirmation
│   ├── agent/
│   │   ├── __init__.py
│   │   ├── loop.py              # Agent loop: message → LLM → tools → respond (max N rounds)
│   │   ├── context_builder.py   # Build system prompt per role + user context
│   │   ├── personas.py          # 5 persona templates
│   │   └── data_only_mode.py    # Keyword intent matching fallback (no LLM)
│   ├── skills/
│   │   ├── __init__.py
│   │   ├── matcher.py           # Skill trigger matching
│   │   ├── loader.py            # Load skills from memory-service
│   │   └── playbook_engine.py   # Step tracking, resume, branching
│   ├── mcp/
│   │   ├── __init__.py
│   │   ├── client.py            # MCP client (tools/list, tools/call, resources/read)
│   │   └── confirmation.py      # Human-in-the-loop confirmation flow
│   ├── session.py               # Session management (Redis via memory-service)
│   └── health.py
├── tests/
└── common/
```

**Key implementation detail — agent loop with tool rounds:**

```python
# agent/loop.py
async def agent_loop(message: str, session: Session, max_rounds: int = 5) -> ChatResponse:
    messages = session.messages + [{"role": "user", "content": message}]
    
    for round in range(max_rounds):
        try:
            response = await llm_client.complete(
                messages=messages,
                task="tool_selection" if round == 0 else "skill_execution",
                tools=session.available_tools,
                tenant_id=session.tenant_id,
                trace_id=session.trace_id,
            )
        except LLMCreditExhaustedError:
            return data_only_mode.handle(message, session)
        
        if not response.tool_calls:
            # LLM responded with text — done
            return ChatResponse(message=response.content)
        
        # Execute tool calls
        tool_results = []
        for call in response.tool_calls:
            result = await mcp_client.call_tool(
                call["name"], call["arguments"], token=session.user_jwt
            )
            if result.get("status") == "confirmation_required":
                return ChatResponse(pending_confirmation=result)
            tool_results.append(result)
        
        # Add tool results to messages, continue loop
        messages.append({"role": "assistant", "tool_calls": response.tool_calls})
        messages.append({"role": "tool", "results": tool_results})
    
    return ChatResponse(message="I've reached my tool call limit. Here's what I found so far...")
```

---

### observer

```
observer/
├── Dockerfile
├── requirements.txt
├── src/
│   ├── __init__.py
│   ├── main.py                  # FastAPI app (admin API) + APScheduler
│   ├── config.py
│   ├── scheduler.py             # APScheduler jobs (quality, prompts, model-fit, self-eval)
│   ├── detection/
│   │   ├── __init__.py
│   │   ├── log_ingestor.py      # Read gateway logs from CloudWatch/volume
│   │   ├── aggregator.py        # Compute metrics per task/model/tenant
│   │   └── detector.py          # Issue detection (8 types)
│   ├── diagnosis/
│   │   ├── __init__.py
│   │   └── engine.py            # Strong-tier LLM diagnosis
│   ├── changes/
│   │   ├── __init__.py
│   │   ├── proposal.py          # Generate Change objects
│   │   ├── applier.py           # 3-tier apply (auto/canary/human)
│   │   ├── validator.py         # Post-apply validation
│   │   └── rollback.py          # Revert to pre-change state
│   ├── governance/
│   │   ├── __init__.py
│   │   ├── inventory.py         # Model inventory from routing config
│   │   ├── drift.py             # KS test on confidence distributions
│   │   ├── bias.py              # Cross-tenant variance detection
│   │   └── reports.py           # Weekly/monthly governance report generation
│   ├── circuit_breaker.py       # 3 rollbacks in 6h → stop
│   ├── self_regulation.py       # Weekly: tighten/relax autonomy based on track record
│   ├── routes.py                # Admin API endpoints
│   └── health.py
├── tests/
└── common/
```

---

### sandbox-service

```
sandbox-service/
├── Dockerfile
├── Dockerfile.runtime           # Pre-built execution image (pandas, numpy, etc.)
├── requirements.txt
├── src/
│   ├── __init__.py
│   ├── main.py                  # FastAPI app: POST /execute, GET /health, /metrics
│   ├── config.py
│   ├── models.py                # ExecutionRequest, ExecutionResult
│   ├── execution/
│   │   ├── __init__.py
│   │   ├── manager.py           # Concurrency control, queue
│   │   ├── docker_backend.py    # Docker-in-Docker execution
│   │   ├── subprocess_backend.py # Simple subprocess (dev only)
│   │   └── preamble.py          # Data-loading code generation
│   ├── security/
│   │   ├── __init__.py
│   │   └── import_allowlist.py  # Validate imports before execution
│   ├── storage.py               # Download files from S3 to temp dir
│   └── health.py
├── tests/
└── common/
```

---

### preprocessor

```
preprocessor/
├── Dockerfile
├── requirements.txt
├── src/
│   ├── __init__.py
│   ├── main.py                  # FastAPI app + poll trigger loop
│   ├── config.py
│   ├── models.py                # FileMetadata, ProcessingResult
│   ├── trigger/
│   │   ├── __init__.py
│   │   ├── poller.py            # Poll S3 prefix for new files
│   │   └── webhook.py           # S3 event notification handler
│   ├── extraction/
│   │   ├── __init__.py
│   │   ├── base.py              # ExtractionBackend ABC
│   │   ├── textract.py          # AWS Textract adapter
│   │   ├── tesseract.py         # Local Tesseract adapter
│   │   ├── pdfplumber_ext.py    # Digital PDF extraction
│   │   └── tika.py              # Word/PowerPoint extraction
│   ├── processing/
│   │   ├── __init__.py
│   │   ├── pipeline.py          # Detect → extract → schema → joins → metadata
│   │   ├── schema_detector.py   # Column types, date detection
│   │   └── join_detector.py     # Cross-file join candidates
│   ├── idempotency.py           # Content hash tracking
│   └── health.py
├── tests/
└── common/
```

---

### backend (MCP module)

```
backend/
├── Dockerfile
├── requirements.txt
├── src/
│   ├── __init__.py
│   ├── main.py                  # FastAPI app: /api/v1/... + /mcp
│   ├── config.py
│   ├── auth/
│   │   ├── __init__.py
│   │   ├── middleware.py        # JWT validation middleware
│   │   ├── dependencies.py      # get_current_user, require_role
│   │   └── feature_flags.py     # Per-tenant feature flag checks
│   ├── mcp/
│   │   ├── __init__.py
│   │   ├── handler.py           # MCP protocol handler (tools/list, tools/call, etc.)
│   │   ├── tools/               # Tool implementations (each tool = one file)
│   │   │   ├── __init__.py
│   │   │   ├── onboarding.py
│   │   │   ├── evidence.py
│   │   │   ├── escalation.py
│   │   │   ├── policy.py
│   │   │   ├── risk.py
│   │   │   ├── users.py
│   │   │   └── audit.py
│   │   ├── resources.py         # MCP resource providers (tenant state)
│   │   ├── prompts.py           # MCP prompt templates
│   │   └── confirmation.py      # Confirmation flow for destructive tools
│   ├── services/                # Business logic (shared by REST + MCP)
│   │   ├── __init__.py
│   │   ├── control_service.py
│   │   ├── evidence_service.py
│   │   ├── policy_service.py
│   │   ├── risk_service.py
│   │   ├── user_service.py
│   │   └── audit_service.py
│   ├── db/
│   │   ├── __init__.py
│   │   ├── models.py            # SQLAlchemy models
│   │   ├── session.py           # Async session factory
│   │   └── migrations/          # Alembic
│   ├── api/                     # REST API routes (frontend)
│   │   ├── __init__.py
│   │   ├── controls.py
│   │   ├── evidence.py
│   │   └── ...
│   └── health.py
├── tests/
└── common/
```

---

## Middleware Stack (All Services)

Every service applies middleware in this order:

```python
# main.py (typical service)
from fastapi import FastAPI
from common.middleware import (
    TraceIdMiddleware,       # 1. Generate/propagate X-Trace-Id
    TenantContextMiddleware, # 2. Extract tenant_id, set on request.state
    RequestLoggingMiddleware,# 3. Log request start/end with timing
)

app = FastAPI(title="service-name", lifespan=lifespan)

# Order matters — outermost runs first
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(TenantContextMiddleware)
app.add_middleware(TraceIdMiddleware)

# CORS only on user-facing services (backend, compliance-assistant)
if settings.cors_enabled:
    app.add_middleware(CORSMiddleware, ...)
```

**Middleware execution order (per request):**
1. **TraceIdMiddleware** — reads `X-Trace-Id` header or generates UUID, sets on request.state and structlog context
2. **TenantContextMiddleware** — extracts tenant_id from JWT or service header, sets on request.state
3. **RequestLoggingMiddleware** — logs request method/path/status/duration with trace_id

---

## Dockerfile Template (All Services)

```dockerfile
# Multi-stage build for minimal image size
FROM python:3.12-slim AS builder

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.12-slim AS runtime

# Security: non-root user
RUN useradd -m -u 1000 appuser
WORKDIR /app

# Copy installed packages
COPY --from=builder /install /usr/local

# Copy application code
COPY common/ /app/common/
COPY src/ /app/src/

# Set Python path
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

USER appuser

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s CMD curl -f http://localhost:8080/health || exit 1

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
```

**Why single worker:**
- Fargate tasks are sized per-service (0.5-1 vCPU)
- Horizontal scaling via ECS task count, not worker count
- Avoids shared state issues between workers
- Each task gets its own IAM role credentials

---

## Dependencies Per Service

### Shared (all services)

```
# requirements-common.txt (included by all)
fastapi>=0.115
uvicorn[standard]>=0.30
httpx>=0.27
pydantic>=2.7
pydantic-settings>=2.3
structlog>=24.1
python-jose[cryptography]>=3.3
```

### Service-specific additions

| Service | Additional Dependencies |
|---------|----------------------|
| **llm-gateway** | `boto3`, `aiobotocore`, `anthropic`, `pyyaml`, `watchdog` |
| **memory-service** | `sqlalchemy[asyncio]>=2.0`, `asyncpg`, `pgvector`, `redis[hiredis]`, `alembic` |
| **agent-eval** | `langgraph>=0.2`, `langchain-core` |
| **compliance-assistant** | `redis[hiredis]` |
| **observer** | `apscheduler>=3.10`, `scipy` (for KS test) |
| **sandbox-service** | `docker>=7.0` (Docker SDK) |
| **preprocessor** | `boto3` (Textract), `pdfplumber`, `openpyxl`, `python-docx`, `pytesseract` |
| **backend** | `sqlalchemy[asyncio]>=2.0`, `asyncpg`, `alembic`, `redis[hiredis]` |

---

## Testing Strategy

### Test Types Per Module

| Module | Unit Tests | Integration Tests | E2E Tests |
|--------|:----------:|:-----------------:|:---------:|
| common/ | Mock HTTP, test adapters | Real Redis/Postgres (testcontainers) | — |
| llm-gateway | Mock providers, test routing/budget | Real Bedrock (sandbox account) | Full request flow |
| memory-service | Mock DB, test dedup/decay logic | Real Postgres + pgvector | CRUD + semantic search |
| agent-eval | Mock LLM, test rules engine + scoring | Real pipeline with mock evidence | Full evaluation flow |
| compliance-assistant | Mock MCP + LLM, test agent loop | Real session flow | Playwright (chat UI) |
| observer | Mock logs + gateway admin API | Real metrics pipeline | — |
| sandbox-service | Mock Docker SDK | Real container execution | Code → result flow |
| preprocessor | Mock storage, test extractors | Real file processing | Upload → metadata flow |
| backend | Mock services, test RBAC | Real DB + auth flow | MCP protocol compliance |

### Running Tests

```bash
# Unit tests (fast, mocked, no external deps)
cd {service} && python -m pytest tests/unit/ -v

# Integration tests (needs Docker for testcontainers)
cd {service} && python -m pytest tests/integration/ -v

# E2E tests (needs full stack running)
python -m pytest tests/e2e/ -v

# Coverage
python -m pytest tests/ --cov=src --cov-report=term-missing --cov-fail-under=80

# Type checking
mypy src/ --strict

# Lint + format
ruff check src/ tests/ && ruff format --check src/ tests/
```
