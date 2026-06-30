# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AWS-first AI agent system for compliance SaaS, adapter-decoupled for future on-prem/hybrid deployments. Deploys as Docker Compose, uses Bedrock for LLM inference (with adapter layer for provider portability). All services are fully implemented with Python source, Dockerfiles, docker-compose.yml, Terraform infrastructure, and unit tests.

This repo is the **AI layer only**. The broader platform handles GRC features (policy management, vendor risk, dashboards). The AI layer provides intelligent evaluation, assistance, and autonomous coordination. The core concept is "Shadow AI" — every user gets a personal agent that does compliance work on their behalf with zero compliance knowledge required.

### Platform Strategy

- **AWS V1**: Bedrock (Converse API), S3, RDS PostgreSQL + pgvector, ElastiCache Redis, Textract
- **Adapter layer**: `common/` clients use adapters (S3Adapter/MinIOAdapter, etc.) — switch via env vars, zero code changes
- **Per-tenant budget tracking**: one customer's credit exhaustion never affects others; system degrades gracefully (rules-only eval, data-only assistant, indefinite queue)

## Key Documentation Pointers

- `requirements/README.md` — full system context and build order
- `requirements/frameworks-modules-design.md` — per-service file trees, Dockerfile template, dependency lists, code patterns
- `requirements/security-auth-design.md` — JWT validation, RBAC, RLS, S2S auth details
- `compliance-assistant/SKILLS.md` — full skill catalog (15 categories, role-based)
- Each service has `REQUIREMENTS.md` and `DESIGN.md` as source of truth for implementation

## Technology Stack

| Layer | Choice | Version |
|-------|--------|---------|
| Language | Python | 3.12 |
| Web framework | FastAPI | 0.115+ |
| ASGI server | Uvicorn | 0.30+ |
| HTTP client | httpx | 0.27+ |
| Validation / settings | Pydantic v2 + pydantic-settings | 2.7+ / 2.3+ |
| ORM | SQLAlchemy 2.0 (async) + asyncpg | 2.0+ |
| Migrations | Alembic | 1.13+ |
| LLM orchestration | LangGraph (agent-eval only) | 0.2+ |
| Vector search | pgvector (in PostgreSQL) | 0.7+ |
| Redis | redis-py (async, hiredis) | 5.0+ |
| AWS SDK | boto3 + aiobotocore | 1.35+ |
| Logging | structlog | 24.1+ |
| Linting/format | ruff | 0.5+ |
| Testing | pytest + pytest-asyncio | 8.0+ |
| Containers | Docker multi-stage, python:3.12-slim base |

## Build & Run Commands

```bash
# Build all services
docker compose build

# Build a single service (Dockerfile context is repo root, not service dir)
docker build --platform linux/amd64 --provenance=false -t onpremai/{service}:dev -f {service}/Dockerfile .

# Run the full stack (infra: postgres:5432, redis:6379, minio:9000/9001)
docker compose up -d

# Upgrade single service (zero-downtime for others)
docker compose up -d --no-deps {service}

# Swap LLM model (no rebuild — config hot-reloads)
# Edit config/routing.yaml, then: docker compose restart llm-gateway
```

## Test Commands

Tests run from repo root. No pytest.ini exists — no central config needed.

```bash
# Run all tests
python -m pytest tests/ -v

# Run tests for one service (use underscores in dir name)
python -m pytest tests/llm_gateway/ -v
python -m pytest tests/agent_eval/ -v
python -m pytest tests/common/ -v

# Run a single test file
python -m pytest tests/llm_gateway/test_resolver.py -v

# Run a single test
python -m pytest tests/llm_gateway/test_budget.py::TestBudgetTracker::test_daily_limit -v

# With coverage
python -m pytest tests/ -v --cov=src --cov-report=term-missing

# E2E tests (full docker compose stack must be running)
python -m pytest tests/e2e/ -v

# Lint + format check
ruff check . && ruff format --check .

# Syntax validation for a single file
python -c "import ast; ast.parse(open('{file}').read())"
```

### Writing New Tests

Each test file must add its service to `sys.path` because services aren't installed as packages. The path goes in `conftest.py`:
```python
import sys
from pathlib import Path
# parents[2] lands at repo root, then into the hyphenated service dir
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "llm-gateway"))
```

Service code then imports with the `src.` prefix (matching the Docker layout):
```python
from src.models import CompletionRequest
from src.routing.resolver import RouteResolver
```

**Naming gotcha**: service dirs use hyphens (`llm-gateway/`), test dirs use underscores (`tests/llm_gateway/`).

Async tests require `@pytest.mark.asyncio` decorator. Fixtures are in per-service `conftest.py` files under `tests/{service}/`. Test fixtures live in `testdata/` (evidence files, framework definitions, tenant/user JSON).

## AWS Deployment

```bash
# Deploy to AWS (fresh account — creates VPC, ECS, RDS, Redis, S3, ECR, Cognito, ALB)
./deploy.sh dev

# Deploy production
./deploy.sh prod

# Update single service image via Terraform
cd infrastructure && terraform apply -var-file=environments/dev.tfvars \
  -var='service_image_tags={"llm-gateway":"v1.2.3"}' -target=module.llm_gateway
```

## Architecture

8 services + static frontend, each independently deployable via Docker Compose:

| Service | Port | Role |
|---------|------|------|
| `llm-gateway` | 4000 (agent), 4001 (admin) | Model routing, escalation, 7 provider adapters |
| `memory-service` | 5000 | Shared memory with pgvector (user/tenant/task/eval/patterns/skills) |
| `observer` | 9000 (host: 9002) | Autonomous improvement agent (tunes routing via admin API) |
| `sandbox-service` | 6000 | Isolated code execution in ephemeral containers (docker-compose override) |
| `preprocessor` | 7000 | File ingestion (Excel/PDF/Word → metadata) |
| `compliance-assistant` | 8081 | User-facing Shadow AI (persona-based, skills/playbooks) |
| `agent-eval` | 8080 | Compliance evaluation engine (3-layer deterministic pipeline) |
| `common/` | — | Shared client libraries copied into each service image |
| `frontend/` | — | Static HTML/JS/CSS UI (vanilla JS, no build step) |

### Import Paths in Docker

All Dockerfiles set `PYTHONPATH=/app`. The resulting layout is:
```
/app/
├── common/    → from common import LLMClient, AgentLogger
├── src/       → from src.models import CompletionRequest
└── config/    → (llm-gateway only, mounted read-only)
```
Service-internal imports always use the `src.` prefix. Cross-service shared code uses `common.` prefix.

### Inter-Service Communication

All LLM calls flow through `llm-gateway`. Agents declare a **task name** (e.g., `task="evaluate_control"`), never a model name. The gateway resolves the model via a 3-level routing hierarchy: tenant override > agent override > task default → tier (fast/mid/strong) → model. Escalation happens transparently when confidence is below threshold.

The `common/` library is the abstraction layer — agents never talk to infrastructure directly. StorageClient auto-detects MinIO vs S3 from `STORAGE_ENDPOINT`. MemoryClient returns empty results on failure (graceful degradation). LLMClient raises `LLMUnavailableError` on gateway failure.

### Agent Registry

Dynamic registry (hosted in memory-service) where agents self-register on startup and heartbeat during operation. Enables:
- **Capability-based routing** — gateway resolves `task → agent` (not just `task → model`) for inter-agent delegation
- **Version coexistence** — run v1 and v2 of an agent simultaneously with priority-weighted traffic split
- **Health-aware routing** — skip degraded/unhealthy agents, queue work for offline agents
- **Inter-agent discovery** — Shadow AI agents find each other for coordination (e.g., compliance manager's agent nudges control owner's agent)

Agents register capabilities (task names + priority), send heartbeats every 10s, and deregister on graceful shutdown. System functions without registry (soft dependency) — agents fall back to direct HTTP when registry is unavailable. See `requirements/agent-registry.md` for full spec.

### common/ Client API

```python
from common import LLMClient, MemoryClient, StorageClient, SandboxClient, AgentLogger

llm = LLMClient()
response = llm.complete(messages=[...], task="evaluate_control", tenant_id="...", trace_id="...")
# Returns: LLMResponse(content, model_used, tier_used, tokens, latency)
# Raises: LLMUnavailableError on gateway failure
# Raises: LLMCreditExhaustedError on budget/quota exhaustion (agent enters degraded mode)

memory = MemoryClient()
facts = memory.tenant_recall(tenant_id, query, top_k=5)  # Returns [] on failure
memory.eval_store(tenant_id, framework="SOC2", control_id="...", result={...})

storage = StorageClient()  # Adapter selected by STORAGE_BACKEND env (s3 | minio)
data = storage.get_json("tenant/evidence/control/metadata.json")

logger = AgentLogger(agent_name="agent-eval")
logger.info("Control evaluated", control_id="CC6.1", duration_ms=4200)

registry = RegistryClient()
await registry.register(agent_type="agent-eval", version="1.5.0", capabilities=[...], endpoint="...")
agents = await registry.discover(task="evaluate_vendor", tenant_id="acme-corp")
# Returns: sorted list of healthy agents with capacity
# Soft dependency: system works without registry (direct HTTP fallback)
```

Exception hierarchy: `CommonError` → `LLMUnavailableError`, `LLMTimeoutError`, `LLMCreditExhaustedError`, `StorageError`, `StorageNotFoundError`, `SandboxError`, `StateError`

### Adapter Pattern

Agents never know which infrastructure backend is active:

| Client | STORAGE_BACKEND=s3 | STORAGE_BACKEND=minio |
|--------|-------------------|----------------------|
| StorageClient | S3 via boto3 + IAM role | MinIO via minio SDK + access keys |

| Client | OCR_BACKEND=textract | OCR_BACKEND=tesseract |
|--------|---------------------|----------------------|
| Preprocessor | AWS Textract | Local Tesseract binary |

Adding a new backend = one adapter class + config value. Zero agent changes.

### agent-eval Pipeline (Core Business Logic)

Three layers maximize determinism:
1. **Layer 1 (Rules):** Deterministic checks (file_existence, freshness, schema_presence, row_count, null_rate, cross_reference, quantitative, keyword_presence) — resolves 60-70% of criteria with zero LLM cost
2. **Layer 2 (LLM Judgment):** Only for NEEDS_JUDGMENT items from Layer 1, bounded questions with rubric
3. **Layer 3 (Scoring):** Deterministic weighted formula with floor rules (policy FAIL caps at 0.84, >25% impl FAIL forces non_compliant)

Evidence hash caching: if evidence hasn't changed, return cached result (100% deterministic, zero cost).

### Degradation Hierarchy

| Failure | Impact |
|---------|--------|
| Memory down | Agents work with empty context (reduced quality, no crash) |
| LLM Gateway down | Raise `LLMUnavailableError` — agent decides fallback |
| LLM credits exhausted | Raise `LLMCreditExhaustedError` — tier cascade, then queue indefinitely |
| Sandbox down | Return `success=False` — code execution fails gracefully |
| Storage down | **Hard failure** — cannot proceed without data |

### Credit Exhaustion Cascade (per-tenant)

```
Level 0: Full service (all tiers)
Level 1: Strong gone → cap at mid (complex reasoning downgrades)
Level 2: Mid gone → fast only (rules + cheap LLM for high-priority items)
Level 3: All LLM gone → deterministic-only (rules still resolve 60-70%)
Level 4: Monthly cap → queue indefinitely, process when budget resets
```

Queued requests never expire — they persist and process automatically when credits return.

## Authentication & Multi-Tenancy

- **User auth**: Cognito JWT (RS256 JWKS validation via `python-jose`). Custom claims: `custom:tenant_id`, `custom:role`
- **S2S auth**: HMAC-signed API keys in `X-Service-Id` / `X-Service-Key` headers, keys from Secrets Manager
- **RBAC roles** (hierarchy): admin > compliance_manager > contributor | auditor > viewer
- **Tenant isolation**: application-layer `tenant_id` filter on all queries + PostgreSQL RLS (`SET app.current_tenant`) as defense-in-depth
- **MCP tools**: pre-filtered by role before returning to compliance-assistant (TOOL_ACCESS matrix in security-auth-design.md)
- S3 evidence paths: `s3://compliance-artifacts/{tenant_id}/evidence/...`
- **Key invariant**: `tenant_id` is ALWAYS extracted from the JWT (Cognito-signed, RS256) — never from user-supplied request parameters. An admin of Tenant A has full admin tools, but they only operate on Tenant A's data.
- **Agent security**: agents have ZERO permission logic — they pass JWT through, MCP/memory/storage enforce permissions. Inter-agent delegation propagates original JWT via `X-Original-JWT` header. Registry discovery is tenant-scoped (R17-R21 in `requirements/agent-registry.md`).

## Middleware Stack (All Services)

Applied in this order on every request:
1. `TraceIdMiddleware` — reads/generates `X-Trace-Id`, sets on request.state + structlog context
2. `TenantContextMiddleware` — extracts tenant_id from JWT or service header
3. `RequestLoggingMiddleware` — logs method/path/status/duration with trace_id

## Key Patterns

- ALL external calls use `httpx.AsyncClient` (never `requests` in async context)
- Configuration via `pydantic_settings.BaseSettings` with env var defaults that work with docker-compose
- Every service has `/health` and `/ready` endpoints
- PII-aware structured JSON logging via `common.logging.logger.AgentLogger` — operational logs are PII-free, audit trail preserves full data
- Use `PII()` wrapper for any field containing user data (emails, names): `logger.info("Sent", assignee=PII("john@acme.com"))`
- `common/` is COPY'd into each Docker image at `/app/common/` (not a pip package) — rebuild all images when common/ changes
- Dockerfiles use repo root as build context: `docker build -f {service}/Dockerfile .` — this allows `COPY common/ ./common/` and `COPY {service}/src/ ./src/`
- LLM Gateway config is a single YAML file (`config/routing.yaml`) with hot-reload via watchdog
- Clients are thread-safe — instantiate once at startup, share across all requests
- Startup sequence: log pass/fail per dependency check, emit fix hints on failure (see `requirements/observability.md` R1-R2)
- Dockerfile pattern: multi-stage build, non-root `appuser`, `PYTHONPATH=/app`, single uvicorn worker (horizontal scaling via task count, not workers)
- Service discovery: Cloud Map DNS (`{service}.onpremai.internal`) in ECS; `http://{service}:{port}` in Docker Compose
- Each service's `common/` symlink or copy in the source tree is only for local dev — Docker build copies from the real `common/` at repo root
- LLM providers (in `llm-gateway/src/providers/`): `bedrock.py`, `anthropic.py`, `openai_compat.py` — all implement `ProviderAdapter` base class

## Rules

- Never hardcode LLM provider names or model IDs in service code — use task-based routing
- Never use `boto3` directly in agent code — use `common/` client abstractions (StorageClient, etc.)
- Never hardcode AWS-specific logic in business layer — adapter handles infrastructure differences
- Never skip security review before deploy
- Never use `print()` — use structured logger with `PII()` wrapper for user data fields
- Never put business logic in route handlers — delegate to service layer
- Never use synchronous blocking in async context
- Never use `allow_origins=["*"]` with `allow_credentials=True` (CORS)
- All services must handle graceful degradation (memory down = reduced context, not crash; storage down = hard failure)
- All agents must handle `LLMCreditExhaustedError` — never crash on budget exhaustion
- Per-tenant budget: one customer's exhaustion must NEVER affect other customers
- Tests required for all new code (unit minimum, integration preferred)
- Type hints on all parameters, return types, and class attributes

## Development Workflow

Skills in `.claude/skills/`:
- `/implement` — code implementation following project conventions
- `/build` — Docker image building
- `/test` — run tests (unit, integration, E2E with Playwright)
- `/security-review` — security audit before deploy
- `/deploy` — Docker Compose deployment
- `/ci-pipeline` — full pipeline orchestration
