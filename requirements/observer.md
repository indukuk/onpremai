# Agent: Observer (observer)

## Purpose

Autonomous improvement agent. Watches all LLM calls and agent outcomes, detects issues, diagnoses root causes, proposes fixes, and applies them — with graduated autonomy (auto-apply → canary → human approval).

The observer makes the system better over time without code deploys.

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

### R16: What Observer DOES NOT Do

- Does NOT modify agent source code
- Does NOT redeploy containers
- Does NOT access tenant data directly (only aggregated metrics)
- Does NOT override human rejections (if human says no, it's no)
- Does NOT run during circuit breaker cooldown
- Does NOT exceed its budget
- Does NOT apply changes faster than validation can confirm them
