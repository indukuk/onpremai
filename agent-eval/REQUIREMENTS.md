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

#### Layer 2: Adversarial Tribunal (only for NEEDS_JUDGMENT items)

The LLM is called ONLY for criteria that require reading comprehension or qualitative assessment. Instead of a single LLM call, Layer 2 uses an **adversarial tribunal** pattern with three distinct roles — Prosecutor, Defender, and Judge — to maximize determinism and produce auditable justifications as a built-in byproduct.

##### Why Adversarial (not single call or consensus voting):

| Problem with single/consensus | How tribunal fixes it |
|-------------------------------|----------------------|
| Single LLM can be lenient or harsh depending on phrasing | Prosecutor is FORCED to find failures, Defender FORCED to find passes |
| Consensus voting (3 identical calls) shares the same blind spots | Adversarial roles explore different angles — diversity catches what redundancy misses |
| No reasoning trail — just a verdict | Judge must cite which arguments won and why |
| Hallucinated passes ("looks fine") | Prosecutor catches vague claims; Judge rejects unsupported arguments |
| Temperature/randomness affects outcome | Structured debate constrains output space |

##### Tribunal Tiers (by criterion weight):

| Criterion weight | Method | LLM calls | When |
|:---:|---|:---:|---|
| >= 0.20 | Full tribunal: Prosecutor + Defender + Judge | 3 | High-stakes criteria (implementation, policy) |
| 0.10 - 0.19 | Simplified: Prosecutor + Judge (defender implicit in judge prompt) | 2 | Medium-weight criteria |
| < 0.10 | Single structured call with rubric | 1 | Low-weight criteria (monitoring, exception) |

##### Full Tribunal Flow (weight >= 0.20):

```
Evidence slice + Criterion
         │
         ├──────────────────────────────────────────────┐
         │                                              │
         ▼                                              ▼
┌─────────────────────────┐            ┌─────────────────────────┐
│      PROSECUTOR         │            │       DEFENDER           │
│                         │            │                          │
│ "Find ALL reasons this  │            │ "Find ALL reasons this   │
│  evidence FAILS this    │            │  evidence SATISFIES this │
│  criterion."            │            │  criterion."             │
│                         │            │                          │
│ Cites exact gaps,       │            │ Cites exact elements     │
│ missing elements,       │            │ that satisfy, partial    │
│ weaknesses.             │            │ compliance indicators.   │
│                         │            │                          │
│ If genuinely strong:    │            │ If genuinely weak:       │
│ "No material weaknesses"│            │ "Limited support"        │
│ + minor concerns        │            │ + any partial elements   │
└────────────┬────────────┘            └────────────┬────────────┘
             │                                      │
             └──────────────────┬───────────────────┘
                                │
                                ▼
                 ┌────────────────────────────┐
                 │           JUDGE            │
                 │                            │
                 │ Reads BOTH arguments.      │
                 │ Identifies which points    │
                 │ from each side are valid   │
                 │ vs. overstated.            │
                 │                            │
                 │ Delivers:                  │
                 │ • verdict (PASS/PARTIAL/   │
                 │   FAIL)                    │
                 │ • points_accepted/rejected │
                 │   from each side           │
                 │ • justification (2-3       │
                 │   sentences citing the     │
                 │   decisive factors)        │
                 │ • confidence (0.0-1.0)     │
                 └────────────────────────────┘
```

##### Prosecutor Prompt Template:

```
You are a strict compliance prosecutor.
Your ONLY job: find reasons this evidence FAILS criterion {criterion.id}.

Criterion: {criterion.question}
Fail conditions: {criterion.fail_condition}
Evidence:
{evidence_slice}

Rules:
- Be specific. Cite exact gaps, missing elements, or weaknesses.
- If the evidence is genuinely strong, say "No material weaknesses found"
  but still note minor concerns.
- Do NOT consider whether it passes. Only look for failures.
- Output 3-5 bullet points.
```

##### Defender Prompt Template:

```
You are a compliance defense advocate.
Your ONLY job: find reasons this evidence SATISFIES criterion {criterion.id}.

Criterion: {criterion.question}
Pass conditions: {criterion.pass_condition}
Evidence:
{evidence_slice}

Rules:
- Be specific. Cite exact elements that satisfy requirements.
- If the evidence is genuinely weak, say "Limited supporting evidence"
  but still note any partial compliance.
- Do NOT consider whether it fails. Only look for passes.
- Output 3-5 bullet points.
```

##### Judge Prompt Template:

```
You are an impartial compliance judge. You have heard both sides.

Criterion: {criterion.id} — {criterion.question}
Category: {criterion.category} | Weight: {criterion.weight}

═══ PROSECUTION ARGUMENT ═══
{prosecution_argument}

═══ DEFENSE ARGUMENT ═══
{defense_argument}

═══ YOUR TASK ═══
1. Identify which prosecution points are valid vs. overstated
2. Identify which defense points are valid vs. overstated
3. Deliver verdict: PASS, PARTIAL, or FAIL
4. Write justification (2-3 sentences) citing the decisive factors

Respond in JSON:
{
  "verdict": "PASS" | "PARTIAL" | "FAIL",
  "prosecution_points_accepted": ["..."],
  "prosecution_points_rejected": ["..."],
  "defense_points_accepted": ["..."],
  "defense_points_rejected": ["..."],
  "justification": "2-3 sentences citing decisive factors",
  "confidence": 0.0-1.0
}
```

##### Confidence-Based Escalation:

If the Judge's confidence < 0.70, escalate to a **second tribunal** with different framing:
- If both tribunals agree → use that verdict (confidence = average)
- If they disagree → mark as CANNOT_ASSESS with flag `needs_human_review: true`
- Both tribunals' reasoning preserved in justification document for auditor review

##### LLM Task Types for Tribunal:

| Task | Tier | Temperature | Max Tokens |
|------|:----:|:-----------:|:----------:|
| `evaluate_prosecute` | mid | 0.0 | 500 |
| `evaluate_defend` | mid | 0.0 | 500 |
| `evaluate_judge` | mid | 0.0 | 600 |

##### Cost Comparison (same as 3-sample consensus):

```
3-sample consensus: 3 identical calls × 200 tokens = 600 output tokens
Full tribunal:      Prosecutor(500) + Defender(500) + Judge(600) = 1600 output tokens
```

Tribunal uses ~2.5x more output tokens per criterion BUT produces dramatically better output because each call has a constrained adversarial role. For criteria with weight >= 0.20, this cost is justified by the auditability and determinism gains. Lower-weight criteria still use single calls.

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

### R7f: Evaluation Justification Document

Every evaluation MUST produce a **full justification document** — not just a score, but a defensible reasoning chain that auditors can review, users can comment on, and compliance managers can accept or override.

#### Justification Structure:

```json
{
  "evaluation_id": "eval-uuid",
  "control_id": "CC6.1",
  "framework": "soc2",
  "final_score": 0.87,
  "final_status": "compliant",
  "evidence_hash": "sha256:abc123...",
  "evaluated_at": "2026-06-10T14:32:00Z",
  
  "justification": {
    "summary": "Control CC6.1 is compliant. 4/6 criteria resolved deterministically (rules). 2/6 resolved via adversarial tribunal. No floor rules triggered.",
    
    "layer1_justification": {
      "method": "deterministic_rules",
      "resolved_count": 4,
      "criteria": [
        {
          "criterion_id": "TC-CC6.1-01",
          "question": "Does an access review policy exist?",
          "result": "PASS",
          "method": "rule:keyword_presence",
          "justification": "Document 'access-review-policy.pdf' contains required terms: 'quarterly review', 'access certification', 'role-based'. Match confidence: 100% (deterministic).",
          "evidence_cited": ["s3://tenant/evidence/CC6.1/access-review-policy.pdf"]
        }
      ]
    },
    
    "layer2_justification": {
      "method": "adversarial_tribunal",
      "resolved_count": 2,
      "criteria": [
        {
          "criterion_id": "TC-CC6.1-04",
          "question": "Do reviews demonstrate actual remediation?",
          "result": "PASS",
          "method": "tribunal:adversarial",
          "confidence": 0.88,
          "prosecution": "Full prosecution argument text...",
          "defense": "Full defense argument text...",
          "judge_reasoning": {
            "prosecution_points_accepted": ["No remediation timestamps"],
            "prosecution_points_rejected": ["Row 12 IS addressed via auto-expiry"],
            "defense_points_accepted": ["15/18 rows show completed remediation (83%)"],
            "defense_points_rejected": [],
            "justification": "Evidence demonstrates substantive remediation. 83% of findings fully remediated. Minor gap: timestamps not recorded, but does not negate action."
          }
        }
      ]
    },
    
    "layer3_justification": {
      "method": "deterministic_scoring",
      "formula": "weighted_sum / assessable_weight",
      "calculation": {
        "criteria_scores": [
          {"id": "TC-01", "weight": 0.15, "result": "PASS", "score": 1.0},
          {"id": "TC-04", "weight": 0.25, "result": "PASS", "score": 1.0},
          {"id": "TC-05", "weight": 0.20, "result": "PARTIAL", "score": 0.5}
        ],
        "raw_score": 0.90,
        "floor_rules_applied": [],
        "final_score": 0.87
      }
    }
  }
}
```

#### Requirements:

- **R7f-1:** Every evaluation MUST produce a justification document, stored in `evaluation_justifications` table (1:1 with `eval_history`)
- **R7f-2:** Layer 1 justifications MUST cite the specific rule, threshold, and evidence file that determined the result
- **R7f-3:** Layer 2 justifications MUST include the full prosecution argument, defense argument, and judge reasoning
- **R7f-4:** Layer 3 justifications MUST show the complete scoring calculation including weights, floor rules checked, and threshold mapping
- **R7f-5:** The justification `summary` field MUST be a 1-2 sentence human-readable explanation suitable for display in dashboards
- **R7f-6:** Justifications are IMMUTABLE once stored — human disagreement is recorded in `evaluation_decisions`, never by editing the justification

### R7g: Evaluation Interaction (Comments, Accept, Override)

Users interact with evaluations through comments, acceptance, and overrides. These interactions are stored separately from the AI evaluation result and together form the complete audit trail.

#### Database Schema:

Three new tables in memory-service PostgreSQL:

```sql
-- 1. EVALUATION JUSTIFICATIONS (full tribunal reasoning, 1:1 with eval_history)
CREATE TABLE evaluation_justifications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id TEXT NOT NULL,
    evaluation_id UUID NOT NULL UNIQUE,
    justification JSONB NOT NULL,
    summary TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now(),
    CONSTRAINT fk_evaluation FOREIGN KEY (evaluation_id) REFERENCES eval_history(id)
);
CREATE INDEX idx_justification_eval ON evaluation_justifications(evaluation_id);
CREATE INDEX idx_justification_tenant ON evaluation_justifications(tenant_id);

-- 2. EVALUATION COMMENTS (threaded discussion per evaluation/criterion)
CREATE TABLE evaluation_comments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id TEXT NOT NULL,
    evaluation_id UUID NOT NULL,
    criterion_id TEXT,                    -- NULL = comment on overall eval
    author_id TEXT NOT NULL,
    author_role TEXT NOT NULL,
    content TEXT NOT NULL,
    parent_comment_id UUID,              -- NULL = top-level, else reply
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ,
    deleted_at TIMESTAMPTZ,              -- Soft delete
    CONSTRAINT fk_evaluation FOREIGN KEY (evaluation_id) REFERENCES eval_history(id),
    CONSTRAINT fk_parent FOREIGN KEY (parent_comment_id) REFERENCES evaluation_comments(id)
);
CREATE INDEX idx_comments_eval ON evaluation_comments(evaluation_id, created_at);
CREATE INDEX idx_comments_tenant ON evaluation_comments(tenant_id, evaluation_id);

-- 3. Add decision_status to existing eval_history
ALTER TABLE eval_history ADD COLUMN decision_status TEXT DEFAULT 'pending';
-- Values: 'pending' | 'accepted' | 'overridden' | 'disputed'
```

The existing `evaluation_decisions` table (R7e) is extended:

```sql
-- Extend evaluation_decisions to support per-criterion accept/override
ALTER TABLE evaluation_decisions ADD COLUMN criterion_id TEXT;
-- NULL = decision on overall evaluation, non-null = specific criterion

ALTER TABLE evaluation_decisions ADD COLUMN ai_verdict TEXT;
-- What the AI said for this criterion (preserved for audit trail)

ALTER TABLE evaluation_decisions ADD COLUMN user_verdict TEXT;
-- What the user decided (NULL = accepted AI verdict)

ALTER TABLE evaluation_decisions ADD COLUMN decision_type TEXT NOT NULL DEFAULT 'pending';
-- 'pending' | 'accepted' | 'overridden'

ALTER TABLE evaluation_decisions ADD COLUMN decided_by_role TEXT;
-- Role at time of decision (auditor, compliance_manager, admin)
```

#### Interaction Flows:

##### Accept Evaluation:
```
User reviews evaluation with justification displayed →
  Clicks "Accept" (overall or per-criterion) →
    POST /evaluations/{eval_id}/accept {criterion_id?, note?} →
      Creates evaluation_decision (decision_type="accepted") →
        Updates eval_history.decision_status = "accepted" →
          Audit trail logged
```

##### Override Criterion:
```
User disagrees with AI on specific criterion →
  Clicks "Override" →
    POST /evaluations/{eval_id}/override {criterion_id, user_verdict, reason} →
      Validates: only auditor/compliance_manager/admin can override →
        Validates: reason is REQUIRED for overrides →
          Creates evaluation_decision (decision_type="overridden") →
            AI verdict preserved (immutable), user verdict stored alongside →
              Score NOT recalculated (AI score is AI's; user decision is separate)
```

##### Add Comment:
```
User wants to discuss a criterion or overall evaluation →
  POST /evaluations/{eval_id}/comments {content, criterion_id?, parent_comment_id?} →
    Creates evaluation_comment (threaded) →
      Other users' shadow agents surface this on next session
```

#### Access Control:

| Action | Who can do it |
|--------|--------------|
| View evaluation + justification | All roles for their tenant |
| Add comment | All roles |
| Accept evaluation | compliance_manager, auditor, admin |
| Override criterion | auditor, compliance_manager, admin |
| Approve (finalize) | compliance_manager, admin |

#### Display Requirements:

When an evaluation is shown to any user (via compliance-assistant or UI), it MUST include:
1. The justification for each criterion (rule method or tribunal prosecution/defense/judge)
2. Existing comments (with author and timestamp)
3. Current decision status (pending/accepted/overridden)
4. Action buttons appropriate to the user's role
5. For overridden criteria: both the AI verdict and user verdict with reason

#### Key Invariants:

- **R7g-1:** AI evaluation results are NEVER modified. All human interaction is stored in separate tables.
- **R7g-2:** Override reason is REQUIRED (empty override_reason is rejected with 422).
- **R7g-3:** Both AI verdict and user verdict are preserved for audit trail. An override does not delete the AI's reasoning.
- **R7g-4:** Comments are soft-deleted (deleted_at timestamp), never hard-deleted, for audit compliance.
- **R7g-5:** Evaluation score is the AI's score. If user overrides criteria, the `final_score` in `evaluation_decisions` reflects the adjusted score, but `eval_history.result` remains unchanged.
- **R7g-6:** Only APPROVED evaluations count toward the organization's Readiness % metric.

### R7h: Policy Analysis Pipeline (Upstream Criteria Generation)

#### Problem

Testing criteria are currently static (bundled in RAG or created by observer). In reality, every organization has its own policies (50-100 page documents, multiple per framework) that define:
- What controls mean in their context
- What thresholds, SLAs, and cadences they commit to
- What constitutes compliance for their specific implementation

Without policy analysis, the evaluation checks against generic criteria ("does a policy exist?") instead of tenant-specific criteria ("does the policy define quarterly review cadence as committed in Section 4.2 of the Information Security Policy?").

#### The Evaluation Chain (correct order)

```
Standard-Based Control (what the framework requires)
  → Organization Policy (what YOUR org committed to for this control)
    → Statement of Applicability (is this control in-scope? what's excluded?)
      → Implementation Specification (how should it work per your policy)
        → Testing Criteria (how to verify it's working — generated from above)
          → Evidence Evaluation (does the evidence satisfy the criteria?)
```

This chain means testing criteria are DERIVED from policies, not invented generically. The evaluation judges evidence against what the organization said it would do.

#### Document Types Analyzed

| Document Type | Size | Purpose in Chain | Examples |
|---|---|---|---|
| **Information Security Policy** | 30-100 pages | Master commitments for all controls | "All access reviewed quarterly" |
| **Acceptable Use Policy** | 10-30 pages | Behavioral requirements | "No personal devices on prod network" |
| **Data Classification Policy** | 15-40 pages | How data is labeled and handled | "PII encrypted at rest with AES-256" |
| **Incident Response Plan** | 20-50 pages | How incidents are detected/handled | "Severity 1 response within 15 min" |
| **Change Management Policy** | 10-30 pages | How changes are approved/deployed | "All prod changes need 2 approvals" |
| **Vendor Management Policy** | 15-40 pages | Third-party risk requirements | "Annual SOC 2 from critical vendors" |
| **Statement of Applicability** | 5-20 pages | Which controls apply, exclusions | "A.14.2.7 excluded (no outsourced dev)" |
| **Risk Treatment Plan** | 10-30 pages | How residual risks are managed | "Accept risk for legacy system until Q3 migration" |
| **Business Continuity Plan** | 20-60 pages | Recovery procedures and targets | "RPO: 4 hours, RTO: 8 hours" |

#### Policy Analysis Process (Graph RAG + Late Chunking)

The pipeline uses **Graph RAG** as primary (structured extraction of entities and relationships) with **late chunking** as fallback (for unstructured queries and when graph construction is incomplete).

##### Why Graph RAG for policies (not flat chunking):

| Problem with flat chunking | How Graph RAG solves it |
|---|---|
| "Quarterly reviews" chunk loses context of WHAT is reviewed | Graph edge: `obligation →applies_to→ "Critical Systems" →defined_by→ Section 1.3` |
| Definitions at document top invisible in later chunks | Definition nodes reachable from any obligation via `uses_term` edge |
| Cross-references severed ("per Section 3.2") | `references` edges explicitly link sections |
| Multi-section obligations fragmented | Single obligation node with edges to multiple source sections |
| Conflicts between policies undetectable | Two nodes with contradicting thresholds for same control = graph query |
| "What does policy say about CC6.1?" = multi-hop | Graph traversal: `CC6.1 ←maps_to← Section 4.2 →requires→ obligations →scoped_to→ systems` |

##### Why Late Chunking as complement (not replacement):

Late chunking embeds the full document through a long-context encoder BEFORE splitting — so each chunk's embedding "knows" the full document. Used for:
- Ad-hoc questions that don't map to graph structure
- Semantic similarity queries ("find similar obligations across policies")
- When graph construction hasn't completed yet
- Evidence matching (non-policy documents)

```
┌─────────────────────────────────────────────────────────────────┐
│  POLICY ANALYSIS PIPELINE (runs once per policy upload/update)  │
└──────────────────────┬──────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│  Step 1: STRUCTURAL PARSING (preprocessor — no LLM)              │
│  • Detect document structure via layout analysis:                 │
│    - Section headings (numbered: 1, 1.1, 1.1.1)                 │
│    - Clause boundaries (sentence-level within sections)          │
│    - Definition blocks ("For the purposes of this policy...")    │
│    - Tables, appendices, cross-reference markers                 │
│  • Preserve hierarchy: Document → Chapter → Section → Clause    │
│  • Output: structural_tree with section_path + text per node     │
│  • NOT flat 1000-token chunks — preserve clause boundaries       │
└──────────────────────┬───────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│  Step 2: LATE CHUNKING (embedding with full-document context)    │
│  • Process full document through long-context encoder             │
│    (jina-embeddings-v3 or similar, 8K+ context window)           │
│  • Get per-token contextual embeddings for entire document       │
│  • Split into chunks aligned to structural_tree boundaries       │
│  • Pool token embeddings per chunk → store as vectors            │
│  • Result: each chunk's embedding "knows" the full document      │
│  • Stored in: pgvector for similarity fallback queries           │
│                                                                   │
│  Key difference from standard chunking:                          │
│    Standard: chunk("quarterly reviews") → embedding lacks context │
│    Late:     chunk("quarterly reviews") → embedding encodes       │
│              "quarterly reviews OF CRITICAL SYSTEMS per Sec 1.3"  │
└──────────────────────┬───────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│  Step 3: GRAPH EXTRACTION (LLM — task: "extract_policy_graph")   │
│  For each structural section:                                    │
│                                                                   │
│  Extract ENTITIES (nodes):                                       │
│  • Defined terms ("Critical System", "Authorized User")          │
│  • Obligations ("must review quarterly", "shall encrypt")        │
│  • Roles ("System Owner", "CISO", "DPO")                        │
│  • Systems/Assets (named systems, tier classifications)          │
│  • Thresholds (SLAs: "5 days", cadences: "quarterly")           │
│  • Controls (framework refs: CC6.1, A.9.2.5)                    │
│  • Exceptions (conditions relaxing obligations)                  │
│  • Sections (with hierarchy path: "4.2.1")                       │
│                                                                   │
│  Extract RELATIONSHIPS (edges):                                  │
│  • defines (Section 1.3 → "Critical System")                    │
│  • requires (Section 4.2 → quarterly_review obligation)          │
│  • applies_to (obligation → Critical Systems)                    │
│  • has_exception (Section 4.2 → Section 7.1 exception)          │
│  • maps_to (Section 4.2 → CC6.1 control)                        │
│  • references (Section 7.1 → Section 4.2)                       │
│  • owned_by (obligation → "System Owner" role)                   │
│  • measured_by (obligation → "5 business days" threshold)        │
│  • scoped_to (obligation → "Tier 1 and Tier 2 only")            │
│  • supersedes (Policy v3.1 Section 4 → Policy v2.0 Section 4)   │
│  • conflicts_with (detected during consolidation)                │
│                                                                   │
│  Output: policy_graph {nodes: [...], edges: [...]}               │
│  Store in: PostgreSQL (nodes table + edges table + vector index) │
└──────────────────────┬───────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│  Step 4: COMMUNITY DETECTION + SUMMARIZATION                     │
│  • Run community detection on graph (Leiden algorithm)           │
│  • Each community = one "topic area" of the policy               │
│    e.g., "Access Management", "Incident Response", "Encryption"  │
│  • Generate community summary (LLM — task: "summarize_community")│
│  • Used for: high-level questions, CISO executive summaries      │
│  • Store: community_id per node, summaries in memory-service     │
└──────────────────────┬───────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│  Step 5: CONTROL MAPPING (graph traversal + LLM verification)    │
│  For each obligation node in graph:                              │
│  • Traverse: obligation →maps_to→ control_id (if explicit)      │
│  • If no explicit mapping: LLM classifies which controls apply   │
│  • Resolve definitions: traverse →applies_to→ →defined_by→      │
│  • Resolve scope: traverse →scoped_to→ (which systems/data)     │
│  • Resolve exceptions: traverse →has_exception→                  │
│  • Output: [{control_id, obligations_with_full_context}]         │
│                                                                   │
│  Graph traversal example for CC6.1:                              │
│    CC6.1 ←maps_to← Section 4.2                                  │
│    Section 4.2 →requires→ [quarterly_review, termination_check]  │
│    quarterly_review →applies_to→ "Critical Systems"              │
│    "Critical Systems" →defined_by→ Section 1.3 (= Tier 1 + 2)  │
│    quarterly_review →measured_by→ "5 business days" SLA          │
│    quarterly_review →has_exception→ Section 7.1 (CISO approval)  │
│                                                                   │
│  Result: COMPLETE obligation context gathered by traversal,      │
│  not by hoping the right chunk appears in top-K vector search.   │
└──────────────────────┬───────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│  Step 6: OBLIGATION CONSOLIDATION (across all policies)          │
│  • Merge graphs from multiple policy documents into unified graph│
│  • Cross-document edges: Policy A references Policy B            │
│  • Group all obligations by control_id                           │
│  • Detect conflicts: two obligation nodes with contradicting     │
│    thresholds connected to same control = flagged for resolution │
│  • Output: consolidated_obligations[control_id] = [{...}]        │
└──────────────────────┬───────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│  Step 7: SOA INTEGRATION (if Statement of Applicability exists)  │
│  • Parse SOA into applicability nodes in graph                   │
│  • Add edges: control →applicability→ {status, justification}    │
│  • Excluded controls: mark in graph, skip during criteria gen    │
│  • Scope limitations: add scoped_to edges from SOA              │
│  • Gap detection: controls applicable per SOA but no obligation  │
│    nodes connected → flag as "policy gap"                        │
│  • Output: applicability_map[control_id] = {status, scope, ...}  │
└──────────────────────┬───────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│  Step 8: TESTING CRITERIA GENERATION (from graph context)        │
│  (LLM — task: "generate_testing_criteria")                       │
│  For each applicable control:                                    │
│  • Input: graph subgraph rooted at control_id                    │
│    (all obligations + definitions + thresholds + exceptions)     │
│  • The graph provides COMPLETE context without top-K lottery     │
│  • Generate: tenant-specific TestingCriteria with:               │
│    - Criteria derived from policy commitments                    │
│    - Thresholds from policy (not generic)                        │
│    - Source references (section + page from graph provenance)    │
│    - Check_types aligned to evidence expected                    │
│  • Output: TestingCriteria object (same schema as R7b)           │
│  • Store: memory.skill_store(f"criteria/{framework}/{control}")  │
└──────────────────────┬───────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│  Step 9: HUMAN REVIEW (compliance manager confirms)              │
│  • Generated criteria marked as status: "candidate"              │
│  • Compliance manager reviews via Shadow AI:                     │
│    "Here's what I derived from your policies for CC6.1.          │
│     Does this match your intent?"                                │
│  • Shows: graph visualization of obligation → criteria mapping   │
│  • On approval: status → "active"                                │
│  • On rejection: criteria adjusted and re-generated              │
└──────────────────────────────────────────────────────────────────┘
```

##### Graph Storage Schema (in memory-service PostgreSQL):

```sql
-- Policy graph nodes
CREATE TABLE policy_graph_nodes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id TEXT NOT NULL,
    document_id TEXT NOT NULL,           -- Which policy document
    node_type TEXT NOT NULL,             -- obligation | term | role | system | threshold | control | exception | section
    label TEXT NOT NULL,                 -- Human-readable name
    properties JSONB NOT NULL DEFAULT '{}',  -- Type-specific attributes
    section_ref TEXT,                    -- Source section (e.g., "4.2.1")
    page_number INT,
    source_text TEXT,                    -- Original clause text
    embedding vector(1024),             -- For similarity fallback
    community_id TEXT,                  -- From community detection
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_graph_nodes_tenant ON policy_graph_nodes(tenant_id, document_id);
CREATE INDEX idx_graph_nodes_type ON policy_graph_nodes(tenant_id, node_type);
CREATE INDEX idx_graph_nodes_community ON policy_graph_nodes(tenant_id, community_id);

-- Policy graph edges (relationships)
CREATE TABLE policy_graph_edges (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id TEXT NOT NULL,
    source_node_id UUID NOT NULL REFERENCES policy_graph_nodes(id),
    target_node_id UUID NOT NULL REFERENCES policy_graph_nodes(id),
    relationship TEXT NOT NULL,          -- defines | requires | applies_to | has_exception | maps_to | references | scoped_to | measured_by | owned_by | conflicts_with | supersedes
    properties JSONB DEFAULT '{}',      -- Relationship-specific metadata
    confidence FLOAT DEFAULT 0.9,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_graph_edges_source ON policy_graph_edges(source_node_id);
CREATE INDEX idx_graph_edges_target ON policy_graph_edges(target_node_id);
CREATE INDEX idx_graph_edges_tenant ON policy_graph_edges(tenant_id, relationship);

-- Community summaries
CREATE TABLE policy_communities (
    id TEXT PRIMARY KEY,                 -- community_id
    tenant_id TEXT NOT NULL,
    topic TEXT NOT NULL,                 -- "Access Management", "Incident Response"
    summary TEXT NOT NULL,               -- LLM-generated community summary
    node_count INT,
    key_obligations TEXT[],             -- Top obligations in this community
    related_controls TEXT[],            -- Controls covered by this community
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_communities_tenant ON policy_communities(tenant_id);
```

##### Graph Query API (in memory-service):

```
-- Traverse from a control to get all related policy context
GET /policy-graph/{tenant_id}/traverse?root=CC6.1&depth=3&relationships=maps_to,requires,applies_to,defined_by,measured_by,has_exception

Returns: {
  nodes: [{id, type, label, properties, source_text, section_ref}],
  edges: [{source, target, relationship}],
  paths: [["CC6.1", "←maps_to←", "Section 4.2", "→requires→", "quarterly_review", ...]]
}

-- Find all obligations for a control (resolved with definitions and scope)
GET /policy-graph/{tenant_id}/obligations?control_id=CC6.1&framework=soc2

Returns: [{
  obligation: "quarterly access review",
  source_section: "4.2",
  scope: "Critical Systems (Tier 1 + Tier 2 per Asset Register)",
  threshold: "5 business days remediation SLA",
  exception: "CISO approval for cadence changes (Section 7.1)",
  applies_to_systems: ["prod-api", "prod-billing", ...],  -- Resolved from Asset Register
}]

-- Detect conflicts across policies
GET /policy-graph/{tenant_id}/conflicts

Returns: [{
  control_id: "CC6.1",
  conflict: "Contradicting review cadence",
  source_a: {document: "ISP v3.1", section: "4.2", value: "quarterly"},
  source_b: {document: "Data Protection Policy", section: "6.1", value: "monthly"},
  resolution_status: "pending"
}]
```

##### Late Chunking Integration:

Late chunking runs in parallel with graph extraction and provides the similarity fallback:

```python
# During policy processing (Step 2):
async def late_chunk_document(document_text: str, structural_tree: list) -> list:
    """Embed full document, then chunk aligned to structure."""
    
    # 1. Full-document contextual encoding
    token_embeddings = await llm.embed(
        text=document_text,
        task="embed_document_full",    # Long-context encoder
        return_token_embeddings=True,  # Not just [CLS] — need per-token
    )
    
    # 2. Chunk aligned to structural boundaries (not arbitrary 1000-token splits)
    chunks = align_chunks_to_structure(document_text, structural_tree)
    
    # 3. Pool pre-computed token embeddings per chunk
    chunk_embeddings = []
    for chunk in chunks:
        token_range = token_embeddings[chunk.start_offset:chunk.end_offset]
        chunk_embedding = mean_pool(token_range)  # Already contextual!
        chunk_embeddings.append(chunk_embedding)
    
    return chunks, chunk_embeddings
    # Each embedding "knows" the full document context
    # Used for: fallback similarity search when graph doesn't have the answer
```

##### When to use Graph traversal vs. Late Chunking similarity:

| Query type | Method | Why |
|---|---|---|
| "What does policy say about CC6.1?" | Graph traversal | Relational — follow edges from control to obligations |
| "What's the remediation SLA?" | Graph traversal | Threshold node directly connected to obligation |
| "Find similar obligations across all policies" | Late chunking similarity | Cross-document similarity, no structural relationship |
| "What's the overall tone about cloud adoption?" | Late chunking similarity | Unstructured, no specific graph target |
| "Are there conflicts between ISP and DPP?" | Graph (conflicts_with edges) | Structural — detected during consolidation |
| "What did the policy say about X?" (open-ended) | Late chunking first, then graph expand | Use similarity to find entry point, then traverse |

#### Example: Policy → Criteria Derivation

**Input:** Information Security Policy, Section 4.2:
> "All user access to production systems shall be reviewed quarterly by the system owner.
> Reviews must verify: (a) active users have legitimate business need, (b) privileged
> accounts have documented justification, (c) terminated employees have no active access.
> Remediation of inappropriate access must be completed within 5 business days of
> identification. Reviews must cover all Tier 1 and Tier 2 systems as defined in the
> Asset Classification Register."

**Output:** Tenant-specific TestingCriteria for CC6.1:

```json
{
  "chunk_type": "testing_criteria",
  "control_id": "CC6.1",
  "framework": "soc2",
  "tenant_id": "acme-corp",
  "derived_from": [
    {"document": "Information Security Policy v3.1", "section": "4.2", "page": 23}
  ],
  "control_objective": "Logical access to production systems is reviewed quarterly",
  
  "criteria": [
    {
      "id": "TC-CC6.1-01",
      "category": "policy",
      "question": "Does the access control policy define quarterly review cadence?",
      "evidence_type": "document",
      "pass_condition": "Policy Section 4.2 states quarterly reviews for all production systems",
      "fail_condition": "No mention of review cadence, or cadence is less frequent than quarterly",
      "weight": 0.10,
      "check_type": "keyword_presence",
      "check_params": {"terms": ["quarterly", "access review", "production systems"]},
      "policy_source": "ISP Section 4.2"
    },
    {
      "id": "TC-CC6.1-03",
      "category": "implementation",
      "question": "Were quarterly reviews completed for all Tier 1 and Tier 2 systems?",
      "evidence_type": "structured_data",
      "pass_condition": "Review records exist for each quarter in audit period, covering ALL systems in Asset Classification Register marked Tier 1 or Tier 2",
      "fail_condition": "Reviews missing for any quarter, or Tier 1/2 systems not covered",
      "weight": 0.25,
      "check_type": "cross_reference",
      "check_params": {
        "dataset_a": "access_review_records",
        "dataset_b": "asset_classification_register",
        "join_key": "system_name",
        "filter_b": "tier IN ('Tier 1', 'Tier 2')",
        "condition": "all systems in B have matching records in A for each quarter"
      },
      "policy_source": "ISP Section 4.2 + Asset Classification Register"
    },
    {
      "id": "TC-CC6.1-04",
      "category": "implementation",
      "question": "Was inappropriate access remediated within 5 business days?",
      "evidence_type": "structured_data",
      "pass_condition": "All identified inappropriate access remediated within 5 business days of identification (per ISP Section 4.2 SLA)",
      "fail_condition": "Any remediation took >5 business days, or remediation not documented",
      "weight": 0.25,
      "check_type": "quantitative",
      "check_params": {
        "metric": "max(remediation_date - identification_date)",
        "threshold": 5,
        "unit": "business_days"
      },
      "policy_source": "ISP Section 4.2 — '5 business days'"
    },
    {
      "id": "TC-CC6.1-05",
      "category": "implementation",
      "question": "Does the review verify terminated employees have no active access?",
      "evidence_type": "structured_data",
      "pass_condition": "Cross-reference of terminations vs active access shows 0 matches",
      "fail_condition": "Terminated employees found in active access list",
      "weight": 0.20,
      "check_type": "cross_reference",
      "check_params": {
        "dataset_a": "hr_terminations",
        "dataset_b": "active_access_list",
        "join_key": "employee_id",
        "condition": "zero matches (no terminated users with active access)"
      },
      "policy_source": "ISP Section 4.2(c)"
    },
    {
      "id": "TC-CC6.1-06",
      "category": "monitoring",
      "question": "Are privileged accounts documented with business justification?",
      "evidence_type": "structured_data",
      "pass_condition": "All accounts with admin/root/elevated access have documented justification approved by system owner",
      "fail_condition": "Privileged accounts without justification or approval",
      "weight": 0.20,
      "check_type": "null_rate",
      "check_params": {
        "dataset": "privileged_access_list",
        "column": "business_justification",
        "threshold": 1.0,
        "filter": "access_level IN ('admin', 'root', 'elevated')"
      },
      "policy_source": "ISP Section 4.2(b)"
    }
  ],
  
  "scoring": {
    "compliant": "Weighted score >= 0.85",
    "partially_compliant": "Weighted score 0.60 - 0.84",
    "non_compliant": "Weighted score < 0.60"
  }
}
```

Note: The criteria reference policy section numbers, use thresholds from the policy (5 business days, not generic "timely"), and scope to systems defined by the tenant's own classification.

#### Statement of Applicability (SOA) Integration

The SOA defines which controls are in-scope. The policy analyzer reads the SOA and:

1. **Marks excluded controls** — skipped during evaluation (not counted in Readiness %)
2. **Records exclusion justification** — stored for auditor review
3. **Narrows scope** — if SOA says "applies only to cloud infrastructure", criteria are scoped accordingly
4. **Detects gaps** — if a control is applicable per SOA but no policy addresses it → flags as "policy gap"

```json
{
  "control_id": "A.14.2.7",
  "framework": "iso27001",
  "applicability": "excluded",
  "justification": "No outsourced development activities. All development performed in-house.",
  "soa_reference": "SOA v2.1, row 87",
  "review_date": "2026-01-15"
}
```

#### Storage (in memory-service)

```sql
-- New table: policy_obligations
CREATE TABLE policy_obligations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id TEXT NOT NULL,
    control_id TEXT NOT NULL,
    framework TEXT NOT NULL,
    
    -- Source
    document_name TEXT NOT NULL,          -- "Information Security Policy v3.1"
    document_storage_key TEXT NOT NULL,   -- S3/MinIO path
    section_ref TEXT NOT NULL,            -- "Section 4.2"
    page_number INT,
    clause_text TEXT NOT NULL,            -- The actual policy text
    
    -- Extracted obligation
    obligation_type TEXT NOT NULL,        -- "cadence" | "threshold" | "scope" | "sla" | "requirement"
    obligation_summary TEXT NOT NULL,     -- "Quarterly access review for all Tier 1/2 systems"
    specifics JSONB NOT NULL,            -- {cadence: "quarterly", scope: "tier_1_tier_2", sla_days: 5}
    
    -- Lifecycle
    status TEXT DEFAULT 'active',        -- active | superseded | conflicting
    confidence FLOAT DEFAULT 0.9,
    extracted_at TIMESTAMPTZ DEFAULT now(),
    reviewed_by TEXT,                     -- user_id who confirmed
    reviewed_at TIMESTAMPTZ,
    
    CONSTRAINT unique_obligation UNIQUE (tenant_id, control_id, framework, document_name, section_ref)
);

CREATE INDEX idx_obligations_control ON policy_obligations(tenant_id, framework, control_id);
CREATE INDEX idx_obligations_doc ON policy_obligations(tenant_id, document_name);

-- New table: control_applicability (from SOA)
CREATE TABLE control_applicability (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id TEXT NOT NULL,
    control_id TEXT NOT NULL,
    framework TEXT NOT NULL,
    
    applicability TEXT NOT NULL,          -- "applicable" | "excluded" | "partially_applicable"
    justification TEXT,                   -- Required for excluded
    scope_limitation TEXT,                -- "Cloud infrastructure only"
    
    soa_document TEXT,                   -- "Statement of Applicability v2.1"
    soa_reference TEXT,                  -- "Row 87"
    
    review_date DATE,
    reviewed_by TEXT,
    
    CONSTRAINT unique_applicability UNIQUE (tenant_id, control_id, framework)
);

CREATE INDEX idx_applicability_tenant ON control_applicability(tenant_id, framework);
```

#### How It Integrates with Evaluation (Agent-Eval is Read-Only)

Agent-eval has NO `/analyze-policy` endpoint. It only READS from memory-service at evaluation time:

```python
# agent-eval/graph/nodes/load_criteria.py
# This runs at evaluation time — all policy data already exists in memory-service

async def load_criteria(framework, control_id, tenant_id):
    # 1. Check applicability (written by policy pipeline, read by eval)
    applicability = await memory.get_applicability(tenant_id, framework, control_id)
    if applicability and applicability.status == "excluded":
        return ExcludedControl(reason=applicability.justification)
    
    # 2. Check for tenant-specific criteria (written by pipeline, read by eval)
    tenant_criteria = await memory.skill_get(
        f"criteria/{tenant_id}/{framework}/{control_id}"
    )
    if tenant_criteria and tenant_criteria.status == "active":
        return tenant_criteria  # Use policy-derived criteria
    
    # 3. Fall back to generic criteria (bundled in RAG)
    generic = rag.get_testing_criteria(framework, control_id)
    return generic


# agent-eval/graph/nodes/load_policy_context.py
# Fetches graph context for enriching rules + tribunal prompts

async def load_policy_context(framework, control_id, tenant_id):
    # All READ operations — agent-eval never writes to policy graph
    graph = await memory.policy_graph_traverse(tenant_id, root=control_id, depth=3)
    obligations = await memory.get_policy_obligations(tenant_id, framework, control_id)
    
    return PolicyContext(
        obligations=obligations,
        thresholds=extract_thresholds(obligations),
        graph_subgraph=graph,
    )
    # Returns empty PolicyContext if nothing exists → evaluation degrades gracefully
```

The evaluation justification references policy sources:
```json
{
  "criterion_id": "TC-CC6.1-04",
  "justification": "Remediation completed in max 3 business days (policy SLA: 5 business days per ISP Section 4.2). PASS.",
  "policy_source": "ISP Section 4.2 — '5 business days'"
}
```

#### Execution Model (Independent Pipeline — NOT Inside Agent-Eval)

The policy pipeline runs as an **independent process** — agent-eval is a READ-ONLY consumer of the policy graph. The pipeline is orchestrated by compliance-assistant or a scheduler.

```
┌────────────────────────────────────────────────────────────────────┐
│                    SEPARATION OF CONCERNS                           │
├──────────────────────┬─────────────────────────────────────────────┤
│  POLICY PIPELINE     │  AGENT-EVAL                                 │
│  (independent)       │  (read-only consumer)                       │
├──────────────────────┼─────────────────────────────────────────────┤
│  Builds graph        │  Reads graph                                │
│  Extracts entities   │  Traverses for context                      │
│  Maps to controls    │  Gets obligations as thresholds             │
│  Generates criteria  │  Loads active criteria                      │
│  Detects conflicts   │  Ignores pipeline state                     │
│  Requires approval   │  Fully automated                            │
│  Runs on policy      │  Runs on evidence                           │
│  upload/change       │  upload/schedule                            │
│  50-100 LLM calls    │  3-6 LLM calls per control                 │
│  5-15 min per policy │  10-30 sec per control                      │
│  Serial (1 per       │  Concurrent (5-10 per tenant)               │
│  tenant)             │                                             │
└──────────────────────┴─────────────────────────────────────────────┘
```

- **Who triggers:** compliance-assistant (orchestrator) or scheduled batch job
- **When triggered:**
  - New policy document uploaded (detected by preprocessor)
  - Policy document updated (content hash changed)
  - SOA uploaded or updated
  - User explicitly requests ("re-analyze my policies")
  - Scheduled re-analysis (e.g., monthly, or before audit)
  - Observer recommends (criteria producing unexpected results)
- **Runtime:** 5-15 minutes for a 100-page policy
- **Concurrency:** One policy pipeline at a time per tenant (serialized to avoid graph conflicts)
- **Idempotency:** Same policy hash → skip re-analysis
- **Human-in-loop:** Generated criteria are "candidate" until compliance manager approves
- **Cost:** ~50-100 LLM calls per policy
- **Failure isolation:** If pipeline fails, agent-eval continues with existing/generic criteria. Pipeline never blocks evaluations.

#### How the orchestrator decides when to run:

```python
# In compliance-assistant (orchestrator logic):

async def on_policy_uploaded(event: FileUploadEvent):
    """Preprocessor notifies: new policy file detected."""
    
    # Check if this is actually a policy (not evidence)
    if event.upload_path.startswith("policies/") or event.detected_type == "policy":
        
        # Check if we've already analyzed this version
        existing = await memory.get_policy_analysis_status(
            tenant_id=event.tenant_id,
            document_hash=event.content_hash,
        )
        
        if existing and existing.status == "completed":
            # Same content, already analyzed — skip
            return
        
        if existing and existing.status == "in_progress":
            # Already running — skip
            return
        
        # Ask user (via Shadow AI) or auto-trigger based on settings
        if tenant_settings.auto_analyze_policies:
            await trigger_policy_pipeline(event)
        else:
            # Queue notification for compliance manager's agent
            await notify_compliance_manager(
                f"New policy detected: {event.filename}. Analyze it?"
            )


async def trigger_policy_pipeline(event: FileUploadEvent):
    """Orchestrator triggers the independent policy pipeline."""
    
    # Pipeline runs as a skill or separate service
    result = await policy_pipeline.run(
        document_key=event.storage_key,
        tenant_id=event.tenant_id,
        framework=detect_framework(event),  # or ask user
    )
    
    # Pipeline writes to memory-service:
    # - policy_graph_nodes / edges
    # - policy_obligations
    # - control_applicability
    # - candidate testing criteria
    
    # Notify compliance manager for review
    if result.criteria_generated > 0:
        await notify_compliance_manager(
            f"Policy analyzed: {result.controls_mapped} controls mapped, "
            f"{result.criteria_generated} testing criteria generated. "
            f"{result.conflicts} conflicts need resolution. Review?"
        )
```

#### Pipeline deployment options:

| Option | When to use |
|--------|-------------|
| **Skill in compliance-assistant** | Default. Pipeline runs as a long-running skill. Simple deployment, shares infrastructure. |
| **Separate service (`policy-analyzer`)** | When pipeline is resource-intensive (many tenants, large policies). Independently scalable. |
| **Batch job (scheduled)** | For periodic re-analysis (monthly) or pre-audit sweeps. Triggered by cron. |

For V1, the pipeline runs as a **skill within compliance-assistant** — the compliance manager's agent triggers it via MCP tools. No new service deployment needed.

#### LLM Task Types:

| Task | Tier | Purpose |
|------|:----:|---------|
| `extract_policy_graph` | mid | Extract entities and relationships from policy section |
| `map_policy_to_controls` | mid | Map obligation nodes → framework controls (when no explicit edge) |
| `extract_obligations` | mid | Extract thresholds, SLAs, cadences from clause |
| `summarize_community` | fast | Generate summary for a graph community (topic cluster) |
| `generate_testing_criteria` | strong | Generate full TestingCriteria from graph subgraph context |
| `detect_conflicts` | mid | Verify potential conflicts between obligation nodes |
| `parse_soa` | mid | Parse Statement of Applicability structure |
| `embed_document_full` | — | Long-context encoder for late chunking (embedding, not LLM) |

#### Key Invariants:

- **R7h-1:** Policy analysis MUST run before evaluation for accurate results. If no policies uploaded, evaluation falls back to generic criteria (degraded but functional).
- **R7h-2:** Generated criteria are CANDIDATE until human approves. Unapproved criteria are NOT used in evaluations.
- **R7h-3:** Policy source references MUST be preserved in criteria (`policy_source` field) and propagated to justification documents.
- **R7h-4:** When a policy is updated, previously generated criteria are marked "superseded" and re-generation triggers automatically.
- **R7h-5:** Conflicting obligations (e.g., one policy says quarterly, another says monthly) MUST be flagged for human resolution, not silently picked.
- **R7h-6:** SOA exclusions override everything — an excluded control is never evaluated regardless of policy obligations.
- **R7h-7:** The evaluation chain order is enforced: Standard → Policy → SOA → Implementation → Testing Criteria → Evidence. Skip to generic criteria only when upstream documents are unavailable.

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

### R10: Graph Structure (updated with evidence preprocessing)

```
router → discovery → confirmation → extractor → evidence_prep → evaluation → sandbox → code_fixer → storage → formatter
                                                                ↘ query → sandbox_query → formatter
                                                                ↘ chat_respond
```

### R10b: Evidence Preprocessing Node

**Problem:** Raw evidence comes in forms that the evaluation node can't reason about:
- PDFs with diagrams, tables, flowcharts → need VLM to describe visual elements
- Screenshots/images → need VLM to extract text and describe what's shown
- Multi-sheet Excel files → need flattening into queryable structure
- Scanned documents → need OCR + layout understanding

The evaluation node expects: clean text, structured data, and described visuals. It should NOT waste LLM tokens on visual interpretation — that's a separate preprocessing step.

**Solution:** An `evidence_prep` node that runs BETWEEN extractor and evaluation. It transforms raw evidence into evaluation-ready form. Crucially: **it only runs if preprocessing hasn't already been done** (results are cached per evidence file hash).

#### What evidence_prep does per file type:

| Evidence type | Preprocessing needed | LLM task used | Output |
|---------------|---------------------|:-------------:|--------|
| **PDF with text only** | None (already extracted by preprocessor) | — | Pass through |
| **PDF with tables** | VLM extracts tables into structured format | `describe_visual` (mid) | Markdown tables + description |
| **PDF with diagrams/flowcharts** | VLM describes the diagram's meaning | `describe_visual` (mid) | Text description of what diagram shows |
| **Screenshots** | VLM describes what's shown (UI, config, dashboard) | `describe_visual` (mid) | "Screenshot shows AWS IAM console with MFA enabled for all users" |
| **Images (certs, badges)** | VLM reads text and identifies document type | `describe_visual` (fast) | "ISO 27001 certificate issued to Acme Corp, valid until 2027-03" |
| **Excel (single sheet, clean)** | None (schema already extracted by preprocessor) | — | Pass through |
| **Excel (multi-sheet, pivots)** | Flatten into single queryable structure, describe relationships | `extract_schema` (fast) | Flattened CSV + sheet relationship description |
| **Excel (merged cells, complex layout)** | Interpret layout, extract logical tables | `describe_visual` (mid) | Clean structured data + layout explanation |
| **Word/PowerPoint** | Already text-extracted by preprocessor | — | Pass through |

#### Skip condition (critical for efficiency):

```python
def evidence_prep(state: AgentState) -> dict:
    evidence = state["evidence"]
    prepared = []
    
    for e in evidence:
        # Check if this file was already preprocessed (cached)
        prep_key = f"prep/{e['s3_key']}.json"
        cached = storage.get_json(prep_key)
        
        if cached and cached["source_hash"] == hash(e["s3_key"] + e.get("content_hash", "")):
            # Already preprocessed — use cached result
            prepared.append({**e, **cached["prepared_fields"]})
            continue
        
        # Needs preprocessing
        if needs_vlm(e):
            result = preprocess_with_vlm(e)
        elif needs_flattening(e):
            result = flatten_excel(e)
        else:
            result = e  # pass through
        
        # Cache the result
        storage.put_json(prep_key, {
            "source_hash": hash(e["s3_key"] + e.get("content_hash", "")),
            "prepared_fields": result,
            "prepared_at": datetime.utcnow().isoformat(),
        })
        
        prepared.append(result)
    
    return {"evidence": prepared}
```

#### What VLM preprocessing produces:

For a PDF with a network diagram:
```json
{
  "source": "network_architecture.pdf",
  "evidence_type": "unstructured",
  "extracted_text": "... original text ...",
  "visual_descriptions": [
    {
      "page": 3,
      "type": "diagram",
      "description": "Network segmentation diagram showing 3 VPCs: production (10.0.0.0/16), staging (10.1.0.0/16), development (10.2.0.0/16). Firewall rules between zones shown. Internet-facing only through ALB in production VPC. Database tier has no direct internet access.",
      "compliance_relevance": "Demonstrates network segmentation and access control layers"
    }
  ],
  "tables_extracted": [
    {
      "page": 5,
      "title": "Firewall Rules Summary",
      "data": [
        {"source": "internet", "destination": "ALB", "port": "443", "action": "allow"},
        {"source": "ALB", "destination": "app-tier", "port": "8080", "action": "allow"}
      ]
    }
  ]
}
```

For a screenshot of an AWS console:
```json
{
  "source": "aws_mfa_config.png",
  "evidence_type": "unstructured",
  "extracted_text": "",
  "visual_descriptions": [
    {
      "type": "screenshot",
      "description": "AWS IAM console showing 'Account Settings' page. 'Require MFA for all IAM users' is toggled ON (green). Password policy shows: minimum 14 characters, require symbols, expire after 90 days. Last modified: 2026-01-15.",
      "compliance_relevance": "Demonstrates MFA enforcement and password policy configuration"
    }
  ]
}
```

#### LLM task types for evidence_prep:

| Task | Tier | When used |
|------|:----:|-----------|
| `describe_visual` | mid | PDFs with diagrams/tables, screenshots, images with complex content |
| `describe_visual_simple` | fast | Certificates, simple images with text, badges |
| `extract_schema` | fast | Complex Excel interpretation |

#### Why this is a separate node (not part of extractor or evaluation):

1. **Caching**: VLM calls are expensive. Cache per file hash. Don't re-describe the same screenshot every evaluation.
2. **Separation of concerns**: Extractor loads files. Prep interprets visuals. Evaluation assesses compliance. Clean boundaries.
3. **Different model needs**: Prep needs a VLM (vision model). Evaluation needs a text reasoning model. Different capabilities.
4. **Skip on re-evaluation**: If evidence files haven't changed, prep is 100% cache hits — zero LLM cost, instant.
5. **Batch-friendly**: In batch mode (40 controls), many controls share evidence files. Prep once, evaluate many times.

#### Graph with skip logic:

```
extractor → [evidence_prep] → evaluation
                 │
                 ├── all files cached? → skip (instant) → evaluation
                 └── some need VLM? → call VLM per file → cache → evaluation
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
| `evaluate_prosecute` | mid | Tribunal: find failures in evidence |
| `evaluate_defend` | mid | Tribunal: find passes in evidence |
| `evaluate_judge` | mid | Tribunal: weigh arguments, deliver verdict + justification |
| `evaluate_control` | mid | Single-call evaluation (low-weight criteria) |
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
