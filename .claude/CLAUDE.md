# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Hybrid on-prem/cloud AI agent system for compliance SaaS. Deploys as Docker Compose, connects to any LLM (local or cloud). Currently in design phase — each service has REQUIREMENTS.md and DESIGN.md but no implementation yet.

## Build & Run Commands

```bash
# Build a single service
docker build --platform linux/amd64 --provenance=false -t onpremai/{service}:dev ./{service}

# Build all services
docker compose build

# Run the full stack
docker compose up -d

# Run with local LLM (Ollama)
docker compose --profile local-llm up -d

# Upgrade single service (zero-downtime for others)
EVAL_VERSION=1.5.1 docker compose up -d --no-deps agent-eval

# Swap LLM model (no rebuild)
vim config/routing.yaml && docker compose restart llm-gateway
```

## Test Commands

```bash
# Unit tests for one service
cd {service} && python -m pytest tests/unit/ -v

# With coverage
python -m pytest tests/ -v --cov=src --cov-report=term-missing

# Integration tests (needs Docker)
python -m pytest tests/integration/ -v

# Lint + format
ruff check src/ tests/ && ruff format --check src/ tests/

# Syntax validation
python -c "import ast; ast.parse(open('{file}').read())"
```

## Architecture

8 services, each independently deployable via Docker Compose:
- `compliance-assistant` — user-facing AI (persona-based, skills/playbooks)
- `agent-eval` — compliance evaluation engine (3-layer deterministic pipeline)
- `llm-gateway` — model routing, escalation, provider adapters (ports 4000 agent-facing, 4001 admin)
- `memory-service` — shared memory with pgvector (user/tenant/task/eval/patterns/skills)
- `observer` — autonomous improvement agent (tunes routing via admin API)
- `sandbox-service` — isolated code execution in containers
- `preprocessor` — file ingestion (Excel/PDF/Word → metadata)
- `common/` — shared client libraries copied into each service image

### Inter-Service Communication

All LLM calls flow through `llm-gateway`. Agents declare a **task name** (e.g., `task="evaluate_control"`), never a model name. The gateway resolves the model via a 3-level routing hierarchy: tenant override > agent override > task default → tier (fast/mid/strong) → model. Escalation happens transparently when confidence is below threshold.

The `common/` library is the abstraction layer — agents never talk to infrastructure directly. StorageClient auto-detects MinIO vs S3 from `STORAGE_ENDPOINT`. MemoryClient returns empty results on failure (graceful degradation). LLMClient raises `LLMUnavailableError` on gateway failure.

### agent-eval Pipeline (Core Business Logic)

Three layers maximize determinism:
1. **Layer 1 (Rules):** Deterministic checks (file_existence, freshness, schema_presence, row_count, null_rate, cross_reference, quantitative, keyword_presence) — resolves 60-70% of criteria with zero LLM cost
2. **Layer 2 (LLM Judgment):** Only for NEEDS_JUDGMENT items from Layer 1, bounded questions with rubric
3. **Layer 3 (Scoring):** Deterministic weighted formula with floor rules (policy FAIL caps at 0.84, >25% impl FAIL forces non_compliant)

Evidence hash caching: if evidence hasn't changed, return cached result (100% deterministic, zero cost).

## Key Patterns

- ALL external calls use `httpx.AsyncClient` (never `requests` in async context)
- Configuration via `pydantic_settings.BaseSettings` with env var defaults that work with docker-compose
- Every service has `/health` and `/ready` endpoints
- Structured JSON logging via `common.logger.AgentLogger` with trace_id correlation
- `common/` is COPY'd into each Docker image (not a pip package) — rebuild all images when common/ changes
- LLM Gateway config is a single YAML file (`config/routing.yaml`) with hot-reload

## Rules

- Never hardcode LLM provider names or model IDs in service code — use task-based routing
- Never use `boto3` directly — use `common/storage_client.py` abstraction
- Never skip security review before deploy
- Never use `print()` — use structured logger
- Never put business logic in route handlers — delegate to service layer
- Never use synchronous blocking in async context
- All services must handle graceful degradation (memory down = reduced context, not crash; storage down = hard failure)
- Tests required for all new code (unit minimum, integration preferred)

## Development Workflow

Skills in `.claude/skills/`:
- `/implement` — code implementation following project conventions
- `/build` — Docker image building
- `/test` — run tests (unit, integration, E2E with Playwright)
- `/security-review` — security audit before deploy
- `/deploy` — Docker Compose deployment
- `/ci-pipeline` — full pipeline orchestration
