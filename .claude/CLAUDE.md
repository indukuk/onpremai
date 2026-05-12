# On-Prem AI Agent System for Compliance

## Project Overview

This is a hybrid on-prem/cloud AI agent system for compliance SaaS. It deploys as Docker Compose and connects to any LLM (local or cloud).

## Architecture

8 services, each independently deployable:
- `compliance-assistant` — user-facing AI (persona-based, skills/playbooks)
- `agent-eval` — compliance evaluation engine (3-layer deterministic pipeline)
- `llm-gateway` — model routing, escalation, provider adapters
- `memory-service` — shared memory (user/tenant/task/eval/patterns/skills)
- `observer` — autonomous improvement agent
- `sandbox-service` — isolated code execution
- `preprocessor` — file ingestion (Excel/PDF/Word → metadata)
- `common/` — shared client libraries

## Tech Stack

- Python 3.11+, FastAPI, Pydantic
- PostgreSQL + pgvector, Redis
- Docker, Docker Compose
- MinIO (S3-compatible storage)
- LLMs: Ollama/vLLM (local) or Anthropic/OpenAI (cloud)

## Key Patterns

- Agents use `common/llm_client.py` for ALL LLM calls (never import provider SDKs)
- Agents use `common/memory_client.py` for ALL memory operations
- Agents use `common/storage_client.py` for ALL file operations
- Configuration via environment variables with docker-compose defaults
- Every service has `/health` and `/ready` endpoints
- Structured JSON logging with trace_id correlation

## Directory Structure

Each service has:
- `REQUIREMENTS.md` — what to build
- `DESIGN.md` — architecture with mermaid diagrams
- `src/` — implementation (when built)
- `tests/` — unit + integration tests
- `Dockerfile` — container definition

## Development Workflow

Use the skills in `.claude/skills/`:
- `/implement` — code implementation following project conventions
- `/build` — Docker image building
- `/test` — run tests (unit, integration, E2E)
- `/security-review` — security audit before deploy
- `/deploy` — Docker Compose deployment
- `/ci-pipeline` — full pipeline orchestration

## Rules

- Never hardcode LLM provider names or model IDs in service code
- Never use `boto3` directly — use common/ abstractions
- Never skip security review before deploy
- All services must log structured JSON with startup sequence
- All services must handle graceful degradation (memory down ≠ crash)
- Tests required for all new code (unit minimum, integration preferred)
