# Service: LLM Gateway (llm-gateway)

## Purpose

Single entry point for all LLM calls across the system. Routes requests to appropriate models based on task type, handles escalation when confidence is low, manages fallbacks, logs everything for the observer.

No agent ever talks to an LLM directly — they all go through this gateway.

## System Requirements Covered

| System Requirement | This module's role | Requirement ID |
|---|---|---|
| LLM Agnostic | Resolves task→tier→model via 3-level routing hierarchy | R3, R4, R4b |
| AWS-First w/ Adapters | BedrockAdapter primary, Anthropic/OpenAI-compatible fallback | R8, R17 |
| Per-Tenant Budget | Tracks cost/tenant, enforces daily/monthly ceiling, queues indefinitely | R16 |
| Graceful Degradation | Fallback within tier, escalate across tiers, then queue | R5 |
| PII-Aware Logging | Operational logs PII-free, prompt/response logging configurable | R9 |
| Observability | Logs every request with full metrics JSON for observer consumption | R9 |
| Self-Improving | Admin API accepts routing/threshold/canary updates from observer | R11 |
| Hot-Reload Config | File watcher on routing.yaml, admin API for programmatic updates | R14 |
| Multi-Tenant Isolation | Per-tenant rate limits, routing overrides, budget tracking | R12, R16 |
| Independent Deploy | Own image, LLM_GW_VERSION tag, config mounted as volume | R15 |

## Core Responsibilities

1. Task-based routing: map task names to model tiers
2. Escalation: retry at higher tier when confidence is below threshold
3. Fallback: if primary model fails, try next in line
4. Tool format translation: normalize tool calling across providers
5. Logging: every request/response logged for observer consumption
6. Canary support: split traffic for A/B testing prompts and models
7. Cost tracking: token counts and estimated cost per call
8. Rate limiting: per-tenant, per-model

## Requirements

### R1: Unified API

- Expose OpenAI-compatible `/v1/chat/completions` for basic calls
- Expose custom `/v1/complete` with task metadata (preferred by agents):
  ```json
  POST /v1/complete
  {
    "messages": [...],
    "task": "evaluate_control",
    "confidence_threshold": 0.8,
    "max_tokens": 4096,
    "temperature": 0.0,
    "response_format": {"type": "json_schema", "schema": {...}},
    "tools": [...],
    "tenant_id": "acme",
    "trace_id": "abc-123"
  }
  ```
- Response:
  ```json
  {
    "content": "...",
    "model_used": "meta-llama/Llama-3.1-70B-Instruct",
    "tier_used": "mid",
    "escalated": false,
    "usage": {"input_tokens": 2340, "output_tokens": 890},
    "latency_ms": 4200,
    "confidence": 0.85,
    "tool_calls": [...] 
  }
  ```

### R2: Embedding Endpoint

- `POST /v1/embed`
  ```json
  {"texts": ["text1", "text2", ...]}
  ```
- Response:
  ```json
  {"embeddings": [[0.1, 0.2, ...], [0.3, 0.4, ...]], "model_used": "nomic-embed-text"}
  ```
- Routes to embedding model configured in routing config

### R3: Model Tier System

- Three tiers: `fast`, `mid`, `strong`
- Each tier has one or more models (ordered by priority)
- If first model in tier fails → try next model in same tier
- If all models in tier fail → escalate to next tier (if escalation enabled)
- Tiers are logical — same physical model can appear in multiple tiers

### R4: Task Routing

- Every request includes a `task` field
- `task_routing` config maps task → default tier
- If task is unknown: use `mid` as default
- Observer can update task routing without gateway restart (hot-reload config)

### R4b: Granular Model Routing (per-agent, per-node, per-tenant)

Agents declare a `task` name. The gateway resolves which model to use via a **routing hierarchy** — most specific match wins:

```
Resolution order:
  1. tenant_routing[tenant_id][task]    → specific model for this customer
  2. agent_routing[agent_name][task]    → specific model for this agent's task
  3. task_routing[task]                 → default tier for this task type
```

#### Why this matters:

| Scenario | How it's handled | Who changes it |
|----------|-----------------|----------------|
| LLM vendor releases better model | Update `task_routing` → all agents use new model | Ops (config change) |
| agent-eval's code gen works better with Sonnet | Set `agent_routing.agent-eval.generate_code.model: sonnet` | Ops or observer |
| A customer pays for premium tier | Set `tenant_routing.acme.evaluate_control.model: opus` | Sales/admin |
| Observer finds router works fine with 8B but eval needs 70B | Already handled — different tasks, different tiers | Observer (auto-adjust) |
| New model released, want to test on 20% of eval traffic | Use canary: `agent_routing.agent-eval.evaluate_control.canary: {model: new-model, pct: 20}` | Observer or ops |
| Customer is air-gapped, can only use local models | `tenant_routing.customer.* → only local models` | Deployment config |

#### What agents send (unchanged — agents never specify models):

```json
POST /v1/complete
{
  "messages": [...],
  "task": "evaluate_control",      ← agent declares WHAT it's doing
  "agent": "agent-eval",           ← agent identifies itself
  "tenant_id": "acme_corp",        ← from user context
  "trace_id": "..."
}
```

#### What gateway resolves:

```python
def resolve_model(agent: str, task: str, tenant_id: str) -> Model:
    # 1. Tenant-specific override?
    if tenant_id in tenant_routing and task in tenant_routing[tenant_id]:
        return get_model(tenant_routing[tenant_id][task])
    
    # 2. Agent-specific override?
    if agent in agent_routing and task in agent_routing[agent]:
        return get_model(agent_routing[agent][task])
    
    # 3. Default task → tier
    tier = task_routing.get(task, "mid")
    return get_primary_model(tier)
```

#### Hot-swap without redeploy:

- All routing is in `config/routing.yaml` (mounted volume)
- Gateway hot-reloads on file change
- Admin API: `POST /admin/routing` to update programmatically
- Observer can update routing via admin API (graduated autonomy)
- **No agent redeploy needed. Ever. For any model change.**

#### Model lifecycle (when LLMs get deprecated):

```yaml
# Example: migrating from Claude Sonnet 4.5 to 4.6

# Step 1: Add new model to tier
mid:
  models:
    - id: sonnet-4.5     # existing
    - id: sonnet-4.6     # new, added as second option

# Step 2: Canary test (20% traffic to new model)
canary:
  agent-eval/evaluate_control:
    model: sonnet-4.6
    traffic_pct: 20

# Step 3: Observer validates (confidence, quality, latency)
# Step 4: Promote (observer or ops)
mid:
  models:
    - id: sonnet-4.6     # now primary
    - id: sonnet-4.5     # fallback (will remove after 1 week)

# Step 5: Remove old model
mid:
  models:
    - id: sonnet-4.6     # only model

# Total agent code changes: ZERO
```

### R5: Escalation Logic

- Triggered when:
  - Agent declares `confidence_threshold` AND response confidence < threshold
  - Response is empty or unparseable
  - Structured output doesn't match requested schema
  - Model returns a refusal
- Escalation path: fast → mid → strong
- Max escalations per request: configurable (default 2)
- Escalation is transparent to the agent (just gets the final answer)
- Log entry marks `escalated: true` with original tier and final tier

### R6: Confidence Extraction

- If response contains parseable JSON with a `confidence` field → use it
- If structured_output schema has a `confidence` field → extract it
- Otherwise: heuristic scoring:
  - Empty response → confidence 0.0
  - Parse failure on expected JSON → confidence 0.3
  - Very short response (< 50 chars) for complex task → confidence 0.4
  - Normal response → confidence 0.8 (assumed)

### R7: Tool Format Translation

- Agents send tools in OpenAI function-calling format (universal)
- Gateway translates to provider-specific format:
  - Anthropic API: `tools` array with `input_schema`
  - OpenAI API: `tools` array with `function` (pass through)
  - vLLM/Ollama with Hermes: inject tool descriptions into system prompt
  - Models without native tool support: use ReAct-style prompting
- Response translation: normalize tool calls back to OpenAI format
- This means agents work with ANY model — even ones without native function calling

### R8: Provider Support (Adapter-Based)

**V1 adapters (shipped):**
- AWS Bedrock (cloud, **primary**): Converse API — supports Claude, Titan, Llama on Bedrock
- Anthropic API (cloud): Messages API with tool use — fallback when Bedrock throttles
- OpenAI-compatible (generic): covers vLLM, Ollama, OpenRouter, any compatible endpoint

**Future adapters (not V1):**
- Azure OpenAI (cloud): Chat completions
- Google Vertex AI (cloud): Gemini API
- Ollama-native (local): chat completions + embeddings (for on-prem profile)

**Adapter interface:** each adapter implements `complete()`, `embed()`, `health_check()`, `estimate_cost()`. Adding a new provider: add adapter class, register in factory, no gateway core rewrite.

### R9: Logging (for Observer)

- Every request/response logged as structured JSON:
  ```json
  {
    "timestamp": "2026-05-10T14:32:01Z",
    "trace_id": "abc-123",
    "agent": "agent-eval",
    "task": "evaluate_control",
    "tier_requested": "mid",
    "tier_used": "mid",
    "model_used": "meta-llama/Llama-3.1-70B-Instruct",
    "escalated": false,
    "escalation_path": [],
    "input_tokens": 2340,
    "output_tokens": 890,
    "latency_ms": 4200,
    "confidence": 0.85,
    "success": true,
    "error": null,
    "tenant_id": "acme_corp",
    "tool_calls_count": 0,
    "parse_success": true,
    "cost_usd": 0.0012
  }
  ```
- Logs written to local volume (consumed by observer)
- Optional: forward to external logging (stdout, file, webhook)

### R10: Canary / A/B Testing

- Gateway supports splitting traffic for a task between versions:
  ```json
  {"task": "evaluate_control", "canary": {"version": "v4", "traffic_pct": 20}}
  ```
- Canary can be a different prompt (sent by memory service) or a different model
- Metrics tracked separately for canary vs control
- Observer calls `GET /admin/canary/{task}/metrics` to evaluate
- Observer calls `POST /admin/canary/{task}/promote` or `/rollback`

### R11: Admin API (for Observer)

- `GET /admin/metrics?window=1h` — aggregated metrics by task/model/tier
- `GET /admin/metrics/{task}` — metrics for specific task
- `POST /admin/routing` — update task→tier mapping (hot reload)
- `POST /admin/threshold` — update confidence threshold for a task
- `GET /admin/canary/{task}/metrics` — canary vs control comparison
- `POST /admin/canary/{task}/set` — start a canary
- `POST /admin/canary/{task}/promote` — canary → 100%
- `POST /admin/canary/{task}/rollback` — remove canary
- `GET /admin/models` — list configured models and health
- `POST /admin/models/{id}/disable` — temporarily disable a model
- `POST /admin/reload` — hot-reload routing config from file

### R12: Rate Limiting & Cost Control

- Per-tenant rate limits (requests/min, tokens/min)
- Per-model rate limits (respect provider limits)
- Cost ceiling per request (abort if projected cost exceeds max)
- Cost ceiling per tenant per day
- Return 429 with retry-after when limited

### R13: Health & Readiness

- `GET /health` — gateway process alive
- `GET /ready` — at least one model per tier is reachable
- Periodic model health checks (ping each configured model endpoint)
- Unhealthy models auto-removed from rotation, re-added when healthy

### R14: Configuration

```yaml
# config/routing.yaml (hot-reloadable)
# AWS-first: Bedrock is primary, Anthropic direct API as fallback

tiers:
  fast:
    models:
      - id: haiku-bedrock
        provider: bedrock
        model: us.anthropic.claude-haiku-4-5-20251001-v1:0
        region: us-east-1
        max_tokens: 2048
        timeout_ms: 15000
      - id: haiku-direct                    # fallback if Bedrock throttles
        provider: anthropic
        model: claude-haiku-4-5-20251001
        api_key: ${ANTHROPIC_API_KEY}
        max_tokens: 2048
        timeout_ms: 15000
    
  mid:
    models:
      - id: sonnet-bedrock
        provider: bedrock
        model: us.anthropic.claude-sonnet-4-20250514-v1:0
        region: us-east-1
        max_tokens: 4096
        timeout_ms: 60000
      - id: sonnet-direct                   # fallback if Bedrock throttles
        provider: anthropic
        model: claude-sonnet-4-20250514
        api_key: ${ANTHROPIC_API_KEY}
        max_tokens: 4096
        timeout_ms: 60000

  strong:
    models:
      - id: opus-bedrock
        provider: bedrock
        model: us.anthropic.claude-opus-4-20250514-v1:0
        region: us-east-1
        max_tokens: 8192
        timeout_ms: 120000
      - id: opus-direct                     # fallback
        provider: anthropic
        model: claude-opus-4-20250514
        api_key: ${ANTHROPIC_API_KEY}
        max_tokens: 8192
        timeout_ms: 120000

## Routing Hierarchy (most specific wins)

# Level 1: Default — task → tier (catches everything)
task_routing:
  classify_intent: fast
  extract_schema: fast
  discover_evidence: fast
  evaluate_control: mid
  evaluate_unstructured: mid
  generate_code: mid
  fix_code: mid
  tool_selection: fast
  chat_response: fast
  skill_execution: mid
  complex_reasoning: strong
  cross_framework_analysis: strong

# Level 2: Per-agent override — agent+task → tier or specific model
agent_routing:
  agent-eval:
    evaluate_control: mid              # uses tier (default model in tier)
    generate_code:
      model: sonnet-cloud              # pin to specific model (not tier)
    classify_intent: fast

  compliance-assistant:
    tool_selection: fast
    skill_execution:
      model: sonnet-cloud              # assistant always uses Sonnet for skills
    chat_response: fast

  observer:
    complex_reasoning:
      model: opus-cloud                # observer always uses strongest for diagnosis

# Level 3: Per-tenant override — tenant+task → model (for customers with preferences)
tenant_routing:
  acme_corp:
    evaluate_control:
      model: opus-cloud                # Acme pays for premium, gets Opus for evals
  
  startup_inc:
    evaluate_control: fast             # Startup on budget, uses fast tier for evals

# Resolution order: tenant_routing > agent_routing > task_routing
# Most specific match wins.

escalation:
  enabled: true
  max_escalations: 2
  path: [fast, mid, strong]

embedding:
  model:
    provider: bedrock
    model: amazon.titan-embed-text-v2:0
    region: us-east-1

rate_limits:
  per_tenant:
    requests_per_minute: 60
    tokens_per_minute: 100000
  per_model:
    haiku-bedrock: {rpm: 100}
    sonnet-bedrock: {rpm: 50}
    opus-bedrock: {rpm: 20}

budget:
  tracking_enabled: true
  default_daily_limit_usd: 50.00
  default_monthly_limit_usd: 1000.00
  warning_threshold_pct: 80
  queue_persistence: true
  queue_poll_interval_sec: 60

cost:
  max_per_request_usd: 1.00

policy:
  allow_cloud_fallback: true     # false for air-gapped deployments
  log_prompts: true              # false in prod if prompts contain PII
  log_responses: true
```

### R15: Container Packaging

- Single Docker image, independently versioned
- Version tag: `LLM_GW_VERSION`
- Config mounted as volume (not baked in image)
- Hot-reload on config file change (inotify or poll)
- Ports: 4000 (agent-facing), 4001 (admin API, internal only)
- No GPU required (gateway is a router, not inference)
- Lightweight: Python + FastAPI or Go for performance

### R16: Credit & Quota Management (Per-Tenant Budget Tracking)

The gateway tracks LLM spend per tenant (customer) and manages graceful degradation when budgets or provider credits are exhausted.

#### Why per-tenant (not per-user):

- Billing is at the customer/organization level, not individual users
- One tenant's exhaustion MUST NOT affect other tenants
- Tenant admin sets their own budget ceiling
- Users within a tenant share the tenant's pool

#### Budget tracking:

```python
# Per-tenant budget state (persisted in StateClient)
class TenantBudget:
    tenant_id: str
    daily_limit_usd: float          # configured by tenant admin
    monthly_limit_usd: float        # hard ceiling
    daily_spent_usd: float          # resets at midnight UTC
    monthly_spent_usd: float        # resets on 1st of month
    current_degradation_level: int  # 0=full, 1-4=degraded
    queue_depth: int                # requests waiting for budget
    last_reset_at: datetime
```

Every LLM response includes cost metadata from the provider. Gateway accumulates per tenant:
```python
def track_cost(tenant_id: str, response: ProviderResponse):
    cost = calculate_cost(response.model, response.input_tokens, response.output_tokens)
    budget = get_tenant_budget(tenant_id)
    budget.daily_spent_usd += cost
    budget.monthly_spent_usd += cost
    
    if budget.monthly_spent_usd >= budget.monthly_limit_usd:
        trigger_degradation(tenant_id, level=4)  # all tiers exhausted
    elif budget.daily_spent_usd >= budget.daily_limit_usd:
        trigger_degradation(tenant_id, level=2)  # restrict to fast tier
```

#### Degradation levels:

| Level | Condition | Tiers Available | User Impact |
|:-----:|-----------|-----------------|-------------|
| 0 | Budget healthy | fast, mid, strong | Full service |
| 1 | Daily budget >80% OR strong-tier provider throttling | fast, mid | Complex reasoning downgrades to mid |
| 2 | Daily budget exceeded OR mid-tier provider throttling | fast only | Evaluations use rules + fast-tier LLM |
| 3 | All cloud providers throttling/erroring | none (queue) | All LLM requests queued indefinitely |
| 4 | Monthly budget exceeded | none (queue) | All LLM requests queued until month resets |

#### Provider credit exhaustion detection:

```python
def detect_credit_exhaustion(provider: str, error: ProviderError) -> bool:
    """Detect when provider credits/quota are gone (not transient)."""
    # Bedrock: ThrottlingException with "quota exceeded" or ServiceQuotaExceededException
    if provider == "bedrock" and error.code in ("ThrottlingException", "ServiceQuotaExceededException"):
        return True
    # Anthropic: 429 with "credit balance" or 402 Payment Required
    if provider == "anthropic" and (error.status == 402 or "credit" in error.message.lower()):
        return True
    # OpenAI: 429 with "quota" in message
    if provider == "openai" and error.status == 429 and "quota" in error.message.lower():
        return True
    return False
```

#### Queue behavior (when budget/credits exhausted):

- Requests that cannot be served are **queued indefinitely** (no TTL, no expiry)
- Queue is persisted (survives gateway restart) via StateClient
- When budget resets or credits replenish, queued requests process in priority order:
  1. Tenant priority (paid tier > free tier)
  2. Task criticality: `strong` tasks first (they waited longest for good reason)
  3. FIFO within same priority
- Gateway polls provider health every 60s — when a previously-exhausted provider responds OK, drain queue
- Queue depth exposed via admin API and health endpoint
- Agents receive `LLMCreditExhaustedError` with `can_queue=True` and `queued_position`
- Agent decides: accept queue (async eval) or fall back to deterministic-only (sync response)

#### Admin API additions:

```
GET  /admin/budget/{tenant_id}
  → {daily_limit, daily_spent, monthly_limit, monthly_spent, degradation_level, queue_depth}

POST /admin/budget/{tenant_id}
  body: {daily_limit_usd, monthly_limit_usd}
  → update tenant budget limits

GET  /admin/budget/{tenant_id}/history?days=30
  → daily spend history for trend analysis

GET  /admin/credit-status
  → per-provider credit health {provider: status, last_error, last_success}

POST /admin/queue/{tenant_id}/drain
  → manually trigger queue drain (for testing or after manual credit top-up)

GET  /admin/queue/{tenant_id}
  → {depth, oldest_request, priority_breakdown}
```

#### Agent-facing response on credit exhaustion:

```json
{
  "error": "credit_exhausted",
  "degradation_level": 3,
  "tier_availability": {"fast": "exhausted", "mid": "exhausted", "strong": "exhausted"},
  "queued": true,
  "queue_position": 7,
  "estimated_recovery": "2026-06-02T00:00:00Z",
  "message": "Tenant monthly budget exceeded. Request queued — will process when budget resets."
}
```

#### Notifications:

| Event | Trigger | Who to notify |
|-------|---------|---------------|
| Budget warning | Daily spend >80% of limit | Tenant admin (webhook) |
| Budget exceeded | Daily or monthly limit hit | Tenant admin + observer |
| Provider exhausted | Credit/quota error from provider | System admin (ops) |
| Queue growing | >50 queued requests for a tenant | Tenant admin |
| Queue draining | Credits restored, processing backlog | Tenant admin |

#### Configuration additions:

```yaml
# config/routing.yaml additions
budget:
  tracking_enabled: true
  default_daily_limit_usd: 50.00
  default_monthly_limit_usd: 1000.00
  warning_threshold_pct: 80        # notify at 80% of daily limit
  queue_persistence: true           # persist queue across restarts
  queue_poll_interval_sec: 60       # check provider health for queue drain
  cost_per_model:                   # cost per 1K tokens (input/output)
    claude-haiku-4-5:    {input: 0.001, output: 0.005}
    claude-sonnet-4:     {input: 0.003, output: 0.015}
    claude-opus-4:       {input: 0.015, output: 0.075}
    titan-embed-v2:      {input: 0.0001, output: 0}

### R17: AWS-First Provider Configuration

The gateway ships with Bedrock as the primary provider. Adapter pattern ensures other providers plug in without gateway changes.

#### Default tier mapping (AWS/Bedrock):

```yaml
tiers:
  fast:
    models:
      - id: haiku-bedrock
        provider: bedrock
        model: us.anthropic.claude-haiku-4-5-20251001-v1:0
        region: us-east-1
        max_tokens: 2048
        timeout_ms: 15000

  mid:
    models:
      - id: sonnet-bedrock
        provider: bedrock
        model: us.anthropic.claude-sonnet-4-20250514-v1:0
        region: us-east-1
        max_tokens: 4096
        timeout_ms: 60000

  strong:
    models:
      - id: opus-bedrock
        provider: bedrock
        model: us.anthropic.claude-opus-4-20250514-v1:0
        region: us-east-1
        max_tokens: 8192
        timeout_ms: 120000

embedding:
  model:
    provider: bedrock
    model: amazon.titan-embed-text-v2:0
    region: us-east-1
```

#### Provider adapter interface:

```python
class ProviderAdapter(ABC):
    """Base class for all LLM provider adapters."""
    
    @abstractmethod
    async def complete(self, request: CompletionRequest) -> CompletionResponse: ...
    
    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]: ...
    
    @abstractmethod
    async def health_check(self) -> bool: ...
    
    @abstractmethod
    def estimate_cost(self, input_tokens: int, output_tokens: int) -> float: ...
```

#### Shipped adapters (V1):

| Adapter | Provider | Auth | Notes |
|---------|----------|------|-------|
| `BedrockAdapter` | AWS Bedrock | IAM role (boto3 default chain) | Primary. Converse API. |
| `AnthropicAdapter` | Anthropic API | API key | Fallback if Bedrock throttles |
| `OpenAICompatibleAdapter` | Any OpenAI-compatible endpoint | API key | For vLLM, Ollama, OpenRouter |

#### Future adapters (not V1):

| Adapter | When |
|---------|------|
| `AzureOpenAIAdapter` | When Azure customers need it |
| `VertexAIAdapter` | When GCP customers need it |
| `OllamaAdapter` | When on-prem profile ships |

Adding a new provider: implement `ProviderAdapter`, register in adapter factory, add model config to `routing.yaml`. Zero gateway core changes.

#### Bedrock-specific behaviors:

- Auth: uses boto3 default credential chain (IAM role on ECS/EC2, env vars locally)
- Cross-region inference: supported via `region` field per model (for capacity)
- Converse API: normalizes tool calling across Claude/Titan/Llama on Bedrock
- Throttling: Bedrock returns `ThrottlingException` — gateway marks model as throttled, tries fallback
- Provisioned throughput: if configured, gateway uses provisioned model ARN instead of on-demand
```
