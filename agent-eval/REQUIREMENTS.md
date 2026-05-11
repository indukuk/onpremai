# Agent: Evaluation Agent (agent-eval)

## Purpose

Stateful compliance evaluation engine. Takes evidence (structured + unstructured), evaluates it against regulatory controls, generates compliance assessments with gaps and recommendations.

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

### R7b: Testing Criteria per Control (Structured Evaluation Rubric)

**Problem:** Current RAG provides assessment objectives ("mechanisms exist to enforce access") but NOT explicit pass/fail conditions. The LLM doesn't know what "complete" means — so it always finds gaps even when evidence is sufficient.

**Solution:** Each control gets a structured **testing criteria** object that defines exactly what to check and how to score.

#### Testing Criteria Structure:

```json
{
  "chunk_type": "testing_criteria",
  "control_id": "CC6.1",
  "framework": "soc2",
  "control_objective": "Logical access to systems is restricted to authorized users",
  
  "criteria": [
    {
      "id": "TC-CC6.1-01",
      "category": "policy",
      "question": "Is there a documented access control policy?",
      "evidence_type": "document",
      "pass_condition": "Policy exists, approved, reviewed within 12 months, covers provisioning, de-provisioning, least privilege, review cadence",
      "fail_condition": "No policy, or >12 months old, or missing key sections",
      "weight": 0.15
    },
    {
      "id": "TC-CC6.1-02",
      "category": "procedure",
      "question": "Is there a provisioning/de-provisioning procedure?",
      "evidence_type": "document",
      "pass_condition": "Procedure defines: who approves, how granted, how removed on termination, SLA for removal",
      "fail_condition": "No procedure, or doesn't cover termination",
      "weight": 0.10
    },
    {
      "id": "TC-CC6.1-03",
      "category": "implementation",
      "question": "Are access reviews performed periodically?",
      "evidence_type": "structured_data",
      "pass_condition": "Review records exist for audit period, all users reviewed, reviewer identified, outcome recorded, cadence met",
      "fail_condition": "No records, or reviews missing for >1 period, or no action on findings",
      "weight": 0.25
    },
    {
      "id": "TC-CC6.1-04",
      "category": "implementation",
      "question": "Are terminated users removed promptly?",
      "evidence_type": "structured_data",
      "pass_condition": "Terminations cross-referenced with access removal: all removed within SLA (24h), no active accounts for terminated users",
      "fail_condition": "Terminated users still active, or removal >48h past SLA",
      "weight": 0.25
    },
    {
      "id": "TC-CC6.1-05",
      "category": "implementation",
      "question": "Is least privilege enforced?",
      "evidence_type": "structured_data",
      "pass_condition": "Access is role-based or justified, privileged access documented and approved",
      "fail_condition": "Admin/root without justification, no role-based model",
      "weight": 0.15
    },
    {
      "id": "TC-CC6.1-06",
      "category": "monitoring",
      "question": "Are unauthorized access attempts detected?",
      "evidence_type": "unstructured",
      "pass_condition": "Failed login monitoring exists, lockout policies in place, anomalies investigated",
      "fail_condition": "No monitoring, no investigation evidence",
      "weight": 0.10
    }
  ],
  
  "scoring": {
    "compliant": "Weighted score >= 0.85",
    "partially_compliant": "Weighted score 0.60 - 0.84",
    "non_compliant": "Weighted score < 0.60",
    "insufficient_evidence": "Cannot assess >= 50% of criteria weight"
  },
  
  "evidence_checklist": [
    {"type": "policy", "name": "Access Control Policy", "required": true},
    {"type": "procedure", "name": "Provisioning/De-provisioning Procedure", "required": true},
    {"type": "data", "name": "Periodic access review records", "required": true},
    {"type": "data", "name": "Termination → access removal records", "required": true},
    {"type": "data", "name": "Privileged access justification list", "required": false},
    {"type": "data", "name": "Failed login monitoring records", "required": false}
  ]
}
```

#### Criteria categories (apply to every control):

| Category | What it checks | Typical evidence |
|----------|---------------|-----------------|
| **policy** | Governing policy document exists and is current? | PDF/Word policy |
| **procedure** | Documented procedure for how to execute? | SOP/runbook |
| **implementation** | Control actually operating with data to prove it? | Records, logs, exports |
| **monitoring** | Ongoing monitoring of control effectiveness? | Dashboards, alerts |
| **review** | Periodic review/testing of the control? | Meeting minutes, test records |
| **exception** | Exceptions documented and approved? | Exception register |

#### How the evaluator uses criteria:

```python
# In evaluation node:
criteria = rag.get_testing_criteria(framework, control_id)

prompt = f"""
## Control: {control_id} — {criteria['control_objective']}

## Testing Criteria (evaluate EACH one):
{format_criteria(criteria['criteria'])}

## Evidence Provided:
{format_evidence(evidence_list)}

## Scoring:
{criteria['scoring']}

For EACH criterion:
- PASS: evidence satisfies pass_condition → explain briefly what you found
- FAIL: evidence shows fail_condition → cite specific data
- CANNOT_ASSESS: evidence is missing or insufficient for this criterion

Then calculate: overall weighted score, map to compliance status.

Output per-criterion results + overall status.
```

#### Why this fixes "never complete":

- **Before:** LLM invents its own criteria → always finds something to flag → never says "compliant"
- **After:** 6 explicit criteria with weights → checks each → weighted score ≥ 0.85 = compliant. Clear, deterministic, auditable.

#### Where criteria come from:

1. **SCF Assessment Objectives** (already in RAG) — restructure into criteria format
2. **AICPA SOC2 Points of Focus** — published testing guidance
3. **ISO 27002:2022** — implementation guidance per control
4. **NIST 800-53A** — assessment procedures
5. **Auditor feedback** — observer learns from real audit outcomes

#### RAG additions:

- New chunk type: `testing_criteria`
- New index: `_cache["by_criteria"]` = control_id → chunk index
- New API: `rag.get_testing_criteria(framework, control_id) -> dict`
- Stored alongside existing chunks in `chunks.json`

#### Observer improves criteria over time:

- Auditor rejects AI result → observer notes which criterion was wrong
- Evaluation says compliant but audit finds gap → criterion too lenient, observer tightens
- Criteria versioned in memory service (same as skills)
- New criteria can be added without agent redeploy

### R7c: Three-Layer Evaluation Pipeline (Automated Reasoning Mode)

The evaluation node uses a 3-layer pipeline to maximize determinism and reproducibility:

#### Layer 1: Deterministic Rule Checks (no LLM, instant, 100% reproducible)

For each criterion, attempt rule-based evaluation first:

| Check type | How it works | Example |
|-----------|--------------|---------|
| File existence | Evidence list contains matching file type/name | "Policy file with 'access' in name exists" |
| Freshness | File/record date < max age threshold | "Policy dated within 12 months" |
| Schema presence | Required columns exist in structured data | "Columns: reviewer, date, outcome present" |
| Row count threshold | Record count ≥ minimum | "1,523 access review records (min: 100)" |
| Null rate | Key columns populated ≥ threshold % | "reviewer column 99.8% populated" |
| Cross-reference | JOIN between datasets produces expected result | "0 terminated users in active access list" |
| Quantitative threshold | Calculated metric meets requirement | "Removal SLA: max 36h (threshold: 48h)" |
| Keyword presence | Document text contains required terms | "Policy mentions 'least privilege'" |

- **Result per criterion:** PASS, FAIL, or NEEDS_JUDGMENT
- Criteria resolved by rules: ~60-70% of all criteria
- Zero LLM cost for these checks
- 100% reproducible: same evidence → same result, always

#### Layer 2: LLM Judgment (only for NEEDS_JUDGMENT items)

The LLM is called ONLY for criteria that require reading comprehension or qualitative assessment:

- Receives a **specific, bounded question** (not "evaluate this control")
- Gets the **exact evidence text** relevant to that one criterion
- Gets an **anchored rubric** with PASS/FAIL examples
- Must output **categorical result** (PASS / PARTIAL / FAIL) + one-sentence reason
- Temperature: 0
- Optional: 3-sample consensus for criteria with weight > 0.20

```
Example LLM judgment call:

Question: "Does this access control policy adequately cover: (a) access provisioning, 
(b) de-provisioning on termination, (c) least privilege principle, (d) periodic review cadence?"

Evidence: [first 5000 chars of the policy document]

PASS example: "Policy has dedicated sections for provisioning (Section 4), de-provisioning 
with 24h SLA (Section 5), RBAC model for least privilege (Section 6), and quarterly 
review requirement (Section 7)."

FAIL example: "Policy mentions access control generally but has no section on de-provisioning, 
does not define review cadence, and does not mention least privilege."

Output format: {result: "PASS|PARTIAL|FAIL", reason: "one sentence"}
```

#### Layer 3: Deterministic Score Calculation (formula, no LLM)

```python
score = sum(criterion.weight * score_value[result] for all criteria) / total_assessable_weight

# score_value: PASS=1.0, PARTIAL=0.5, FAIL=0.0
# total_assessable_weight excludes CANNOT_ASSESS criteria

# Floor rules (override):
if any policy criterion is FAIL: cap score at 0.84 (partially_compliant max)
if >25% of implementation criteria FAIL: force non_compliant
if cannot_assess weight >= 50%: insufficient_evidence (regardless of other scores)

# Threshold mapping (fixed, deterministic):
score >= 0.85 → compliant
score 0.60-0.84 → partially_compliant  
score < 0.60 → non_compliant
```

#### Anti-flapping rule:

- If evidence hash unchanged from last evaluation → return cached result (100% deterministic)
- If evidence changed → re-evaluate only criteria affected by changed files
- Score can only change direction if underlying evidence changed

#### Reproducibility guarantee:

| Component | Deterministic? | Reproducibility |
|-----------|:-:|:-:|
| Layer 1 (rules) | Yes | 100% |
| Layer 2 (LLM, temp=0, categorical) | Nearly | ~97% |
| Layer 3 (formula) | Yes | 100% |
| Overall system | — | ~97-99% |
| With evidence hash caching | Yes | 100% |

#### When to skip Layer 2 entirely:

If all criteria resolve in Layer 1 (all PASS or all FAIL), the LLM is never called. This happens for:
- Controls with only quantitative requirements (data-heavy controls like CC8.1)
- Obvious failures (no evidence uploaded at all)
- Re-evaluations where evidence hasn't changed (cached)

This means many evaluations complete with ZERO LLM calls — instant, free, and perfectly reproducible.

### R7d: Execution Modes

Agent-eval evaluates ONE control per request. Always. Batch coordination lives outside.

#### Mode 1: Single Control (interactive, user-triggered)

- Triggered by: compliance-assistant (user says "evaluate CC6.1")
- Input: `{control_id, framework, tenant_id}`
- Agent discovers evidence, evaluates, returns result
- Result state: **DRAFT** (until user confirms in chat → APPROVED)
- Latency: 30-45s (user is watching)

#### Mode 2: Batch (full framework sweep)

- Triggered by: compliance-assistant ("evaluate all SOC2") or scheduler (nightly)
- **Orchestrated by compliance-assistant or a batch-manager** — NOT by agent-eval
- Orchestrator:
  1. Gets all controls for the framework
  2. Dispatches N concurrent requests to agent-eval (default concurrency: 5)
  3. Tracks progress in memory-service batch job table
  4. Reports completion to user
- Each individual evaluation is the same single-control request
- All results land as **DRAFT** — user reviews exceptions → APPROVED
- Latency: ~10 min for 40 controls at concurrency=5

#### Mode 3: Continuous (evidence-triggered)

- Triggered by: preprocessor event (new evidence uploaded) or scheduler (evidence stale)
- Orchestrator sends single-control evaluation request to agent-eval
- Result replaces previous DRAFT (or creates new DRAFT if prior was APPROVED)
- Notifies user: "CC6.1 re-evaluated with new evidence: status changed from partial → compliant"
- No user action needed unless status degraded

#### Batch API (on compliance-assistant or batch-manager, NOT on agent-eval):

```
POST /evaluate-batch
  body: {framework, tenant_id, controls: [...] | "all", concurrency: 5}
  response: {batch_id, total: 40, status: "running"}

GET /batch-status/{batch_id}
  response: {
    batch_id, status: "running",
    total: 40, completed: 28, failed: 1,
    results_summary: {compliant: 20, partial: 6, non_compliant: 2},
    failures: [{control: "CC9.1", error: "timeout"}]
  }
```

#### Agent-eval API (unchanged — always single control):

```
POST /evaluate
  body: {control_id, framework, tenant_id}
  response: {job_id}

GET /status/{job_id}
  response: {status: "completed", evaluation: {...}}
```

### R7e: Evaluation Lifecycle & Human Override

Every evaluation has a lifecycle. Human overrides are stored in a **separate database** (evaluation-decisions DB) from the AI results.

#### Lifecycle states:

```
AI evaluates → DRAFT → human reviews → APPROVED
                  ↓                        ↓
              (auto-replaced            (locked — new eval
               by re-evaluation)         creates new DRAFT)
```

| State | Meaning | Who can see | Editable |
|-------|---------|-------------|----------|
| `draft` | AI produced this, not yet human-validated | Compliance mgr, admin | Yes |
| `approved` | Human confirmed (with or without changes) | Everyone, auditors | No (new eval creates new draft) |
| `superseded` | A newer evaluation replaced this one | Audit trail only | No |

#### Two databases — separation of concerns:

**1. AI Evaluation Store (memory-service `eval_history` table):**
- What the AI produced — raw, unmodified, immutable per evaluation
- Per-criterion results as the AI determined them
- AI score, AI status
- Model used, tier, latency, confidence
- Evidence hash at time of evaluation
- This is the "machine record" — never edited by humans

**2. Human Decisions Store (separate `evaluation_decisions` table on backend DB):**
- Human overrides, edits, approvals per evaluation
- Links to AI evaluation by `evaluation_id`
- Per-criterion: override result, reason, who, when
- Final score (after human adjustments)
- Final status (after human adjustments)
- Approval: who approved, when, any notes
- This is the "human record" — the auditable decision layer

```sql
-- evaluation_decisions (on backend/platform DB, NOT in memory-service)
CREATE TABLE evaluation_decisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    evaluation_id UUID NOT NULL,          -- links to AI eval in memory-service
    tenant_id TEXT NOT NULL,
    control_id TEXT NOT NULL,
    framework TEXT NOT NULL,
    
    -- Lifecycle
    status TEXT NOT NULL DEFAULT 'draft', -- draft | approved | superseded
    approved_by TEXT,                     -- user_id who approved
    approved_at TIMESTAMPTZ,
    
    -- Human overrides (per criterion)
    overrides JSONB DEFAULT '[]',
    -- [{criterion_id, ai_result, final_result, reason, overridden_by, overridden_at}]
    
    -- Final scores (after human adjustments)
    ai_score FLOAT NOT NULL,
    ai_status TEXT NOT NULL,
    final_score FLOAT NOT NULL,           -- = ai_score unless overrides change it
    final_status TEXT NOT NULL,           -- = ai_status unless overrides change it
    
    -- Metadata
    notes TEXT,                           -- reviewer notes
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_eval_decisions_tenant ON evaluation_decisions(tenant_id, framework, control_id);
CREATE INDEX idx_eval_decisions_status ON evaluation_decisions(tenant_id, status);
```

#### Why separate databases:

1. **AI results are immutable** — you never edit what the AI said. You record your disagreement separately.
2. **Audit trail is clean** — auditor sees: "AI said X, human decided Y, because Z"
3. **Re-evaluation doesn't lose human decisions** — AI can re-run, new draft created, previous human decisions preserved in history
4. **Different owners** — AI evaluation store is memory-service (agents write). Human decisions store is backend DB (MCP/frontend writes).
5. **Different access patterns** — AI store is read-heavy by agents. Human store is read-heavy by auditors/UI.

#### How the override flow works:

```
1. AI evaluates CC6.1 → stores in memory-service (eval_history)
   evaluation_id: "eval-001"
   ai_score: 0.78, ai_status: "partially_compliant"
   criteria_results: [{TC-04: PARTIAL}, {TC-06: FAIL}, ...]

2. Frontend/compliance-assistant creates decision record:
   INSERT evaluation_decisions (evaluation_id: "eval-001", 
     ai_score: 0.78, ai_status: "partially_compliant",
     final_score: 0.78, final_status: "partially_compliant",
     status: "draft")

3. User reviews in UI or chat — overrides TC-04 and TC-06:
   UPDATE evaluation_decisions SET
     overrides = [
       {criterion: "TC-04", ai_result: "PARTIAL", final_result: "PASS",
        reason: "Contractor SLA is 72h per policy", overridden_by: "sarah"},
       {criterion: "TC-06", ai_result: "FAIL", final_result: "PASS",
        reason: "SIEM monitoring active, evidence upload pending", overridden_by: "sarah"}
     ],
     final_score = 0.93,
     final_status = "compliant"

4. User approves:
   UPDATE evaluation_decisions SET
     status = "approved",
     approved_by = "sarah",
     approved_at = NOW()

5. Platform shows: final_status ("compliant") to everyone
   Auditor can drill in: sees AI said "partial", human overrode 2 criteria with reasons
```

#### What each system sees:

| Consumer | Reads from | Shows |
|----------|-----------|-------|
| **Compliance-assistant** (chat) | evaluation_decisions | final_status, final_score |
| **Dashboard/UI** | evaluation_decisions | final_status + progress bars |
| **Auditor** | evaluation_decisions + eval_history | AI result vs human decision, full trail |
| **Observer** | eval_history (memory-service) | AI performance, never sees human overrides |
| **Readiness %** | evaluation_decisions | Only counts APPROVED evaluations |

#### MCP tools for human override:

```yaml
tools:
  - evaluation.get_draft:
      description: "Get current draft evaluation for a control (AI result + any pending overrides)"
      params: {control_id, framework}

  - evaluation.override_criterion:
      description: "Override AI result for a specific criterion with human judgment"
      params: {evaluation_id, criterion_id, new_result, reason}
      confirmation_required: false  # not destructive, just an edit

  - evaluation.approve:
      description: "Approve evaluation (with or without overrides) as the official result"
      params: {evaluation_id, notes}
      confirmation_required: true  # makes it official

  - evaluation.bulk_approve:
      description: "Approve multiple evaluations at once (for batch review)"
      params: {evaluation_ids: [...], notes}
      confirmation_required: true
```

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
# Environment variables (all have defaults for local dev)
LLM_GATEWAY_URL: http://llm-gateway:4000
MEMORY_URL: http://memory-service:5000
STORAGE_ENDPOINT: http://minio:9000
STORAGE_BUCKET: compliance-artifacts
STATE_BACKEND: postgres          # postgres | dynamodb
STATE_DSN: postgresql://user:pass@postgres:5432/compliance
PREPROCESSOR_URL: http://preprocessor:7000
SANDBOX_URL: http://sandbox-service:9000
LOG_LEVEL: info
MAX_EVAL_TIMEOUT_SEC: 300
MAX_SANDBOX_RETRIES: 2
RAG_INDEX_PATH: /data/rag/       # local mount or fetched from storage on startup
```

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
