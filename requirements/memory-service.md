# Service: Memory Service (memory-service)

## Purpose

Shared memory layer for all agents. Stores tenant knowledge, evaluation history, learned patterns, skills/prompts, and session state. Every agent reads from and writes to this single source of truth.

No agent has its own memory silo. The memory service is the only persistence layer agents interact with (besides the LLM gateway for inference).

## System Requirements Covered

| System Requirement | This module's role | Requirement ID |
|---|---|---|
| AWS-First w/ Adapters | RDS PostgreSQL + ElastiCache (same engine as local) | R11, R12 |
| Graceful Degradation | Stores without embedding if LLM down, flags for retry | R8 |
| PII-Aware Logging | Audit trail stores full unredacted data (access-controlled, append-only) | R7 |
| Memory is Shared | Single source of truth — sessions, user/tenant facts, evals, patterns, skills | R1-R7 |
| Shadow AI per User | Stores per-user preferences, behavior, responsibilities | R2 |
| Deterministic First | Evidence hash in eval history enables 100% cache-hit on unchanged evidence | R5 |
| Skills & Playbooks | Stores versioned skills with canary/active lifecycle, metrics per version | R5 |
| Self-Improving | Stores patterns and skills that observer creates/updates | R4, R5 |
| Self-Governing | Stores model governance reports as eval history entries | R5 |
| Multi-Tenant Isolation | tenant_id enforced on all queries, no cross-tenant reads, admin scope for observer | R9 |
| Independent Deploy | Own image, MEMORY_VERSION tag, runs migrations on startup | R11 |

## Core Responsibilities

1. Session state: short-term conversation context (Redis-backed)
2. User memory: per-user preferences, responsibilities, behavior patterns (PostgreSQL + vector)
3. Tenant memory: org-wide facts about the customer's environment (PostgreSQL + vector)
4. Task/Workflow tracking: what needs to be done, what's blocked, what's overdue (PostgreSQL)
5. Evaluation history: past results per control per tenant (PostgreSQL)
6. Patterns: cross-tenant learned behaviors (PostgreSQL + vector)
7. Skills: versioned prompt templates and behavior configs (PostgreSQL)
8. Interactions: conversation log for learning (PostgreSQL)

## Requirements

### R1: Session Memory (short-term)

- Purpose: current conversation state within a session
- TTL: configurable, default 4 hours
- Storage: Redis (fast read/write)
- API:
  ```
  GET  /session/{session_id}
  PUT  /session/{session_id}          body: {data: {...}}
  DELETE /session/{session_id}
  ```
- Data: arbitrary JSON (agent decides what to store)
- Max size per session: 256KB
- Auto-expire after TTL

### R2: User Memory (per-user, long-term)

- Purpose: what the system knows about each individual user — preferences, responsibilities, behavior
- Storage: PostgreSQL with pgvector for semantic search
- Scoped to: `tenant_id` + `user_id` (user memory is tenant-isolated)
- Categories: `preference`, `responsibility`, `behavior`, `context`, `interaction_note`
- API:
  ```
  POST /user/{tenant_id}/{user_id}/remember
    body: {fact, category, source, confidence}
  
  GET  /user/{tenant_id}/{user_id}/recall?query=...&top_k=5
    → semantic search over user facts
  
  GET  /user/{tenant_id}/{user_id}/facts?category=...
    → list all facts about this user
  
  DELETE /user/{tenant_id}/{user_id}/facts/{fact_id}
    → remove stale fact
  ```
- Examples of stored facts:
  - `preference`: "Prefers concise answers", "Likes tables over bullet lists"
  - `responsibility`: "Owns CC6.1, CC6.2, CC6.3", "Reports to Mike (admin)"
  - `behavior`: "Usually uploads evidence on Fridays", "Asks follow-up questions about metrics"
  - `context`: "New to SOX framework, experienced with SOC2", "Joined 3 weeks ago"
  - `interaction_note`: "Struggled with policy formatting last session, showed examples"
- Auto-learned: compliance-assistant observes patterns and stores (e.g., if user always asks for CSV format, remember "prefers CSV exports")
- Never stores: passwords, PII beyond name/email, authentication data
- Deduplication: same as tenant memory (>0.9 similarity = update)

### R3: Tenant Memory (org-wide, long-term)

- Purpose: what the system knows about the entire organization
- Storage: PostgreSQL with pgvector for semantic search
- Categories: `environment`, `process`, `people`, `preference`, `integration`
- API:
  ```
  POST /tenant/{tenant_id}/remember
    body: {fact, category, source, confidence}
  
  GET  /tenant/{tenant_id}/recall?query=...&top_k=5
    → semantic search over tenant facts
  
  GET  /tenant/{tenant_id}/facts?category=...
    → list all facts, optionally filtered
  
  DELETE /tenant/{tenant_id}/facts/{fact_id}
    → remove stale/incorrect fact
  
  PUT  /tenant/{tenant_id}/facts/{fact_id}
    body: {fact, confidence}
    → update existing fact
  ```
- Embedding generated on write (via LLM gateway `/v1/embed`)
- Deduplication: before storing, check semantic similarity to existing facts (>0.9 similarity = update, not insert)
- Source tracking: which agent stored the fact, when, with what confidence

### R4: Task & Workflow Tracking (what needs to be done)

- Purpose: persistent to-do list the agent manages across sessions — open tasks, blocked items, deadlines, escalations
- Storage: PostgreSQL
- Scoped to: `tenant_id` (shared across users in the org — everyone sees relevant tasks)
- API:
  ```
  POST /tasks/{tenant_id}
    body: {type, control_id, framework_id, assignee_id, status, due_date, note, metadata}

  GET  /tasks/{tenant_id}?assignee=...&status=...&overdue=true&framework=...
    → filtered task list

  PUT  /tasks/{tenant_id}/{task_id}
    body: {status, note, metadata}
    → update task status

  GET  /tasks/{tenant_id}/summary
    → {total, open, overdue, blocked, by_assignee: {...}, by_framework: {...}}

  GET  /tasks/{tenant_id}/timeline?days=30
    → upcoming deadlines in next N days
  ```
- Task types:
  | Type | Created by | Example |
  |------|-----------|---------|
  | `evidence_needed` | agent-eval (gap found), MCP (manual request) | "Upload Q1 access review for CC6.1" |
  | `evidence_uploaded` | preprocessor (file detected) | "New file for CC6.1, ready for evaluation" |
  | `evaluation_pending` | compliance-assistant (user requested eval) | "Re-evaluate CC6.1 with new evidence" |
  | `evaluation_complete` | agent-eval (eval done) | "CC6.1 evaluated: compliant" |
  | `policy_needed` | gap analysis | "Create password policy for CC6.3" |
  | `review_requested` | compliance-assistant (user sent for review) | "Policy review pending from Mike" |
  | `escalation` | observer or compliance-assistant | "CC7.2 overdue 12 days, assigned to Mike" |
  | `onboarding_step` | compliance-assistant (workflow progress) | "Invite team members (step 3/5)" |
  | `remediation` | auditor (finding logged) | "Fix terminated user access, due June 1" |
  | `reminder_sent` | escalation tool | "Reminder sent to Mike about CC7.2" |

- Status lifecycle:
  ```
  open → in_progress → completed
                     → blocked (with blocked_reason)
                     → overdue (auto-set when due_date passes)
                     → escalated (reminder sent or manager notified)
                     → cancelled
  ```

- Auto-transitions:
  - `due_date` passes → status auto-set to `overdue`
  - Evidence uploaded for a control with `evidence_needed` task → status auto-set to `evidence_uploaded`
  - Evaluation completes → corresponding `evaluation_pending` task → `completed`
  - These transitions triggered by agents/preprocessor writing updates, not by a scheduler

- What agents do with tasks:
  - **compliance-assistant**: reads tasks to tell user their status ("you have 2 overdue items"), creates tasks when user requests ("remind Sarah to upload by Friday")
  - **agent-eval**: marks evaluation tasks complete, creates `evidence_needed` tasks for gaps found
  - **observer**: detects stuck/overdue tasks, proposes escalation
  - **MCP tools**: `escalation.check_overdue` reads from this, `evidence.request_from_user` creates a task

### R5: Evaluation History

- Purpose: track every evaluation result for trend analysis and caching
- Storage: PostgreSQL
- API:
  ```
  POST /eval/{tenant_id}/{framework}/{control_id}
    body: {status, confidence, evidence_hash, result, model_used, tier_used, latency_ms}
  
  GET  /eval/{tenant_id}/{framework}/{control_id}/last
    → most recent evaluation
  
  GET  /eval/{tenant_id}/{framework}/{control_id}/history?limit=20
    → evaluation history (trend)
  
  GET  /eval/{tenant_id}/{framework}/{control_id}/last?evidence_hash=xyz
    → check if evaluation exists for this exact evidence
  ```
- Used by agent-eval to skip re-evaluation when evidence unchanged
- Used by observer to track quality over time
- Used by compliance-assistant to answer "how did CC6.1 do last time?"

### R4: Patterns (cross-tenant learning)

- Purpose: system-wide knowledge learned from successful evaluations
- Storage: PostgreSQL with pgvector
- NOT tenant-specific — patterns apply across all tenants
- API:
  ```
  POST /patterns/record
    body: {pattern, context, confidence, source}
  
  GET  /patterns/query?task=...&context={...}&top_k=5
    → find relevant patterns for a task
  
  GET  /patterns/list?source=...&min_confidence=0.8
    → list patterns, filtered
  
  PUT  /patterns/{id}/boost
    → increment hit_count, update last_used_at (pattern was useful)
  
  DELETE /patterns/{id}
    → remove bad pattern
  ```
- Embedding generated on write for semantic search
- Confidence decays over time if pattern is never used (configurable decay rate)
- Hit count tracking: patterns that get used more are ranked higher
- Examples:
  - "Files named *_access_review* are relevant for CC6.1"
  - "For CC8.1, column 'change_ticket_id' correlates with approval evidence"
  - "When tenant uses Okta, check for 'okta_events' in evidence files"

### R5: Skills (versioned prompts)

- Purpose: prompt templates and agent behavior configs that evolve over time
- Storage: PostgreSQL (versioned)
- Skills are identified by string ID (e.g., `prompt/evaluate_control`, `prompt/classify_intent`, `greeting/admin`)
- API:
  ```
  GET  /skills/{skill_id}
    → current active version {prompt_template, config, version, status}
  
  GET  /skills/{skill_id}/version/{version}
    → specific version
  
  GET  /skills/{skill_id}/history
    → all versions with metrics
  
  POST /skills/{skill_id}
    body: {prompt_template, config, reason, author, status}
    → create new version (status: active|candidate|canary)
  
  POST /skills/{skill_id}/rollback/{version}
    → set active version back to a previous one
  
  GET  /skills?role=...&trigger=...
    → search skills by role or trigger pattern
  ```
- Status lifecycle: `candidate` → `canary` → `active` (or `retired`)
- Only one version can be `active` at a time
- Metrics stored per version: `{avg_confidence, escalation_rate, usage_count, last_used}`
- Observer is the primary writer; humans can also update via admin API

### R6: Interactions (conversation log)

- Purpose: store conversations for memory extraction and skill improvement
- Storage: PostgreSQL
- API:
  ```
  POST /interactions/{tenant_id}/{user_id}
    body: {session_id, messages: [{role, content, timestamp}]}
  
  GET  /interactions/{tenant_id}/{user_id}?limit=50
    → recent interactions
  
  GET  /interactions/{tenant_id}?since=...
    → all tenant interactions since timestamp (for observer batch processing)
  ```
- Retention: configurable per tenant (default 90 days)
- Used by observer to extract patterns and improve skills
- MUST NOT store raw PII in patterns (interactions yes, patterns no)

### R7: Audit Trail

- Purpose: immutable log of all state-changing operations
- Storage: PostgreSQL (append-only table, no UPDATE/DELETE)
- Recorded automatically by memory service on every write operation:
  ```json
  {
    "id": "uuid",
    "timestamp": "2026-05-10T14:32:01Z",
    "operation": "tenant_remember",
    "tenant_id": "acme",
    "agent": "agent-eval",
    "data": {"fact": "Uses Okta", "category": "integration"},
    "trace_id": "abc-123"
  }
  ```
- API:
  ```
  GET /audit/{tenant_id}?since=...&operation=...
    → query audit trail (read-only)
  ```
- No delete endpoint. Ever.

### R8: Embedding Integration

- Memory service generates embeddings for semantic search
- Calls LLM gateway `/v1/embed` endpoint (does not embed locally)
- Embeddings stored as pgvector columns
- Dimension: configurable (default 1024, matches Amazon Titan Embed v2)
- If embedding service unavailable: store without embedding, flag for retry
- If LLM credits exhausted: store without embedding (still searchable by exact match), queue for embedding when credits return

### R9: Data Isolation

- Tenant data is strictly isolated — no tenant can access another tenant's data
- Patterns are the exception: cross-tenant, but contain NO tenant-identifiable information
- API enforces tenant_id on all tenant-scoped endpoints
- No wildcard tenant queries (except for observer with admin scope)
- Observer has `admin` scope: can read cross-tenant aggregates but MUST NOT copy tenant data to patterns

### R10: Backup & Migration

- PostgreSQL: standard pg_dump/pg_restore
- Schema migrations: applied on service startup (versioned migrations directory)
- Backward compatible: new service version can read old data
- Export endpoint: `GET /export/{tenant_id}` — full tenant data dump (for portability)
- Import endpoint: `POST /import/{tenant_id}` — restore tenant data from dump

### R11: Container Packaging

- Single Docker image, independently versioned
- Version tag: `MEMORY_VERSION`
- Depends on: PostgreSQL, Redis, LLM Gateway (for embeddings)
- Health check: `GET /health`
- Readiness: `GET /ready` (DB connected, Redis connected)
- Port: 5000
- Startup: runs migrations automatically

### R12: Configuration

```yaml
# Environment variables (AWS-first defaults — RDS PostgreSQL + ElastiCache Redis)
DB_HOST: ${RDS_ENDPOINT}              # e.g., compliance-db.cluster-xyz.us-east-1.rds.amazonaws.com
DB_PORT: 5432
DB_NAME: compliance_memory
DB_USER: memory_svc
DB_PASSWORD: ${MEMORY_DB_PASSWORD}
REDIS_URL: redis://${ELASTICACHE_ENDPOINT}:6379/0
LLM_GATEWAY_URL: http://llm-gateway:4000
AWS_REGION: us-east-1
EMBEDDING_DIMENSION: 1024              # matches Amazon Titan Embed v2
SESSION_TTL_HOURS: 4
INTERACTION_RETENTION_DAYS: 90
PATTERN_DECAY_DAYS: 90
PATTERN_DECAY_RATE: 0.1
DEDUP_SIMILARITY_THRESHOLD: 0.9
LOG_LEVEL: info
PORT: 5000

# Local development overrides:
# DB_HOST: postgres
# REDIS_URL: redis://redis:6379/0
```

### R13: Schema (PostgreSQL)

```sql
-- User memory (per-user, per-tenant)
CREATE TABLE user_memory (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    fact TEXT NOT NULL,
    category TEXT NOT NULL,         -- preference, responsibility, behavior, context, interaction_note
    source TEXT NOT NULL,
    confidence FLOAT DEFAULT 1.0,
    embedding vector(1024),
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_user_mem_tenant_user ON user_memory(tenant_id, user_id);
CREATE INDEX idx_user_mem_embedding ON user_memory USING ivfflat (embedding vector_cosine_ops);

-- Tenant memory (org-wide)
CREATE TABLE tenant_memory (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id TEXT NOT NULL,
    fact TEXT NOT NULL,
    category TEXT NOT NULL,
    source TEXT NOT NULL,
    confidence FLOAT DEFAULT 1.0,
    embedding vector(1024),
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_tenant_mem_tenant ON tenant_memory(tenant_id);
CREATE INDEX idx_tenant_mem_embedding ON tenant_memory USING ivfflat (embedding vector_cosine_ops);

-- Tasks & workflow tracking
CREATE TABLE tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id TEXT NOT NULL,
    type TEXT NOT NULL,              -- evidence_needed, evaluation_pending, escalation, etc.
    control_id TEXT,
    framework_id TEXT,
    assignee_id TEXT,               -- user responsible
    status TEXT NOT NULL DEFAULT 'open',  -- open, in_progress, completed, blocked, overdue, escalated, cancelled
    due_date DATE,
    note TEXT,
    blocked_reason TEXT,
    metadata JSONB,                 -- flexible extra data per task type
    created_by TEXT NOT NULL,       -- which agent/user created this
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    completed_at TIMESTAMPTZ
);
CREATE INDEX idx_tasks_tenant ON tasks(tenant_id);
CREATE INDEX idx_tasks_assignee ON tasks(tenant_id, assignee_id, status);
CREATE INDEX idx_tasks_control ON tasks(tenant_id, control_id);
CREATE INDEX idx_tasks_overdue ON tasks(tenant_id, status, due_date) WHERE status IN ('open', 'in_progress');

-- Evaluation history
CREATE TABLE eval_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id TEXT NOT NULL,
    framework TEXT NOT NULL,
    control_id TEXT NOT NULL,
    status TEXT NOT NULL,
    confidence FLOAT,
    evidence_hash TEXT,
    result JSONB NOT NULL,
    model_used TEXT,
    tier_used TEXT,
    latency_ms INT,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- System patterns
CREATE TABLE patterns (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pattern TEXT NOT NULL,
    context JSONB,
    confidence FLOAT NOT NULL,
    hit_count INT DEFAULT 1,
    source TEXT NOT NULL,
    embedding vector(1024),
    created_at TIMESTAMPTZ DEFAULT now(),
    last_used_at TIMESTAMPTZ,
    decay_applied_at TIMESTAMPTZ
);

-- Skills (versioned prompts)
CREATE TABLE skills (
    id TEXT PRIMARY KEY,
    current_version INT NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE skill_versions (
    skill_id TEXT REFERENCES skills(id),
    version INT NOT NULL,
    prompt_template TEXT NOT NULL,
    config JSONB,
    author TEXT NOT NULL,
    reason TEXT,
    status TEXT DEFAULT 'active',
    metrics JSONB,
    created_at TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (skill_id, version)
);

-- Interactions
CREATE TABLE interactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    messages JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Audit trail (append-only)
CREATE TABLE audit_trail (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    timestamp TIMESTAMPTZ DEFAULT now(),
    operation TEXT NOT NULL,
    tenant_id TEXT,
    agent TEXT,
    trace_id TEXT,
    data JSONB
);
-- No UPDATE or DELETE triggers/policies on audit_trail
```
