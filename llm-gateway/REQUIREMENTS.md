# Service: LLM Gateway (llm-gateway)

## Purpose

Single entry point for all LLM calls across the system. Routes requests to appropriate models based on task type, handles escalation when confidence is low, manages fallbacks, logs everything for the observer.

No agent ever talks to an LLM directly — they all go through this gateway.

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

### R8: Provider Support

- Ollama (local): chat completions + embeddings
- vLLM (local): OpenAI-compatible API
- Anthropic API (cloud): Messages API with tool use
- OpenAI API (cloud): Chat completions with function calling
- AWS Bedrock (cloud): Converse API
- Azure OpenAI (cloud): Chat completions
- Google Vertex AI (cloud): Gemini API
- Any OpenAI-compatible endpoint (generic)
- Adding a new provider: add adapter class, no gateway rewrite

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

tiers:
  fast:
    models:
      - id: ollama-8b
        provider: ollama
        model: llama3.1:8b
        endpoint: http://ollama:11434
        max_tokens: 2048
        timeout_ms: 15000
      - id: haiku-cloud
        provider: anthropic
        model: claude-haiku-4-5-20251001
        api_key: ${ANTHROPIC_API_KEY}
        max_tokens: 2048
        timeout_ms: 15000
    
  mid:
    models:
      - id: vllm-70b
        provider: vllm
        model: meta-llama/Llama-3.1-70B-Instruct
        endpoint: http://vllm:8000
        max_tokens: 4096
        timeout_ms: 60000
      - id: sonnet-cloud
        provider: anthropic
        model: claude-sonnet-4-20250514
        api_key: ${ANTHROPIC_API_KEY}
        max_tokens: 4096
        timeout_ms: 60000

  strong:
    models:
      - id: opus-cloud
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
    provider: ollama
    model: nomic-embed-text
    endpoint: http://ollama:11434

rate_limits:
  per_tenant:
    requests_per_minute: 60
    tokens_per_minute: 100000
  per_model:
    ollama-8b: {rpm: 100}
    vllm-70b: {rpm: 50}

cost:
  max_per_request_usd: 1.00
  max_per_tenant_per_day_usd: 50.00

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
