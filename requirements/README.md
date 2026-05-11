# On-Prem AI Agent System — Requirements

## System Overview

A compliance SaaS platform with AI agents that deploy on-prem, in the cloud, or hybrid. Agents connect to any LLM (local or remote) without knowing which model they're using.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Agents                                       │
│  ┌──────────┐  ┌──────────┐  ┌──────────────┐                      │
│  │agent-eval│  │compliance-assistant│  │ preprocessor │  ... (future agents) │
│  └────┬─────┘  └────┬─────┘  └──────┬───────┘                      │
│       └──────────────┼───────────────┘                              │
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
│  │  │  (routing,   │ │(state, skills, │ │  (watches, learns,  │ │  │
│  │  │  escalation) │ │ patterns, eval)│ │   auto-improves)    │ │  │
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
| [agent-eval.md](./agent-eval.md) | Compliance evaluation agent (LangGraph) |
| [compliance-assistant.md](./compliance-assistant.md) | Compliance program manager agent — proactive, goal-driven, guides users to audit readiness |
| [llm-gateway.md](./llm-gateway.md) | LLM routing, escalation, cost control |
| [memory-service.md](./memory-service.md) | Shared memory, skills, patterns |
| [observer.md](./observer.md) | Auto-improvement agent with graduated autonomy |
| [preprocessor.md](./preprocessor.md) | File ingestion and processing |
| [sandbox-service.md](./sandbox-service.md) | Isolated code execution for any agent |
| [mcp-server.md](./mcp-server.md) | MCP module on backend — tools/resources/prompts, feature-flagged |
| [common-libraries.md](./common-libraries.md) | Shared client libraries (LLM, memory, storage) |
| [observability.md](./observability.md) | Logging, startup diagnostics, failure correlation, health checks |
| [deployment.md](./deployment.md) | Docker Compose architecture, upgrades, air-gap |

## Key Design Principles

1. **Agents are LLM-agnostic** — they declare tasks, not models
2. **Independent deployment** — each agent has its own image and version
3. **Observer improves the system** — without code deploys, with safety guardrails
4. **Memory is shared** — no agent has private state, everything goes through memory service
5. **Simple ops** — Docker Compose, not K8s. One command to deploy, one line to upgrade.
6. **Works anywhere** — air-gapped on-prem, hybrid, or full cloud

## Build Order (suggested)

1. `common/` — shared client libraries (everything depends on these)
2. `llm-gateway` — enables LLM-agnostic development of everything else
3. `memory-service` — enables shared state
4. `backend + MCP module` — platform tool surface, needed by compliance-assistant
5. `sandbox-service` — code execution, needed by agent-eval
6. `agent-eval` — refactor from existing code, use new common libs
7. `compliance-assistant` — refactor from existing code, now an MCP client
8. `preprocessor` — refactor from existing code
9. `observer` — needs gateway logs + memory to be operational
10. `deployment/` — docker-compose.yml, configs, scripts
