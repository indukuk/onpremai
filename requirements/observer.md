# Agent: Observer (observer)

## Purpose

Autonomous improvement agent. Watches all LLM calls and agent outcomes, detects issues, diagnoses root causes, proposes fixes, and applies them — with graduated autonomy (auto-apply → canary → human approval).

The observer makes the system better over time without code deploys.

## System Requirements Covered

| System Requirement | This module's role | Requirement ID |
|---|---|---|
| LLM Agnostic | Uses task="complex_reasoning" for diagnosis via gateway | R3 |
| Per-Tenant Budget | Pauses on credit exhaustion, tracks degradation events | R18 |
| Graceful Degradation | Defers diagnosis if strong tier unavailable, resumes automatically | R18 |
| PII-Aware Logging | Reads only aggregated metrics, never raw PII from logs | R13 |
| Observability | Consumes all service logs for pattern detection and analysis | R1 |
| Self-Improving | Core purpose: tunes routing, prompts, thresholds via graduated autonomy | R2-R10 |
| Self-Governing (AI Risk) | Generates model inventory, drift detection, bias monitoring, governance reports | R16 |
| Human-in-the-Loop | Tier 3 changes require human approval before execution | R5 |
| Multi-Tenant Isolation | Admin scope: reads cross-tenant aggregates but never copies tenant data | R13 |
| Independent Deploy | Own image, OBSERVER_VERSION tag | R14 |

## Core Responsibilities

1. Monitor: ingest all LLM gateway logs and agent outcomes
2. Detect: find performance issues (high escalation, low confidence, parse failures, cost spikes)
3. Diagnose: use reasoning (strong model) to understand root causes
4. Propose: generate concrete fixes (routing changes, prompt rewrites, model swaps)
5. Apply: execute fixes with appropriate safety (auto, canary, or human approval)
6. Validate: check if applied changes improved metrics, rollback if not
7. Learn: record successful patterns, evolve skills over time
8. Self-regulate: tighten/relax own autonomy based on track record

## Requirements

### R1: Log Ingestion

- Reads structured JSON logs from LLM gateway (mounted volume or API)
- Each log entry:
  ```json
  {
    "timestamp", "trace_id", "agent", "task", "tier_requested", "tier_used",
    "model_used", "escalated", "input_tokens", "output_tokens", "latency_ms",
    "confidence", "success", "error", "tenant_id", "tool_calls_count",
    "parse_success", "cost_usd"
  }
  ```
- Can query by time window, task, model, tenant, success/failure
- Retains raw logs for configurable period (default 7 days)
- Aggregates metrics for longer retention (30 days)

### R2: Issue Detection

- Runs on a schedule (configurable, default every hour)
- Detects:
  | Issue | Trigger |
  |-------|---------|
  | High escalation | >40% of calls for a task escalate |
  | Low confidence | Average confidence <0.7 for a task (min 10 samples) |
  | Parse failures | >15% structured output parse failures |
  | Cost spike | Avg cost >2x baseline for a task |
  | Model errors | >5% error rate for a model endpoint |
  | Latency spike | P95 latency >2x baseline |
  | Stale patterns | Patterns unused for >90 days |
  | Skill degradation | Skill metrics trending down over 7 days |

### R3: Diagnosis Engine

- For each detected issue: use strong-tier LLM to diagnose root cause
- Diagnosis input: issue metrics + sample calls (prompts, responses, errors)
- Diagnosis output:
  ```json
  {
    "root_cause": "description",
    "fix_type": "routing|prompt|threshold|model|pattern",
    "fix_description": "what to change",
    "confidence": 0.0-1.0,
    "requires_prompt_rewrite": true/false
  }
  ```
- Minimum confidence to act: 0.6 (below this: log observation, don't act)
- Uses its own `task="complex_reasoning"` calls through the LLM gateway

### R4: Fix Proposal

- Turn diagnosis into a concrete `Change` object:
  - `routing` change: move task to different tier
  - `prompt` change: rewrite a prompt template
  - `threshold` change: adjust confidence threshold
  - `model` change: add/swap model in a tier
  - `pattern` change: record/remove a pattern
- For prompt rewrites: observer asks strong model to rewrite, given:
  - Current prompt
  - Examples where it worked (high confidence)
  - Examples where it failed (low confidence)
  - The target model's capabilities/limitations

### R5: Apply Engine (Graduated Autonomy)

**Tier 1 — AUTO-APPLY (no human needed):**
- Routing changes (task → different tier)
- Confidence threshold adjustments
- Pattern recording/removal
- Tenant memory updates
- Requirements: confidence ≥ 0.80, min 20 samples of data

**Tier 2 — CANARY (test first, then roll out):**
- Prompt rewrites
- Model additions/swaps
- Fallback order changes
- Process:
  1. Deploy change to X% of traffic (default 20%)
  2. Run for minimum duration (default 4 hours)
  3. Collect minimum samples (default 30)
  4. Compare canary vs control on: confidence, escalation rate, failure rate
  5. If canary wins → promote to 100%
  6. If canary loses → rollback, record failure
- Requirements: confidence ≥ 0.70

**Tier 3 — HUMAN APPROVAL (notify and wait):**
- Model removal
- Escalation policy changes
- Any change type that previously failed canary
- Any change when circuit breaker is near threshold
- Process: store recommendation, send notification, wait for approval/rejection

### R6: Validation & Rollback

- After every auto-apply: schedule validation check (default 1 hour later)
- Validation compares metrics before and after:
  - Escalation rate increased >10% → rollback
  - Confidence decreased >10% → rollback
  - Failure rate increased >5% → rollback
  - Latency P95 increased >50% → rollback
- Rollback: revert to saved snapshot (pre-change state)
- Record rollback as a failure (affects future tier classification)

### R7: Circuit Breaker

- If 3+ rollbacks in 6 hours: STOP all auto-applies
- All subsequent changes escalated to human approval
- Circuit breaker resets after:
  - Configured cooldown (default 12 hours), OR
  - Human manually resets via admin API
- Notification sent when circuit breaker trips

### R8: Self-Regulation

- Weekly self-evaluation:
  - Count: total changes, auto-applied, canary passed/failed, rolled back
  - Calculate: success rate, net confidence improvement, net cost change
  - If rollback rate >30% → tighten policy (increase min_confidence by 0.05, increase min_samples by 10)
  - If rollback rate = 0% AND total changes >10 → relax policy slightly (decrease min_confidence by 0.02)
- Self-regulation bounds: min_confidence never below 0.60, never above 0.95
- Self-regulation is itself logged and auditable

### R9: Learning Jobs

- **On every completed evaluation** (event-driven):
  - Extract schema patterns (which columns mattered)
  - Extract evidence file patterns (naming conventions)
  - Record in patterns table
- **Every 6 hours** (prompt optimization):
  - Find tasks with declining metrics
  - Draft improved prompts
  - Deploy as canary
- **Daily** (model fitness):
  - Compare model performance across tasks
  - Recommend rebalancing

### R10: A/B Testing Support

- Observer can run A/B tests on prompts and models
- Tell LLM gateway to split traffic: `POST /admin/canary/{task}/set`
- Gateway tracks metrics separately for canary vs control
- Observer evaluates after sufficient samples: `GET /admin/canary/{task}/metrics`
- Statistical significance: minimum 30 samples per variant, p<0.05 confidence
- Promote winner or rollback loser

### R11: Observer Admin API

```
GET  /observer/status
  → last run times, pending items, active canaries, circuit breaker status

GET  /observer/changes?days=7&status=...
  → list all changes (applied, pending, rolled_back, canary_running)

GET  /observer/changes/{id}
  → change detail with diagnosis, evidence, outcome

POST /observer/changes/{id}/approve
  → approve a human-tier change

POST /observer/changes/{id}/reject
  → reject a change

GET  /observer/recommendations
  → pending human approvals

GET  /observer/metrics
  → observer's own performance (success rate, impact)

GET  /observer/self-eval
  → latest self-evaluation results

POST /observer/pause
  → pause all observer activity

POST /observer/resume
  → resume observer

POST /observer/circuit-breaker/reset
  → manually reset circuit breaker

POST /observer/run-now
  → trigger an immediate analysis cycle (for testing)
```

### R12: Notification System

- Notify on: auto-applies, canary results, rollbacks, circuit breaks, human-needed
- Channels (configurable):
  - Webhook (default): POST to configured URL
  - Log: structured log entry (always, regardless of other channels)
- Notification payload:
  ```json
  {
    "type": "auto_applied|canary_passed|canary_failed|rollback|human_needed|circuit_break",
    "change_id": "...",
    "summary": "Moved task 'evaluate_control' from mid to strong tier",
    "reason": "58% escalation rate over 48h",
    "confidence": 0.91,
    "timestamp": "..."
  }
  ```

### R13: Observability of Observer

- Observer's own LLM calls go through the gateway (task="complex_reasoning")
- Observer tracks its own cost (diagnosis calls can be expensive)
- Budget limit: configurable max spend per cycle (default $5)
- If diagnosis calls exceed budget: defer remaining issues to next cycle
- Observer logs its decisions: what it detected, what it diagnosed, what it applied, what it skipped and why

### R14: Container Packaging

- Single Docker image, independently versioned
- Version tag: `OBSERVER_VERSION`
- Depends on: LLM Gateway, Memory Service
- Reads: LLM gateway logs (mounted volume or API)
- Writes to: Memory Service (skills, patterns), LLM Gateway admin API (routing)
- Health check: `GET /health`
- Port: 6000 (admin API)
- No GPU required
- Runs as a single process with scheduled jobs (no external scheduler needed)

### R15: Configuration

```yaml
# Environment variables
LLM_GATEWAY_URL: http://llm-gateway:4000
LLM_GATEWAY_ADMIN_URL: http://llm-gateway:4001
MEMORY_URL: http://memory-service:5000
LOG_PATH: /logs                     # mounted from gateway
LOG_LEVEL: info
PORT: 6000

# Schedule
SCHEDULE_QUALITY_SEC: 3600          # every hour
SCHEDULE_PROMPTS_SEC: 21600         # every 6 hours
SCHEDULE_MODEL_FIT_SEC: 86400       # daily
SCHEDULE_SELF_EVAL_SEC: 604800      # weekly

# Policy
AUTO_APPLY_ENABLED: true
AUTO_APPLY_MIN_CONFIDENCE: 0.80
AUTO_APPLY_MIN_SAMPLES: 20
CANARY_TRAFFIC_PCT: 20
CANARY_MIN_DURATION_HOURS: 4
CANARY_MIN_SAMPLES: 30
CIRCUIT_BREAKER_MAX_ROLLBACKS: 3
CIRCUIT_BREAKER_WINDOW_HOURS: 6
CIRCUIT_BREAKER_COOLDOWN_HOURS: 12
MAX_AUTO_APPLIES_PER_DAY: 10
MAX_CONCURRENT_CANARIES: 3
OBSERVER_BUDGET_PER_CYCLE_USD: 5.00
VALIDATION_DELAY_MINUTES: 60

# Notifications
NOTIFY_WEBHOOK_URL: ${OBSERVER_WEBHOOK_URL:-}
NOTIFY_ON_AUTO_APPLY: true
NOTIFY_ON_CANARY: true
NOTIFY_ON_ROLLBACK: true
NOTIFY_ON_CIRCUIT_BREAK: true
```

### R16: AI Model Risk Governance (Self-Assessment)

The system deploys AI models for compliance evaluation — which itself is subject to model risk regulation (SR 11-7, EU AI Act, ECB guidelines). The observer monitors and documents the AI system's own model risk, making the system auditable for AI governance.

#### Why this matters:

Financial services customers under SR 11-7 and EU AI Act must demonstrate governance over AI/ML models used in risk and compliance decisions. Since agent-eval produces compliance assessments that feed audit opinions, it IS a model that needs governance. This is a competitive differentiator — the system governs itself.

#### What observer tracks:

**Model Inventory (automated):**
- All models in `routing.yaml` are automatically inventoried
- Per model: provider, version, tasks routed to it, deployment date, last health check
- Model changes tracked over time (when models were added, swapped, removed)
- Exposed via: `GET /observer/model-inventory`

**Model Performance Metrics (continuous):**
- Per model, per task:
  - Accuracy proxy: confidence scores over time (trend, distribution)
  - Consistency: same input → same output (measured via evidence hash caching)
  - Escalation rate: how often this model's output requires escalation
  - Parse success rate: structured output compliance
  - Drift detection: confidence distribution shifting over time (KS test on weekly windows)
- Exposed via: `GET /observer/model-performance/{model_id}`

**Decision Audit Trail:**
- Every observer action (routing change, prompt rewrite, model swap) is an auditable decision
- Stored with: rationale, evidence (metrics that triggered it), outcome, rollback status
- This IS the model change management log auditors need
- Exposed via: `GET /observer/changes` (already exists in R11)

**Bias and Fairness Monitoring:**
- Per tenant: track if evaluation scores systematically differ across similar evidence sets
- Flag if a model consistently scores one tenant's evidence lower than comparable evidence from others
- Not a full fairness framework — a signal that something may need investigation
- Threshold: >15% score variance across comparable evaluations triggers alert

**Model Validation Reports (periodic):**
- Weekly automated report: model health, drift indicators, performance trends
- Monthly automated report: full model inventory, changes made, validation results
- Format: structured JSON (consumed by platform for dashboard display) + human-readable summary
- Stored in memory: `memory.eval_store(type="model_governance_report")`
- Exposed via: `GET /observer/governance-report?period=weekly|monthly`

#### Observer admin API additions:

```
GET  /observer/model-inventory
  → all models with metadata, status, tasks, last validated

GET  /observer/model-performance/{model_id}
  → performance metrics over configurable time window

GET  /observer/governance-report?period=weekly|monthly
  → latest model governance report

GET  /observer/drift-alerts
  → active drift/bias alerts requiring attention
```

#### Configuration additions:

```yaml
# Model Risk Governance
MODEL_GOVERNANCE_ENABLED: true
DRIFT_DETECTION_WINDOW_DAYS: 7
DRIFT_THRESHOLD_KS_PVALUE: 0.05        # KS test p-value threshold
BIAS_VARIANCE_THRESHOLD: 0.15           # flag >15% cross-tenant variance
GOVERNANCE_REPORT_WEEKLY: true
GOVERNANCE_REPORT_MONTHLY: true
```

#### How this helps customers:

- **For SR 11-7**: model inventory, performance monitoring, change management, validation evidence
- **For EU AI Act**: risk classification documentation, monitoring of high-risk AI system, human oversight records
- **For auditors**: "Show me your AI governance" → point them at `/observer/governance-report`
- **For internal teams**: early warning when models degrade, before it affects evaluation quality

### R17: What Observer DOES NOT Do

- Does NOT modify agent source code
- Does NOT redeploy containers
- Does NOT access tenant data directly (only aggregated metrics)
- Does NOT override human rejections (if human says no, it's no)
- Does NOT run during circuit breaker cooldown
- Does NOT exceed its budget
- Does NOT apply changes faster than validation can confirm them
- Does NOT run diagnosis or optimization during credit exhaustion (pauses gracefully)

### R18: Credit Exhaustion Behavior

When the system enters degraded mode due to credit/budget exhaustion:

1. **Observer pauses all LLM-dependent jobs**: diagnosis, prompt optimization, model fitness analysis
2. **Observer continues metric collection**: log ingestion, aggregation, detection — these are code-only, no LLM
3. **Observer monitors budget status**: polls `GET /admin/credit-status` and `GET /admin/budget/{tenant_id}`
4. **Observer resumes automatically**: when credits replenish and gateway reports tiers available
5. **Observer tracks degradation events**: records when tenants enter/exit degraded mode as a metric (useful for governance reports)
6. **Observer's own budget**: observer uses `task="complex_reasoning"` (strong tier). If strong is exhausted, observer pauses entirely — it will not produce low-quality diagnosis on a weaker model.

### R19: Configuration (AWS-First)

```yaml
# Environment variables (AWS-first defaults)
LLM_GATEWAY_URL: http://llm-gateway:4000
LLM_GATEWAY_ADMIN_URL: http://llm-gateway:4001
MEMORY_URL: http://memory-service:5000
LOG_PATH: /logs
LOG_LEVEL: info
PORT: 6000
AWS_REGION: us-east-1

# Schedule
SCHEDULE_QUALITY_SEC: 3600
SCHEDULE_PROMPTS_SEC: 21600
SCHEDULE_MODEL_FIT_SEC: 86400
SCHEDULE_SELF_EVAL_SEC: 604800

# Policy
AUTO_APPLY_ENABLED: true
AUTO_APPLY_MIN_CONFIDENCE: 0.80
AUTO_APPLY_MIN_SAMPLES: 20
CANARY_TRAFFIC_PCT: 20
CANARY_MIN_DURATION_HOURS: 4
CANARY_MIN_SAMPLES: 30
CIRCUIT_BREAKER_MAX_ROLLBACKS: 3
CIRCUIT_BREAKER_WINDOW_HOURS: 6
CIRCUIT_BREAKER_COOLDOWN_HOURS: 12
MAX_AUTO_APPLIES_PER_DAY: 10
MAX_CONCURRENT_CANARIES: 3
OBSERVER_BUDGET_PER_CYCLE_USD: 5.00
VALIDATION_DELAY_MINUTES: 60

# Model Risk Governance
MODEL_GOVERNANCE_ENABLED: true
DRIFT_DETECTION_WINDOW_DAYS: 7
DRIFT_THRESHOLD_KS_PVALUE: 0.05
BIAS_VARIANCE_THRESHOLD: 0.15
GOVERNANCE_REPORT_WEEKLY: true
GOVERNANCE_REPORT_MONTHLY: true

# Notifications
NOTIFY_WEBHOOK_URL: ${OBSERVER_WEBHOOK_URL:-}
NOTIFY_ON_AUTO_APPLY: true
NOTIFY_ON_CANARY: true
NOTIFY_ON_ROLLBACK: true
NOTIFY_ON_CIRCUIT_BREAK: true
NOTIFY_ON_CREDIT_EXHAUSTION: true
```
