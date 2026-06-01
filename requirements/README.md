# On-Prem AI Agent System — Requirements

## System Overview

An autonomous AI compliance workforce that deploys on-prem, in the cloud, or hybrid. Every user gets a personal AI agent (Shadow AI) that does their compliance work for them — sends messages, collects evidence, evaluates controls, and coordinates with other users' agents. No compliance knowledge required from users.

This repo is the **AI layer only**. The broader platform handles GRC features (policy management, vendor risk, dashboards). The AI layer provides intelligent evaluation, assistance, and autonomous coordination.

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

| Document | Covers |
|----------|--------|
| [agent-eval.md](./agent-eval.md) | 3-layer evaluation engine (deterministic rules + LLM judgment + scoring) |
| [compliance-assistant.md](./compliance-assistant.md) | Shadow AI agent — per-user, persona-based, skills/playbooks, inter-agent coordination, regulatory monitoring, evidence summarization |
| [llm-gateway.md](./llm-gateway.md) | LLM routing (7 providers), escalation, canary testing, cost control |
| [memory-service.md](./memory-service.md) | Per-user memory, skills, patterns, eval history |
| [observer.md](./observer.md) | Self-tuning, self-governing AI with graduated autonomy + AI model risk governance |
| [preprocessor.md](./preprocessor.md) | File ingestion (Excel/PDF/Word → structured metadata) |
| [sandbox-service.md](./sandbox-service.md) | Isolated code execution for data analysis |
| [mcp-server.md](./mcp-server.md) | MCP module on backend — tools/resources/prompts, feature-flagged |
| [common-libraries.md](./common-libraries.md) | Shared client libraries (LLM, memory, storage, state, sandbox) |
| [observability.md](./observability.md) | Logging, startup diagnostics, failure correlation, health checks |
| [deployment.md](./deployment.md) | Docker Compose, upgrades, air-gapped packaging |

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
10. **Works anywhere** — air-gapped on-prem, hybrid, or full cloud

## Key Differentiators (vs. Vanta, Drata, IBM OpenPages)

- **Per-user AI agents** that act on behalf of users (no competitor has this)
- **Inter-agent coordination** — agents talk to each other to finish compliance fast
- **Zero platform knowledge required** — users just respond to plain-language messages
- **97-99% reproducible evaluations** — 3-layer pipeline (rules → bounded LLM → formula)
- **Self-tuning observer** — system improves daily without code deploys
- **Self-governing AI** — automated model governance reports for auditors
- **Air-gapped in under 1 hour** — Docker Compose, not 6-10 month OpenShift deployments
- **7 LLM providers** — swap models via YAML config, zero code changes

See [AI-COMPARISON.md](../AI-COMPARISON.md) for full competitive analysis.

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
