# AI Agent System — Requirements

## System Overview

An autonomous AI compliance workforce built **AWS-first** with adapter-based decoupling for future on-prem/hybrid deployments. Every user gets a personal AI agent (Shadow AI) that does their compliance work for them — sends messages, collects evidence, evaluates controls, and coordinates with other users' agents. No compliance knowledge required from users.

This repo is the **AI layer only**. The broader platform handles GRC features (policy management, vendor risk, dashboards). The AI layer provides intelligent evaluation, assistance, and autonomous coordination.

## Platform Strategy

**AWS-first, adapter-decoupled.** V1 targets AWS (Bedrock, S3, RDS, ElastiCache). The adapter pattern in `common/` ensures the system can run on-prem or on other clouds by changing configuration — zero code changes, zero image rebuilds.

| Concern | AWS V1 | Adapter enables later |
|---------|--------|----------------------|
| LLM inference | Bedrock (Converse API) | Ollama, vLLM, Azure, GCP |
| Storage | S3 | MinIO, Azure Blob, GCS |
| Database | RDS PostgreSQL + pgvector | Local PostgreSQL |
| Cache | ElastiCache Redis | Local Redis |
| Embeddings | Titan Embed v2 | nomic-embed-text, OpenAI |
| OCR | Textract (with pdfplumber for digital PDFs) | Tesseract, Azure Doc Intelligence |

## Budget & Degradation

Per-tenant (customer) budget tracking ensures:
- One customer's credit exhaustion never affects other customers
- System degrades gracefully: rules-only evaluation, data-only assistant, queued requests
- Queued requests persist indefinitely and process automatically when budget resets
- No data loss, no hard failures — just reduced AI capability until credits return

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│  SHADOW AI AGENTS (one per user, personalized, inter-communicating) │
│  [CISO] ◄──► [CompMgr] ◄──► [Owners] ◄──► [IT/HR] ◄──► [Auditor] │
├─────────────────────────────────────────────────────────────────────┤
│                         AI Services                                   │
│  ┌──────────┐  ┌──────────────────┐  ┌──────────────┐              │
│  │agent-eval│  │compliance-assistant│  │ preprocessor │  (+ future) │
│  └────┬─────┘  └────┬─────────────┘  └──────┬───────┘              │
│       └──────────────┼───────────────────────┘                      │
│                      │                                               │
│  ┌───────────────────┴───────────────────────────────────────────┐  │
│  │              common/ (shared client libraries)                  │  │
│  │   LLMClient │ MemoryClient │ StorageClient │ StateClient      │  │
│  └───────────────────┬───────────────────────────────────────────┘  │
│                      │                                               │
│  ┌───────────────────┼───────────────────────────────────────────┐  │
│  │              Core Services                                     │  │
│  │  ┌──────────────┐ ┌────────────────┐ ┌─────────────────────┐ │  │
│  │  │ llm-gateway  │ │memory-service  │ │     observer        │ │  │
│  │  │  (routing,   │ │(state, skills, │ │  (self-tunes,       │ │  │
│  │  │  escalation, │ │ patterns, eval,│ │   self-governs,     │ │  │
│  │  │  7 providers)│ │ per-user ctx)  │ │   auto-improves)    │ │  │
│  │  └──────┬───────┘ └────────────────┘ └─────────────────────┘ │  │
│  └─────────┼─────────────────────────────────────────────────────┘  │
│            │                                                         │
│  ┌─────────┼─────────────────────────────────────────────────────┐  │
│  │         │        Infrastructure                                │  │
│  │  ┌──────▼──────┐  ┌──────────┐  ┌──────┐  ┌──────┐          │  │
│  │  │ LLM (local) │  │PostgreSQL│  │MinIO │  │Redis │          │  │
│  │  │ Ollama/vLLM │  │+ pgvector│  │      │  │      │          │  │
│  │  └─────────────┘  └──────────┘  └──────┘  └──────┘          │  │
│  └───────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

## Requirements Documents

### Architecture & Design

| Document | Covers |
|----------|--------|
| [aws-architecture.md](./aws-architecture.md) | **High-level design**: VPC, ECS Fargate, RDS, S3, Bedrock, networking, scaling, CI/CD |
| [security-auth-design.md](./security-auth-design.md) | **Security design**: Cognito, JWT, RBAC, S2S auth, multi-tenant isolation, encryption |
| [frameworks-modules-design.md](./frameworks-modules-design.md) | **Low-level design**: FastAPI, SQLAlchemy, structlog, per-module file structure, Dockerfiles |
| [deployment.md](./deployment.md) | Docker Compose, upgrades, profiles, air-gapped packaging |
| [observability.md](./observability.md) | Logging, PII-aware output, startup diagnostics, health checks, alerts |

### Service Requirements

| Document | Covers |
|----------|--------|
| [common-libraries.md](./common-libraries.md) | Shared client libraries (LLM, memory, storage, state, sandbox, logger) |
| [llm-gateway.md](./llm-gateway.md) | LLM routing, escalation, budget tracking, provider adapters |
| [memory-service.md](./memory-service.md) | Per-user memory, skills, patterns, eval history, audit trail |
| [agent-eval.md](./agent-eval.md) | 3-layer evaluation engine (rules + LLM judgment + scoring) |
| [compliance-assistant.md](./compliance-assistant.md) | Shadow AI agent — persona-based, skills/playbooks, regulatory monitoring |
| [observer.md](./observer.md) | Self-tuning, self-governing AI with graduated autonomy |
| [preprocessor.md](./preprocessor.md) | File ingestion (Excel/PDF/Word → structured metadata) |
| [sandbox-service.md](./sandbox-service.md) | Isolated code execution for data analysis |
| [agent-registry.md](./agent-registry.md) | Dynamic agent registration, capability discovery, health-aware routing |
| [mcp-server.md](./mcp-server.md) | MCP module on backend — tools/resources/prompts, feature-flagged |

## Key Design Principles

1. **Shadow AI per user** — every user gets a personal agent that acts on their behalf, zero compliance knowledge required
2. **Multi-agent coordination** — agents talk to each other to get work done collaboratively
3. **Agents are LLM-agnostic** — they declare tasks, not models
4. **Self-improving** — observer tunes the system daily without code deploys
5. **Self-governing** — the AI system audits itself (SR 11-7, EU AI Act compliance)
6. **Deterministic where possible** — 60-70% of evaluation is rule-based (free, instant, reproducible)
7. **Independent deployment** — each service has its own image and version
8. **Memory is shared** — no agent has private state, everything goes through memory service
9. **Simple ops** — Docker Compose, not K8s. One command to deploy, one line to upgrade.
10. **AWS-first, adapter-decoupled** — build for Bedrock/S3/RDS, swap via config for on-prem
11. **Graceful degradation on budget exhaustion** — per-tenant tracking, tier downgrade cascade, queue indefinitely, never crash
12. **Dynamic agent registry** — agents self-register capabilities on startup, enabling capability-based routing, version coexistence, and inter-agent discovery without hardcoded wiring

## Key Differentiators (vs. Vanta, Drata, IBM OpenPages)

- **Per-user AI agents** that act on behalf of users (no competitor has this)
- **Inter-agent coordination** — agents talk to each other to finish compliance fast
- **Zero platform knowledge required** — users just respond to plain-language messages
- **97-99% reproducible evaluations** — 3-layer pipeline (rules → bounded LLM → formula)
- **Self-tuning observer** — system improves daily without code deploys
- **Self-governing AI** — automated model governance reports for auditors
- **Never stops working** — graceful degradation on credit exhaustion (rules still run, data still accessible, queue for full eval)
- **Per-tenant budget isolation** — one customer's cost never impacts another
- **Air-gapped in under 1 hour** — Docker Compose, not 6-10 month OpenShift deployments
- **7 LLM providers** — swap models via YAML config, zero code changes

See [AI-COMPARISON.md](../AI-COMPARISON.md) for full competitive analysis.

## Requirements Traceability Matrix

Every system-level requirement maps to one or more modules. This matrix shows who implements what — use it to verify coverage during implementation and review.

| # | Requirement | common/ | llm-gateway | memory-service | agent-eval | compliance-assistant | observer | sandbox-service | preprocessor | MCP server | deployment |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | **LLM Agnostic** | LLMClient sends task name, never model | Resolves task→model via routing hierarchy | — | Declares task per node, zero model knowledge | Declares task per LLM call | Uses task="complex_reasoning" | — | Uses task="extract_schema" (optional) | — | — |
| 2 | **Storage Agnostic** | StorageClient adapter (S3/MinIO) | — | — | Reads/writes evidence via StorageClient | — | — | Downloads files via StorageClient | Reads/writes files via StorageClient | — | STORAGE_BACKEND env switches backend |
| 3 | **AWS-First w/ Adapters** | S3Adapter primary, MinIOAdapter for on-prem | BedrockAdapter primary, Anthropic/OpenAI fallback | RDS PostgreSQL + ElastiCache | — | — | — | — | Textract primary, Tesseract fallback | — | Profiles switch AWS vs local infra |
| 4 | **Per-Tenant Budget** | LLMCreditExhaustedError with metadata | Tracks cost/tenant, enforces ceiling, queues indefinitely | — | Partial eval mode on credit exhaustion | Data-only mode on credit exhaustion | Pauses on credit exhaustion, tracks events | — | — | — | Budget limits in routing.yaml |
| 5 | **Graceful Degradation** | Per-client degradation behavior defined | Fallback within tier, escalate, then queue | Store without embedding if LLM down | Rules-only if LLM down, cached if unchanged | Data-only mode if LLM/MCP down | Defers diagnosis if budget exceeded | Returns success=false on failure | Deterministic processing if LLM down | Returns 404 if feature disabled | Health checks gate readiness |
| 6 | **PII-Aware Logging** | AgentLogger: PII() wrapper, HMAC hash, regex redaction | Operational logs PII-free, prompt logging configurable | Audit trail stores full data (access-controlled) | Uses AgentLogger, all logs PII-free | Uses AgentLogger, all logs PII-free | Reads only aggregated metrics, no PII | Uses AgentLogger, all logs PII-free | Uses AgentLogger, all logs PII-free | Audit logs full data for accountability | PII_HMAC_KEY in secrets config |
| 7 | **Observability** | AgentLogger emits structured JSON + trace_id | Logs every request with full metrics | — | Emits per-node timing and LLM call logs | Emits tool execution and session metrics | Consumes all logs for analysis | Logs execution with resource stats | Logs processing events | — | /health, /ready, /diagnostics on all |
| 8 | **Security Isolation** | SandboxClient is sole code-exec interface | — | — | Generates code, never executes in-process | Never executes code | — | Ephemeral containers, no network, no secrets | — | — | Only sandbox gets Docker socket |
| 9 | **Self-Improving** | — | Admin API accepts routing/threshold updates | Stores versioned skills and patterns | — | Uses observer-updated skills/playbooks | Core: tunes routing, prompts, thresholds | — | — | — | Config volume shared for hot-reload |
| 10 | **Self-Governing (AI Risk)** | — | — | Stores governance reports | — | — | Generates model inventory, drift, bias reports | — | — | — | — |
| 11 | **Independent Deploy** | COPY'd into each image at build time | Own image: LLM_GW_VERSION | Own image: MEMORY_VERSION | Own image: EVAL_VERSION | Own image: CHAT_VERSION | Own image: OBSERVER_VERSION | Own image: SANDBOX_VERSION | Own image: PREPROC_VERSION | Ships with backend image | `up -d --no-deps {service}` |
| 12 | **Memory is Shared** | MemoryClient is sole interface | — | Single source of truth for all state | Reads/writes eval history, patterns, context | Reads/writes user memory, sessions | Reads/writes patterns, skills | — | Writes evidence-available facts | — | — |
| 13 | **Shadow AI per User** | — | — | Stores per-user preferences and behavior | — | Adopts persona per role, loads user context | — | — | — | Filters tools/resources by user role | — |
| 14 | **Deterministic First** | — | — | Evidence hash cache (100% deterministic) | 3-layer: rules first, LLM only for judgment | — | — | — | Deterministic parsing, LLM optional | — | — |
| 15 | **Skills & Playbooks** | — | — | Stores versioned skills (canary/active) | Fetches prompts from memory skills | Loads role-filtered skills + playbooks | Creates/updates via canary promotion | — | — | — | — |
| 16 | **Multi-Tenant Isolation** | — | Per-tenant rate limits and routing | tenant_id enforced, no cross-tenant reads | Scoped to tenant in all calls | Passes tenant JWT, never mixes | Admin scope only, no tenant data copy | — | Scoped to tenant file prefix | RBAC + scope checks on every call | — |
| 17 | **Human-in-the-Loop** | — | — | — | — | Shows confirmation for destructive actions | Tier 3 changes require human approval | — | — | confirmation_required flag per tool | — |
| 18 | **Hot-Reload Config** | — | File watcher + admin API, atomic swap | — | — | — | Triggers reload via admin API | — | — | — | routing.yaml mounted as volume |
| 19 | **Agent Registry** | RegistryClient (register, heartbeat, discover) | Resolves task→agent for delegation | Hosts registry table + heartbeat cache | Self-registers capabilities on startup | Self-registers, discovers other agents for inter-agent messaging | Reads topology, monitors canary health | Self-registers | Self-registers | — | REGISTRY_ENABLED env toggle |

### How to Read This Matrix

- **Rows** = system-level requirements that span multiple modules
- **Columns** = services/modules that implement parts of each requirement
- **"—"** = module does not participate in this requirement
- Each cell describes what that module's specific responsibility is
- During code review: verify that the module's implementation matches its cell
- During testing: each non-"—" cell needs at least one test case

### Cross-Reference to Module Requirements

Each cell in the matrix maps to specific requirement IDs in the module documents:

| System Requirement | Where to find the detailed spec |
|---|---|
| LLM Agnostic | common-libraries.md §1, llm-gateway.md R1-R4, agent-eval.md R1, compliance-assistant.md R1 |
| Storage Agnostic | common-libraries.md §3, agent-eval.md R2, preprocessor.md R1 |
| AWS-First w/ Adapters | common-libraries.md §Adapter Pattern, llm-gateway.md R17, preprocessor.md R2, deployment.md §Platform Strategy |
| Per-Tenant Budget | common-libraries.md §Error Hierarchy, llm-gateway.md R16, agent-eval.md R16, compliance-assistant.md R17, observer.md R18 |
| Graceful Degradation | common-libraries.md §Error Hierarchy, all service docs (degradation behavior per service) |
| PII-Aware Logging | common-libraries.md §6 (Logger), observability.md R6 |
| Observability | common-libraries.md §6, observability.md R1-R14, llm-gateway.md R9 |
| Security Isolation | common-libraries.md §5, sandbox-service.md R2/R6, agent-eval.md R12 |
| Self-Improving | observer.md R1-R10, llm-gateway.md R11, memory-service.md R4/R5 |
| Self-Governing | observer.md R16 |
| Independent Deploy | deployment.md §Version Management, all service docs §Container Packaging |
| Memory is Shared | common-libraries.md §2, memory-service.md R1-R7, agent-eval.md R4, compliance-assistant.md R5 |
| Shadow AI per User | compliance-assistant.md R0/R6, memory-service.md R2, mcp-server.md R5 |
| Deterministic First | agent-eval.md §3-Layer Pipeline (DESIGN.md), memory-service.md R5 (eval history hash) |
| Skills & Playbooks | compliance-assistant.md R6, memory-service.md R5, observer.md R9 |
| Multi-Tenant Isolation | memory-service.md R9, mcp-server.md R5, llm-gateway.md R12 |
| Human-in-the-Loop | compliance-assistant.md R7/R14, mcp-server.md R6, observer.md R5 (Tier 3) |
| Hot-Reload Config | llm-gateway.md R14, deployment.md §Directory Structure |
| Agent Registry | agent-registry.md R1-R16, common-libraries.md §RegistryClient, memory-service.md (registry routes) |

## Build Order (suggested)

1. `common/` — shared client libraries (everything depends on these)
2. `llm-gateway` — enables LLM-agnostic development of everything else
3. `memory-service` — enables shared state and per-user context
4. `backend + MCP module` — platform tool surface, needed by compliance-assistant
5. `sandbox-service` — code execution, needed by agent-eval
6. `agent-eval` — refactor from existing code, use new common libs
7. `compliance-assistant` — refactor from existing code, Shadow AI + inter-agent messaging
8. `preprocessor` — refactor from existing code
9. `observer` — needs gateway logs + memory to be operational; includes AI governance
10. `deployment/` — docker-compose.yml, configs, scripts
