# Agent: Evaluation Agent (agent-eval)

## Purpose

Stateful compliance evaluation engine. Takes evidence (structured + unstructured), evaluates it against regulatory controls, generates compliance assessments with gaps and recommendations.

## System Requirements Covered

| System Requirement | This module's role | Requirement ID |
|---|---|---|
| LLM Agnostic | Declares task per graph node, zero model knowledge | R1 |
| Storage Agnostic | All evidence I/O via StorageClient | R2 |
| Per-Tenant Budget | Partial evaluation mode (rules-only) on credit exhaustion | R16 |
| Graceful Degradation | Rules-only if LLM down, cached if evidence unchanged | R4, R16 |
| PII-Aware Logging | All logs via AgentLogger, PII-free operational output | R6 |
| Observability | Per-node timing, LLM call logs, trace_id propagation | R6 |
| Security Isolation | Generates code, delegates to sandbox, never runs in-process | R12 |
| Memory is Shared | Reads/writes eval history, patterns, tenant context | R4 |
| Deterministic First | 3-layer pipeline: rules → LLM judgment → scoring formula | R10 |
| Skills & Playbooks | Fetches prompt templates from memory service | R5 |
| Multi-Tenant Isolation | Scoped to tenant_id in all memory/storage calls | R4 |
| Independent Deploy | Own image, EVAL_VERSION tag | R8 |

## Current State (what exists in /Users/indukuk/compliance)

- LangGraph-based graph with 12 nodes: router → discovery → confirmation → extractor → evaluation → sandbox → code_fixer → storage → query → formatter → chat_respond
- Hardcoded to AWS Bedrock (`ChatBedrock`, `us.anthropic.claude-3-5-haiku`)
- RAG v2 with cross-framework mappings (SCF → SOC2/SOX/NIST/ISO)
- Code sandbox for structured data analysis (generates + executes Python)
- DynamoDB for session state, S3 for evidence storage
- Async execution pattern (start → poll → complete)

## Requirements for On-Prem/Hybrid

### R1: LLM Agnostic

- MUST NOT import any provider-specific library (no `langchain_aws`, no `ChatBedrock`, no `boto3` for Bedrock)
- MUST use `common.llm_client.LLMClient` for all LLM calls
- MUST declare task type on each call (e.g., `task="evaluate_control"`, `task="classify_intent"`)
- MUST declare confidence threshold where escalation is appropriate
- Agent has zero knowledge of which model or provider handles the request

### R2: Storage Agnostic

- MUST NOT use boto3 S3 client directly
- MUST use `common.storage_client.StorageClient` that abstracts S3/MinIO/local filesystem
- Evidence read/write, RAG index loading, evaluation result storage all go through this client
- Configuration: single env var `STORAGE_ENDPOINT` (MinIO on-prem, S3 in cloud)

### R3: State Store Agnostic

- MUST NOT use DynamoDB directly for session state
- MUST use `common.state_client.StateClient` that abstracts DynamoDB/PostgreSQL/Redis
- Session tracking, evidence hashing, job status all go through this client
- On-prem: PostgreSQL. Cloud: DynamoDB or PostgreSQL.

### R4: Memory Integration

- MUST call `memory.eval_last()` before running evaluation (check for cached result)
- MUST call `memory.eval_store()` after successful evaluation
- MUST call `memory.tenant_recall()` to get tenant-specific context for prompts
- MUST call `memory.pattern_query()` to get learned patterns for the task
- SHOULD call `memory.tenant_remember()` when new facts about tenant are discovered during evaluation
- Memory service URL via env var `MEMORY_URL`

### R5: Skill/Prompt Fetching

- Prompt templates MUST NOT be hardcoded in source
- MUST fetch current prompt version from memory service: `memory.skill_get("prompt/{task}")`
- Fallback: if memory service is unreachable, use built-in default prompts (bundled at build time)
- Observer can update prompts without agent redeploy

### R6: Observability

- Every LLM call MUST emit a structured log entry: `{trace_id, agent, task, tier_requested, latency_ms, confidence, success, tenant_id, context}`
- These logs are consumed by the observer for optimization
- MUST propagate `trace_id` through all calls for end-to-end tracing
- MUST report timing per graph node (already exists as POCLogger, needs adapting)

### R7: Embedding Agnostic

- RAG v2 embedding generation MUST use `LLMClient.embed()` (not Amazon Titan directly)
- Embedding model chosen by LLM gateway config, not by agent
- On-prem: nomic-embed-text via Ollama. Cloud: Amazon Titan or OpenAI embeddings.

### R8: Container Packaging

- Single Docker image, independently versioned
- Version tag: `EVAL_VERSION` env var in docker-compose
- Health check endpoint: `GET /health`
- Readiness endpoint: `GET /ready` (true when RAG index loaded)
- Graceful shutdown on SIGTERM (finish in-progress evaluation)
- Max memory: configurable, default 2GB
- No GPU required (all inference via LLM gateway)

### R9: API Contract

- HTTP API (not Lambda-specific)
- Endpoints:
  - `POST /evaluate` — start async evaluation, returns `{job_id, status: "processing"}`
  - `GET /status/{job_id}` — poll for result
  - `POST /chat` — synchronous chat about compliance
  - `GET /health` — container health
  - `GET /ready` — readiness (RAG loaded)
- Input/output format unchanged from V3 (backward compatible with existing frontend)

### R10: Graph Structure (unchanged logic, new wiring)

```
router → discovery → confirmation → extractor → evaluation → sandbox → code_fixer → storage → formatter
                                              ↘ query → sandbox_query → formatter
                                              ↘ chat_respond
```

- All nodes use `LLMClient` instead of `ChatBedrock`
- All nodes use `StorageClient` instead of boto3
- All nodes use `MemoryClient` for context enrichment

### R11: Evaluation Task Types (for LLM gateway routing)

| Task declared by agent | Typical tier | Purpose |
|------------------------|:---:|---------|
| `classify_intent` | fast | Router: classify user message |
| `discover_evidence` | fast | Match files to controls |
| `extract_schema` | fast | Analyze file structure |
| `evaluate_control` | mid | Core evaluation logic |
| `evaluate_unstructured` | mid | PDF/doc evaluation |
| `generate_code` | mid | Python code for data analysis |
| `fix_code` | mid | Fix sandbox errors |
| `cross_framework_analysis` | strong | Complex multi-framework reasoning |
| `chat_response` | fast | Answer user questions |
| `format_results` | fast | Format evaluation output |
| `summarize_evidence` | fast | Summarize a single evidence document |
| `regulatory_impact_analysis` | mid | Map regulatory changes to affected controls |

### R12: Code Sandbox Integration

- Sandbox is a **separate service** (`sandbox-service`) — see [sandbox-service.md](./sandbox-service.md)
- Any agent can submit code for execution via HTTP
- Agent-eval's `sandbox` node calls: `POST http://sandbox-service:9000/execute`
- Agent sends: `{code, files: [{key, type}], timeout_sec}`
- Agent receives: `{stdout, stderr, success, duration_ms}`
- Agent-eval responsibilities:
  - Generate the Python code (via LLM)
  - Tell sandbox which evidence files to load (by storage key)
  - Interpret results from stdout
  - Retry on failure (via code_fixer node)
- Agent does NOT manage sandbox lifecycle, isolation, or file loading — that's the service's job

### R13: Preprocessor Integration

- When extractor finds no `metadata.json` for evidence: call preprocessor service via HTTP
- `POST http://preprocessor:7000/process` with `{storage_key: "..."}`
- Preprocessor processes file, writes metadata.json back to storage
- Extractor retries loading metadata after preprocessor responds
- If preprocessor is unavailable: fall back to inline extraction (basic schema detection from file bytes)
- This replaces the current `boto3.client("lambda").invoke(FunctionName=preprocessor)` pattern

### R14: Handler (HTTP server, not Lambda)

- Replace Lambda event format with standard HTTP server (FastAPI recommended)
- Async evaluation pattern:
  - `POST /evaluate` starts a background task (threading or asyncio)
  - Writes job status to `StateClient` (processing → completed/failed)
  - `GET /status/{job_id}` reads from `StateClient`
- Evidence hashing for incremental re-evaluation: keep logic, use `StateClient` for hash storage
- Session management: use `MemoryClient.session_get/update` instead of DynamoDB direct

### R15: Configuration

```yaml
# Environment variables (AWS-first defaults)
LLM_GATEWAY_URL: http://llm-gateway:4000
MEMORY_URL: http://memory-service:5000
STORAGE_BACKEND: s3                      # s3 | minio
STORAGE_BUCKET: compliance-artifacts
AWS_REGION: us-east-1
STATE_BACKEND: postgres
STATE_DSN: postgresql://compliance:${DB_PASSWORD}@${DB_HOST}:5432/compliance
PREPROCESSOR_URL: http://preprocessor:7000
SANDBOX_URL: http://sandbox-service:9000
LOG_LEVEL: info
MAX_EVAL_TIMEOUT_SEC: 300
MAX_SANDBOX_RETRIES: 2
RAG_INDEX_PATH: s3://compliance-artifacts/rag-kb/v2/  # S3 path, fetched on startup
```

### R16: Credit Exhaustion — Partial Evaluation Mode

When LLM gateway returns `LLMCreditExhaustedError`, agent-eval does NOT fail. It falls back to **rules-only evaluation**:

#### Behavior:

```python
async def evaluate_control(request: EvalRequest) -> EvalResult:
    # Layer 1 always runs (deterministic, zero LLM cost)
    layer1_results = await run_rule_engine(request.evidence, request.criteria)
    
    needs_judgment = [c for c in layer1_results if c.status == "NEEDS_JUDGMENT"]
    
    if not needs_judgment:
        # 100% deterministic — no LLM needed regardless of budget
        return score_and_return(layer1_results, partial=False)
    
    try:
        # Layer 2: attempt LLM judgment
        layer2_results = await run_llm_judgment(needs_judgment, request)
        return score_and_return(layer1_results + layer2_results, partial=False)
    except LLMCreditExhaustedError as e:
        # Mark NEEDS_JUDGMENT criteria as "insufficient_evidence" (not pass, not fail)
        degraded_results = mark_as_insufficient(needs_judgment)
        result = score_and_return(layer1_results + degraded_results, partial=True)
        result.metadata.update({
            "partial_evaluation": True,
            "llm_skipped": True,
            "degradation_level": e.degradation_level,
            "criteria_resolved_by_rules": len(layer1_results) - len(needs_judgment),
            "criteria_needing_llm": len(needs_judgment),
            "queued_for_full_eval": e.can_queue,
            "queue_position": e.queued_position,
        })
        return result
```

#### What the user sees:

```json
{
  "control_id": "CC6.1",
  "status": "partial_evaluation",
  "confidence": 0.65,
  "partial_evaluation": true,
  "resolved_criteria": 7,
  "pending_criteria": 3,
  "message": "7 of 10 criteria evaluated by rules. 3 criteria require AI judgment — queued for processing when budget is available.",
  "rule_based_score": 0.78,
  "estimated_full_score_range": [0.70, 0.90]
}
```

#### Scoring in partial mode:

- Only deterministic criteria contribute to score
- Score is marked as provisional — will be updated when queue drains
- Floor rules still apply (policy FAIL still caps at 0.84)
- Result stored in eval_history with `partial=True` flag
- When queue drains and full evaluation completes: result is updated, user notified

---

## Code Reuse Map

Files from existing codebase (`/Users/indukuk/compliance/src/agent/`) and reuse status:

| File | Reuse % | Action |
|------|:-------:|--------|
| `graph.py` | 100% | Copy as-is |
| `state.py` | 100% | Copy as-is |
| `confirmation.py` | 100% | Copy as-is |
| `formatter.py` | 100% | Copy as-is |
| `usage.py` | 90% | Copy, minor cleanup |
| `controls.py` | 90% | Copy, load from storage on startup |
| `rag_v2.py` | 85% | Replace boto3 S3 → StorageClient, Titan embed → LLMClient.embed() |
| `router.py` | 80% | Replace ChatBedrock → LLMClient, keep all heuristic/regex logic |
| `evaluation.py` | 75% | Replace ChatBedrock → LLMClient, add memory calls, keep prompts+flow |
| `query.py` | 75% | Replace ChatBedrock → LLMClient, keep prompts |
| `chat.py` | 70% | Replace ChatBedrock → LLMClient, keep context building |
| `discovery.py` | 70% | Replace boto3 S3 → StorageClient, keep fuzzy matching |
| `code_fixer.py` | 90% | Replace ChatBedrock → LLMClient, keep prompt |
| `extractor.py` | 60% | Replace boto3 → StorageClient, replace Lambda invoke → HTTP, keep metadata logic |
| `storage.py` | 60% | Replace boto3 → StorageClient+StateClient, replace ChatBedrock → LLMClient |
| `sandbox.py` | 40% | Rewrite: AgentCore → HTTP call to sandbox-service. Keep retry logic, drop execution code |
| `handler_v2/v3.py` | 50% | Rewrite: Lambda → FastAPI. Keep evaluation start/poll/chat logic |
| `config.py` | 0% | Rewrite with new env vars |
| `logger.py` | 80% | Adapt to common.logger interface, keep structured format |

### Prompts (all reusable as-is)
- `DEFAULT_ANALYSIS_PROMPT` (evaluation.py)
- `DEFAULT_CODE_PROMPT` (evaluation.py)
- `UNSTRUCTURED_EVAL_PROMPT` (evaluation.py)
- `FINALIZE_PROMPT` (storage.py)
- `FIX_CODE_PROMPT` (code_fixer.py)
- `QUERY_DATA_PROMPT` (query.py)
- `QUERY_RESULTS_PROMPT` (query.py)
- `CHAT_SYSTEM_PROMPT` (chat.py)
- `ROUTER_PROMPT` (router.py)

These will initially be hardcoded (as they are today) with a plan to move into memory-service skills once the observer is operational.
