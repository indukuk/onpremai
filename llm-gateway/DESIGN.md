# LLM Gateway — Architecture Design

## Overview

The LLM Gateway is the single entry point for ALL LLM calls across the system. No agent ever talks to a model directly. The gateway owns routing, escalation, fallback, tool format translation, cost tracking, and logging. Agents declare WHAT they are doing (task name); the gateway decides HOW (which model, which tier, which provider).

This design enables model changes, tier rebalancing, canary testing, and provider migrations without any agent code changes or redeployments.

---

## High-Level Architecture

```mermaid
graph TB
    subgraph "Agents (Callers)"
        AE[agent-eval]
        CA[compliance-assistant]
        OB[observer]
        PP[preprocessor]
        OTHER[any future agent]
    end

    subgraph "LLM Gateway Container"
        PORT4000[Port 4000<br/>Agent-Facing API]
        PORT4001[Port 4001<br/>Admin API]
        
        subgraph "Request Pipeline"
            ROUTER[Route Resolver<br/>tenant → agent → task]
            CANARY[Canary Splitter<br/>traffic % routing]
            ESCAL[Escalation Engine<br/>confidence check + retry]
            FALLBACK[Fallback Handler<br/>next model in tier]
        end

        subgraph "Provider Layer"
            ADAPTER[Provider Adapter Registry]
            OLLAMA_A[Ollama Adapter]
            VLLM_A[vLLM Adapter]
            ANTH_A[Anthropic Adapter]
            OAI_A[OpenAI Adapter]
            BED_A[Bedrock Adapter]
            AZ_A[Azure Adapter]
            VTX_A[Vertex AI Adapter]
        end

        subgraph "Cross-Cutting"
            TOOL_TX[Tool Format Translator]
            RATE[Rate Limiter]
            COST[Cost Calculator]
            HEALTH[Health Checker]
            LOGGER[Request Logger]
            CONFIG[Config Manager<br/>hot-reload]
        end
    end

    subgraph "Model Providers"
        OLL[Ollama<br/>local 8B/13B]
        VLM[vLLM<br/>local 70B]
        ANT[Anthropic API<br/>Haiku/Sonnet/Opus]
        OAI[OpenAI API<br/>GPT-4o etc.]
        BDK[AWS Bedrock<br/>Converse API]
        AZR[Azure OpenAI]
        VTX[Google Vertex AI<br/>Gemini]
    end

    subgraph "Observability"
        LOGS[/Log Volume/]
        OBS_SVC[Observer Service]
    end

    AE & CA & OB & PP & OTHER -->|POST /v1/complete| PORT4000
    OBS_SVC -->|Admin API| PORT4001
    
    PORT4000 --> ROUTER
    ROUTER --> CANARY
    CANARY --> ESCAL
    ESCAL --> FALLBACK
    FALLBACK --> ADAPTER
    
    ADAPTER --> OLLAMA_A --> OLL
    ADAPTER --> VLLM_A --> VLM
    ADAPTER --> ANTH_A --> ANT
    ADAPTER --> OAI_A --> OAI
    ADAPTER --> BED_A --> BDK
    ADAPTER --> AZ_A --> AZR
    ADAPTER --> VTX_A --> VTX

    LOGGER --> LOGS
    LOGS --> OBS_SVC
    PORT4001 --> CONFIG
```

---

## Request Resolution Flow

The routing hierarchy determines which model handles a request. Most specific match wins.

```mermaid
flowchart TD
    REQ[Incoming Request<br/>agent=agent-eval, task=evaluate_control, tenant=acme_corp]
    
    REQ --> L1{Level 1: tenant_routing<br/>acme_corp + evaluate_control?}
    
    L1 -->|Match found| L1_RES[Use tenant override<br/>e.g. opus-cloud]
    L1 -->|No match| L2{Level 2: agent_routing<br/>agent-eval + evaluate_control?}
    
    L2 -->|Match found| L2_RES[Use agent override<br/>e.g. mid tier or specific model]
    L2 -->|No match| L3{Level 3: task_routing<br/>evaluate_control?}
    
    L3 -->|Match found| L3_RES[Use task default tier<br/>e.g. mid]
    L3 -->|No match| DEFAULT[Default: mid tier]
    
    L1_RES --> RESOLVE[Resolve to Model]
    L2_RES --> RESOLVE
    L3_RES --> RESOLVE
    DEFAULT --> RESOLVE
    
    RESOLVE --> CANARY{Canary active<br/>for this route?}
    CANARY -->|Yes: roll dice| SPLIT{Traffic split}
    CANARY -->|No| PRIMARY[Use primary model in tier]
    
    SPLIT -->|80% control| PRIMARY
    SPLIT -->|20% canary| CANARY_MODEL[Use canary model]
    
    PRIMARY --> HEALTH_CHECK{Model healthy?}
    CANARY_MODEL --> HEALTH_CHECK
    
    HEALTH_CHECK -->|Healthy| EXECUTE[Execute request]
    HEALTH_CHECK -->|Unhealthy| NEXT[Next model in tier]
    
    NEXT --> HEALTH_CHECK
```

---

## Escalation Flow

When confidence is below threshold, the gateway transparently retries at a higher tier.

```mermaid
sequenceDiagram
    participant A as Agent
    participant GW as Gateway Router
    participant FAST as Fast Tier<br/>(Llama 8B)
    participant MID as Mid Tier<br/>(Llama 70B)
    participant STRONG as Strong Tier<br/>(Opus)
    participant LOG as Logger

    A->>GW: complete(task=evaluate_control, confidence_threshold=0.8)
    
    Note over GW: Route resolves to: mid tier
    GW->>MID: Request to Llama 70B
    MID-->>GW: Response (confidence=0.55)
    
    Note over GW: 0.55 < 0.80 threshold<br/>Escalation #1: mid → strong
    GW->>STRONG: Same request to Opus
    STRONG-->>GW: Response (confidence=0.92)
    
    Note over GW: 0.92 >= 0.80 threshold<br/>Escalation success
    GW->>LOG: Log: escalated=true, path=[mid, strong]
    GW-->>A: Response (confidence=0.92, model=opus, escalated=true)

    Note over A: Agent sees final answer only.<br/>Escalation is transparent.
```

```mermaid
flowchart TD
    START[Response received from model]
    
    START --> CONF{Extract confidence}
    
    CONF --> JSON_CHECK{Response has<br/>JSON confidence field?}
    JSON_CHECK -->|Yes| USE_FIELD[Use explicit confidence value]
    JSON_CHECK -->|No| HEURISTIC{Apply heuristics}
    
    HEURISTIC --> EMPTY{Empty response?}
    EMPTY -->|Yes| C00[confidence = 0.0]
    EMPTY -->|No| PARSE{Parse failure on<br/>expected JSON?}
    PARSE -->|Yes| C03[confidence = 0.3]
    PARSE -->|No| SHORT{Very short<br/>< 50 chars for complex task?}
    SHORT -->|Yes| C04[confidence = 0.4]
    SHORT -->|No| C08[confidence = 0.8 assumed]
    
    USE_FIELD --> THRESHOLD
    C00 --> THRESHOLD
    C03 --> THRESHOLD
    C04 --> THRESHOLD
    C08 --> THRESHOLD
    
    THRESHOLD{confidence >= threshold?}
    THRESHOLD -->|Yes| RETURN[Return response to caller]
    THRESHOLD -->|No| ESC_CHECK{Escalations remaining?<br/>current < max_escalations}
    
    ESC_CHECK -->|Yes| NEXT_TIER[Move to next tier in path<br/>fast→mid→strong]
    ESC_CHECK -->|No| RETURN_BEST[Return best response so far<br/>mark escalated=true]
    
    NEXT_TIER --> RETRY[Retry request at higher tier]
    RETRY --> START
```

---

## Provider Adapter Pattern

All provider differences are encapsulated behind a common interface. Adding a new provider means implementing one adapter class.

```mermaid
classDiagram
    class ProviderAdapter {
        <<interface>>
        +complete(request: NormalizedRequest) NormalizedResponse
        +embed(texts: list[str]) list[list[float]]
        +health_check() bool
        +estimate_cost(input_tokens, output_tokens) float
    }

    class NormalizedRequest {
        +messages: list[Message]
        +tools: list[Tool]  -- OpenAI format
        +max_tokens: int
        +temperature: float
        +response_format: ResponseFormat
        +stop: list[str]
    }

    class NormalizedResponse {
        +content: str
        +tool_calls: list[ToolCall]  -- OpenAI format
        +usage: Usage
        +finish_reason: str
        +raw_response: dict
    }

    class OllamaAdapter {
        +endpoint: str
        +complete()
        +embed()
        +health_check()
    }

    class VLLMAdapter {
        +endpoint: str
        +complete()
        +health_check()
    }

    class AnthropicAdapter {
        +api_key: str
        +complete()
        +health_check()
    }

    class OpenAIAdapter {
        +api_key: str
        +complete()
        +embed()
        +health_check()
    }

    class BedrockAdapter {
        +region: str
        +complete()
        +health_check()
    }

    class AzureAdapter {
        +endpoint: str
        +api_key: str
        +complete()
        +embed()
        +health_check()
    }

    class VertexAIAdapter {
        +project_id: str
        +region: str
        +complete()
        +health_check()
    }

    ProviderAdapter <|.. OllamaAdapter
    ProviderAdapter <|.. VLLMAdapter
    ProviderAdapter <|.. AnthropicAdapter
    ProviderAdapter <|.. OpenAIAdapter
    ProviderAdapter <|.. BedrockAdapter
    ProviderAdapter <|.. AzureAdapter
    ProviderAdapter <|.. VertexAIAdapter
```

```mermaid
graph LR
    subgraph "Gateway Internal"
        NR[Normalized Request<br/>OpenAI-format tools<br/>standard messages]
    end

    subgraph "Adapter Translation"
        NR --> TX{Provider Adapter}
        TX -->|Ollama| OLL_FMT[Ollama /api/chat<br/>tools in system prompt]
        TX -->|vLLM| VLLM_FMT[OpenAI-compat /v1/chat/completions<br/>pass through]
        TX -->|Anthropic| ANTH_FMT[Messages API<br/>tools → input_schema format]
        TX -->|OpenAI| OAI_FMT[Chat API<br/>pass through]
        TX -->|Bedrock| BDK_FMT[Converse API<br/>toolConfig format]
        TX -->|Azure| AZ_FMT[Azure Chat API<br/>pass through]
        TX -->|Vertex| VTX_FMT[Gemini API<br/>functionDeclarations format]
    end

    subgraph "Response Normalization"
        OLL_FMT --> NR2[Normalized Response<br/>OpenAI-format tool_calls]
        VLLM_FMT --> NR2
        ANTH_FMT --> NR2
        OAI_FMT --> NR2
        BDK_FMT --> NR2
        AZ_FMT --> NR2
        VTX_FMT --> NR2
    end
```

---

## Tool Format Translation Flow

Agents always send tools in OpenAI function-calling format. The gateway handles all translation to/from provider-specific formats.

```mermaid
sequenceDiagram
    participant Agent as Agent<br/>(OpenAI format)
    participant GW as Gateway<br/>Tool Translator
    participant ANTH as Anthropic API

    Note over Agent: Sends tools in OpenAI format
    Agent->>GW: tools: [{type: "function", function: {name, description, parameters}}]
    
    Note over GW: Translate to Anthropic format
    GW->>GW: Transform each tool:<br/>OpenAI function → Anthropic tool<br/>{name, description, input_schema}
    
    GW->>ANTH: tools: [{name, description, input_schema: {type: "object", properties: ...}}]
    
    ANTH-->>GW: content: [{type: "tool_use", id, name, input: {...}}]
    
    Note over GW: Translate response back to OpenAI format
    GW->>GW: Transform tool_use blocks →<br/>tool_calls: [{id, type: "function", function: {name, arguments}}]
    
    GW-->>Agent: tool_calls: [{id, type: "function", function: {name, arguments: "..."}}]
```

```mermaid
flowchart TD
    subgraph "Input: Agent sends OpenAI format"
        IN[tools array:<br/>type: function<br/>function.name<br/>function.description<br/>function.parameters]
    end

    subgraph "Translation Strategies"
        IN --> PROVIDER{Target provider?}
        
        PROVIDER -->|OpenAI / vLLM / Azure| PASS[Pass through unchanged<br/>Already OpenAI format]
        
        PROVIDER -->|Anthropic| ANTH_TX[Transform:<br/>function.parameters → input_schema<br/>Remove function wrapper]
        
        PROVIDER -->|Bedrock| BDK_TX[Transform:<br/>tools → toolConfig.tools<br/>Each: toolSpec.inputSchema]
        
        PROVIDER -->|Vertex AI| VTX_TX[Transform:<br/>tools → functionDeclarations<br/>parameters → OpenAPI schema]
        
        PROVIDER -->|Ollama/vLLM no-tool| REACT[Inject into system prompt:<br/>ReAct format with tool descriptions<br/>Parse action/input from response]
    end

    subgraph "Response Normalization"
        PASS --> OUT[Normalized: tool_calls in OpenAI format]
        ANTH_TX --> ANTH_RESP[Parse tool_use content blocks<br/>→ tool_calls array]
        BDK_TX --> BDK_RESP[Parse toolUse from output<br/>→ tool_calls array]
        VTX_TX --> VTX_RESP[Parse functionCall from parts<br/>→ tool_calls array]
        REACT --> REACT_RESP[Parse Action: / Action Input:<br/>from text → tool_calls array]
        
        ANTH_RESP --> OUT
        BDK_RESP --> OUT
        VTX_RESP --> OUT
        REACT_RESP --> OUT
    end
```

---

## Canary Traffic Splitting

```mermaid
sequenceDiagram
    participant A1 as Agent Request #1
    participant A2 as Agent Request #2
    participant A3 as Agent Request #3
    participant GW as Gateway<br/>Canary Splitter
    participant CTRL as Control Model<br/>(Sonnet 4.5)
    participant CAN as Canary Model<br/>(Sonnet 4.6)
    participant LOG as Logger
    participant OBS as Observer

    Note over GW: Canary config: task=evaluate_control<br/>canary=sonnet-4.6, traffic_pct=20

    A1->>GW: evaluate_control
    Note over GW: Random [0,100) = 45 → control
    GW->>CTRL: Request
    CTRL-->>GW: Response
    GW->>LOG: variant=control, metrics={...}
    GW-->>A1: Response

    A2->>GW: evaluate_control
    Note over GW: Random [0,100) = 12 → canary
    GW->>CAN: Request
    CAN-->>GW: Response
    GW->>LOG: variant=canary, metrics={...}
    GW-->>A2: Response

    A3->>GW: evaluate_control
    Note over GW: Random [0,100) = 78 → control
    GW->>CTRL: Request
    CTRL-->>GW: Response
    GW->>LOG: variant=control, metrics={...}
    GW-->>A3: Response

    Note over OBS: After 30+ samples per variant
    OBS->>GW: GET /admin/canary/evaluate_control/metrics
    GW-->>OBS: {control: {avg_conf: 0.82, p95_lat: 4200}, canary: {avg_conf: 0.89, p95_lat: 3800}}
    
    Note over OBS: Canary wins on confidence and latency
    OBS->>GW: POST /admin/canary/evaluate_control/promote
    Note over GW: Canary promoted to 100%<br/>sonnet-4.6 is now primary
```

```mermaid
stateDiagram-v2
    [*] --> NoCanary: Normal operation
    
    NoCanary --> CanaryActive: POST /admin/canary/{task}/set<br/>traffic_pct, model, min_samples
    
    CanaryActive --> Collecting: Traffic split active
    Collecting --> Collecting: Requests routed by percentage
    
    Collecting --> Evaluating: min_samples reached + min_duration elapsed
    
    Evaluating --> Promoted: Observer: POST .../promote<br/>Canary wins
    Evaluating --> RolledBack: Observer: POST .../rollback<br/>Canary loses
    
    Promoted --> NoCanary: Canary becomes primary<br/>Old model becomes fallback or removed
    RolledBack --> NoCanary: Canary removed<br/>All traffic to control
    
    note right of Collecting
        Metrics tracked separately:
        - confidence (avg, p50, p95)
        - latency (avg, p95)  
        - error rate
        - escalation rate
        - cost per call
    end note
```

---

## Admin API and Observer Interaction

```mermaid
sequenceDiagram
    participant OBS as Observer
    participant ADMIN as Admin API<br/>(port 4001)
    participant CFG as Config Manager
    participant ROUTER as Route Resolver
    participant METRICS as Metrics Store

    Note over OBS: Hourly analysis cycle

    OBS->>ADMIN: GET /admin/metrics?window=1h
    ADMIN->>METRICS: Aggregate last hour
    METRICS-->>ADMIN: {by_task, by_model, by_tier}
    ADMIN-->>OBS: Metrics summary

    Note over OBS: Detects: evaluate_control has 55% escalation rate

    OBS->>OBS: Diagnosis via strong model:<br/>"Mid tier struggling with this task"

    OBS->>ADMIN: POST /admin/routing<br/>{task_routing: {evaluate_control: "strong"}}
    ADMIN->>CFG: Update routing config
    CFG->>CFG: Validate new config
    CFG->>ROUTER: Hot-swap routing table
    ROUTER-->>CFG: ACK
    CFG-->>ADMIN: {status: "applied", previous: "mid"}
    ADMIN-->>OBS: Success

    Note over OBS: 1 hour later: validate
    OBS->>ADMIN: GET /admin/metrics/evaluate_control?window=1h
    ADMIN-->>OBS: {escalation_rate: 0.08, avg_confidence: 0.91}
    Note over OBS: Escalation dropped from 55% to 8%<br/>Change validated successfully

    Note over OBS: Decides to test new model via canary
    OBS->>ADMIN: POST /admin/canary/evaluate_control/set<br/>{model: "new-model-v2", traffic_pct: 20, min_samples: 30}
    ADMIN->>CFG: Add canary config
    ADMIN-->>OBS: {status: "canary_active"}
```

```mermaid
graph TD
    subgraph "Admin API Endpoints (port 4001)"
        subgraph "Metrics"
            M1[GET /admin/metrics?window=1h]
            M2[GET /admin/metrics/{task}]
        end
        
        subgraph "Routing"
            R1[POST /admin/routing<br/>update task→tier]
            R2[POST /admin/threshold<br/>update confidence threshold]
            R3[POST /admin/reload<br/>hot-reload config from file]
        end
        
        subgraph "Canary"
            C1[GET /admin/canary/{task}/metrics]
            C2[POST /admin/canary/{task}/set]
            C3[POST /admin/canary/{task}/promote]
            C4[POST /admin/canary/{task}/rollback]
        end
        
        subgraph "Models"
            MD1[GET /admin/models<br/>list + health status]
            MD2[POST /admin/models/{id}/disable]
        end
    end

    subgraph "Callers"
        OBS[Observer<br/>automated adjustments]
        OPS[Ops Team<br/>manual overrides]
    end

    OBS --> M1 & M2
    OBS --> R1 & R2
    OBS --> C1 & C2 & C3 & C4
    OPS --> R1 & R3
    OPS --> MD1 & MD2
    OPS --> C2 & C3 & C4
```

---

## Module Structure

```mermaid
graph TD
    subgraph "llm-gateway/src/"
        MAIN[main.py<br/>FastAPI app, agent routes port 4000]
        ADMIN_APP[admin.py<br/>Admin API routes port 4001]
        
        subgraph "Core"
            RESOLVER[resolver.py<br/>3-level routing hierarchy]
            ESCALATION[escalation.py<br/>confidence check, tier promotion]
            FALLBACK[fallback.py<br/>model failover within tier]
            CANARY_MOD[canary.py<br/>traffic splitting, metrics tracking]
            CONFIDENCE[confidence.py<br/>extraction + heuristics]
        end

        subgraph "Providers"
            BASE[base_adapter.py<br/>ProviderAdapter interface]
            OLLAMA_P[ollama.py]
            VLLM_P[vllm.py]
            ANTHROPIC_P[anthropic.py]
            OPENAI_P[openai.py]
            BEDROCK_P[bedrock.py]
            AZURE_P[azure.py]
            VERTEX_P[vertex.py]
            GENERIC_P[generic_openai.py<br/>any OpenAI-compatible]
        end

        subgraph "Translation"
            TOOL_FMT[tool_translator.py<br/>OpenAI ↔ all formats]
            MSG_FMT[message_translator.py<br/>normalize message formats]
            REACT_MOD[react_prompt.py<br/>ReAct for non-tool models]
        end

        subgraph "Infrastructure"
            CONFIG_MGR[config.py<br/>YAML loading, hot-reload, validation]
            HEALTH_MOD[health.py<br/>periodic checks, model status]
            RATE_MOD[rate_limiter.py<br/>per-tenant, per-model]
            COST_MOD[cost.py<br/>token pricing, budget enforcement]
            LOG_MOD[logger.py<br/>structured JSON logging]
            METRICS_MOD[metrics.py<br/>in-memory aggregation for admin API]
        end
    end

    subgraph "llm-gateway/config/"
        ROUTING_YAML[routing.yaml<br/>tiers, models, routing rules]
    end

    subgraph "common/ (shared library)"
        MODELS[models.py<br/>shared request/response types]
        CLIENT[llm_client.py<br/>thin wrapper agents use]
    end

    MAIN --> RESOLVER
    MAIN --> ESCALATION
    MAIN --> TOOL_FMT
    MAIN --> LOG_MOD
    RESOLVER --> CONFIG_MGR
    RESOLVER --> CANARY_MOD
    ESCALATION --> FALLBACK
    FALLBACK --> BASE
    BASE --> OLLAMA_P & VLLM_P & ANTHROPIC_P & OPENAI_P & BEDROCK_P & AZURE_P & VERTEX_P & GENERIC_P
    ADMIN_APP --> CONFIG_MGR
    ADMIN_APP --> METRICS_MOD
    ADMIN_APP --> CANARY_MOD
    ADMIN_APP --> HEALTH_MOD
    CONFIG_MGR --> ROUTING_YAML
```

---

## Model Lifecycle

```mermaid
stateDiagram-v2
    [*] --> Added: Ops adds model to config<br/>(in a tier, at lowest priority)

    Added --> HealthCheck: Gateway detects new model
    HealthCheck --> Healthy: Health check passes
    HealthCheck --> Unhealthy: Health check fails

    Unhealthy --> HealthCheck: Retry on schedule
    Unhealthy --> Removed: Persistent failure → ops removes

    Healthy --> Canary: Observer starts canary test<br/>20% traffic

    Canary --> Collecting: Metrics accumulating
    Collecting --> Evaluating: min_samples + min_duration met

    Evaluating --> Promoted: Canary wins<br/>→ becomes primary in tier
    Evaluating --> Demoted: Canary loses<br/>→ removed from canary

    Promoted --> Active: Primary model for tier
    Demoted --> Healthy: Remains as fallback<br/>or removed

    Active --> Deprecated: Ops marks deprecated<br/>(new model added above it)
    
    Deprecated --> Fallback: Moved to fallback position<br/>Still serves if primary fails
    
    Fallback --> Removed: Grace period elapsed<br/>No traffic for N days
    
    Removed --> [*]: Model config deleted

    Active --> Unhealthy: Health check fails
    Unhealthy --> Active: Health check recovers

    note right of Active
        Active = first healthy model in tier
        Serves all non-canary traffic
    end note

    note right of Deprecated
        Model still works, but new model
        is preferred. Kept for safety.
    end note
```

---

## Health Check and Model Rotation

```mermaid
sequenceDiagram
    participant TIMER as Health Check Timer<br/>(every 30s)
    participant HC as Health Checker
    participant M1 as Model: ollama-8b
    participant M2 as Model: vllm-70b
    participant M3 as Model: sonnet-cloud
    participant POOL as Model Pool
    participant LOG as Logger

    TIMER->>HC: Trigger health check cycle
    
    par Check all models
        HC->>M1: GET /health (or minimal completion)
        HC->>M2: GET /v1/models
        HC->>M3: POST /messages (tiny prompt)
    end
    
    M1-->>HC: 200 OK (healthy)
    M2-->>HC: timeout (unhealthy)
    M3-->>HC: 200 OK (healthy)
    
    HC->>POOL: Mark vllm-70b unhealthy
    HC->>LOG: {model: vllm-70b, status: unhealthy, reason: timeout}
    
    Note over POOL: Mid tier models:<br/>1. vllm-70b [UNHEALTHY - skipped]<br/>2. sonnet-cloud [HEALTHY - now primary]
    
    Note over HC: Next cycle (30s later)
    TIMER->>HC: Trigger health check
    HC->>M2: GET /v1/models
    M2-->>HC: 200 OK (recovered)
    HC->>POOL: Mark vllm-70b healthy
    HC->>LOG: {model: vllm-70b, status: healthy, recovered: true}
    
    Note over POOL: Mid tier models:<br/>1. vllm-70b [HEALTHY - primary again]<br/>2. sonnet-cloud [HEALTHY - fallback]
```

---

## Hot-Reload Mechanism

```mermaid
sequenceDiagram
    participant FS as Filesystem<br/>config/routing.yaml
    participant WATCH as File Watcher<br/>(inotify/poll)
    participant CFG as Config Manager
    participant VAL as Config Validator
    participant ROUTER as Route Resolver
    participant POOL as Model Pool
    participant LOG as Logger

    Note over FS: Ops edits routing.yaml<br/>(or volume mount updates)
    FS->>WATCH: File modified event
    WATCH->>CFG: reload_config()
    
    CFG->>CFG: Read new YAML
    CFG->>VAL: validate(new_config)
    
    alt Valid config
        VAL-->>CFG: OK
        CFG->>CFG: Diff old vs new config
        CFG->>ROUTER: Swap routing tables (atomic)
        CFG->>POOL: Add/remove models as needed
        CFG->>LOG: {event: config_reloaded, changes: [...]}
        Note over ROUTER: Next request uses new config<br/>In-flight requests use old config (no interruption)
    else Invalid config
        VAL-->>CFG: Error: {field: "tiers.mid", msg: "no models defined"}
        CFG->>LOG: {event: config_reload_failed, error: "..."}
        Note over ROUTER: Continue using previous valid config<br/>Never apply broken config
    end
```

### How Hot-Reload Works (Implementation Detail)

1. **File watching**: On Linux, use `inotify` via `watchdog` library. On macOS/fallback, poll every 5 seconds.
2. **Atomic swap**: The routing table is an immutable snapshot. New config creates a new snapshot, then a single pointer swap makes it active. No locks on the read path.
3. **In-flight safety**: Requests that already resolved a model continue with that model. Only new requests see the new config.
4. **Validation before apply**: Schema validation (required fields, valid tier names, model IDs exist) prevents broken configs from being applied.
5. **Admin API trigger**: `POST /admin/reload` forces an immediate reload (same validation path). Used by observer for programmatic changes.
6. **Config sources**: File-based changes (ops editing YAML) and API-based changes (observer posting to admin API) both funnel through the same validation + swap pipeline.

---

## Cost Calculation and Rate Limiting

```mermaid
flowchart TD
    subgraph "Pre-Request Checks"
        REQ[Incoming Request] --> RATE{Rate limit check}
        RATE -->|Under limit| COST_EST{Cost estimate<br/>within budget?}
        RATE -->|Over limit| REJECT_429[429 Too Many Requests<br/>Retry-After header]
        
        COST_EST -->|Within budget| PROCEED[Proceed to model]
        COST_EST -->|Exceeds per-request max| REJECT_COST[400 Cost ceiling exceeded]
        COST_EST -->|Exceeds daily tenant budget| REJECT_BUDGET[429 Daily budget exhausted]
    end

    subgraph "Rate Limit Layers"
        RL1[Per-Tenant<br/>requests/min + tokens/min]
        RL2[Per-Model<br/>RPM respecting provider limits]
        RL3[Global<br/>total gateway throughput]
    end

    subgraph "Cost Tracking"
        RESPONSE[Response received] --> TOKEN_COUNT[Count actual tokens<br/>input + output]
        TOKEN_COUNT --> PRICE[Apply model pricing<br/>per 1K input / per 1K output]
        PRICE --> RECORD[Record cost:<br/>- per request log entry<br/>- tenant daily accumulator<br/>- model usage tracker]
    end

    RATE --> RL1 & RL2 & RL3
```

### Cost Calculation Details

| Provider | Pricing Source | Method |
|----------|---------------|--------|
| Ollama / vLLM (local) | Config-defined (amortized GPU cost) | tokens * configured_rate |
| Anthropic | Model-specific pricing | input_tokens * input_rate + output_tokens * output_rate |
| OpenAI | Model-specific pricing | Same formula |
| Bedrock | On-demand pricing per region | Same formula |
| Azure / Vertex | Deployment-specific | Configurable per model |

### Rate Limiting Implementation

- **Algorithm**: Token bucket with sliding window (per-tenant, per-model).
- **Storage**: In-memory (single instance) or Redis (multi-instance deployment).
- **Fairness**: Per-tenant limits prevent one tenant from starving others.
- **Provider respect**: Per-model limits stay below provider API rate limits to avoid 429s from upstream.
- **429 Response**: Includes `Retry-After` header with seconds until tokens refill.

---

## Why This Is NOT LiteLLM

LiteLLM is a popular open-source library for proxying LLM calls across providers. The gateway shares some surface-level goals but differs fundamentally in several areas:

### What LiteLLM does well (and we could use under the hood)

| Capability | LiteLLM | Our Gateway |
|-----------|---------|-------------|
| Provider API translation | Yes | Could delegate to LiteLLM internally |
| Basic load balancing | Yes (router) | Yes, but with richer logic |
| Cost tracking per call | Yes | Yes |
| Retry on failure | Yes | Yes |

### What requires custom implementation (not in LiteLLM)

| Capability | Why custom |
|-----------|-----------|
| 3-level routing hierarchy (tenant > agent > task) | LiteLLM has no concept of tenants, agents, or task-based routing |
| Confidence-based escalation | LiteLLM retries on failure, not on low confidence; it doesn't inspect response content |
| Tool format translation with ReAct fallback | LiteLLM passes tools through; it doesn't inject ReAct prompts for non-tool models |
| Canary traffic splitting with per-variant metrics | LiteLLM has no A/B testing or canary concept |
| Observer integration (admin API for automated tuning) | LiteLLM is a library, not a controllable service with an admin plane |
| Hot-reload config hierarchy | LiteLLM uses static config or code-level routing |
| Per-tenant daily budget enforcement | LiteLLM tracks cost but doesn't enforce tenant-level budgets |
| Structured logging for observer consumption | LiteLLM logs are operational, not designed for automated analysis |

### Decision: Build custom gateway, optionally use LiteLLM as a provider adapter

The gateway is architecturally distinct from LiteLLM. However, for the provider adapter layer specifically, we could optionally use LiteLLM's `completion()` function as the transport layer inside individual adapters — treating it as a convenience library for API format translation rather than as the routing brain.

**Why not just wrap LiteLLM entirely?**
- Our routing logic (3-level hierarchy, canary, escalation) must wrap around the model call, not be wrapped by it.
- We need to inspect responses between tiers (for confidence extraction) which LiteLLM's router doesn't support.
- The admin API + hot-reload + observer loop is a fundamentally different operational model than LiteLLM's "call and forget" pattern.

---

## Key Design Decisions

### 1. Agents declare tasks, never models

Agents send `task="evaluate_control"` — never `model="claude-sonnet-4-20250514"`. This complete decoupling means:
- Models can be swapped without touching agent code
- The observer can rebalance the entire system by editing one config file
- New models can be tested via canary without any agent awareness
- Tenant-specific model preferences are gateway concerns, not agent concerns

**Why:** If agents chose models, every model change would be a multi-repo code change with coordinated deploys. With task-based routing, model changes are config changes.

### 2. Three-tier system, not N arbitrary tiers

Fast/mid/strong is sufficient granularity. More tiers would complicate escalation paths and make it harder for the observer to reason about routing changes. The tiers map to real cost/capability tradeoffs:
- **Fast**: Sub-second, cheap, good for classification/extraction (8B local)
- **Mid**: Few seconds, moderate cost, good for generation/evaluation (70B local or Sonnet)
- **Strong**: Slower, expensive, for complex reasoning or when others fail (Opus)

**Why:** Simplicity. The observer can reason about "promote to strong" without navigating a complex tier graph.

### 3. Fallback within tier BEFORE escalation across tiers

When a model fails (timeout, 5xx, rate limit), try the next model in the same tier first. Only escalate to a higher tier when the response itself is inadequate (low confidence, parse failure). This keeps costs predictable.

**Why:** A timeout from vLLM doesn't mean the task needs a stronger model — it means vLLM is overloaded. Try Sonnet (same tier, cloud) before jumping to Opus.

### 4. Confidence extraction is best-effort, not required

Not all models return confidence scores. The heuristic system (empty = 0.0, parse fail = 0.3, normal = 0.8) means escalation works even without explicit confidence. Agents that want precise escalation control can include a `confidence` field in their structured output schema.

**Why:** We cannot require all models to return confidence. The heuristic makes the system work universally, while structured output schemas provide precision when needed.

### 5. Two ports: one for agents, one for admin

Port 4000 (agent-facing) is the hot path — it needs to be fast and never blocked by admin operations. Port 4001 (admin) is for the observer and ops — it can afford more processing and doesn't need the same latency guarantees. In production, port 4001 is not exposed externally.

**Why:** Security (admin API not reachable from outside), performance (no request interference), clarity (different auth requirements possible in future).

### 6. Logging is synchronous write, not fire-and-forget

Every request/response is logged before the response is returned to the agent. This guarantees the observer has complete data. The log write is to a local volume (fast), not a remote service.

**Why:** The observer's ability to diagnose issues depends on complete logs. Async/lossy logging would create blind spots. Local file writes are fast enough (sub-ms) to not meaningfully impact latency.

### 7. Config is YAML on a volume, not in a database

The routing config is a YAML file mounted into the container. This means:
- GitOps: config changes are reviewable PRs
- Simplicity: no database dependency for the gateway
- Portability: works in air-gapped deployments with no external services
- Hot-reload: file watcher detects changes without restart

The admin API can also modify the in-memory config, but changes that need to persist across restarts must be written to the YAML file (or the orchestrator must handle persistence).

**Why:** The gateway should have minimal dependencies. A database would add a failure mode for something that can be a flat file.

### 8. Provider adapters are stateless and independently testable

Each adapter is a pure function: normalized request in, normalized response out. No shared state between adapters. Each can be unit tested with mock HTTP responses.

**Why:** Provider APIs change frequently. Isolated adapters mean a Bedrock API change doesn't risk breaking the Anthropic path. Testing is straightforward.

### 9. Tool translation supports ReAct as a fallback

For models without native function calling (older Ollama models, some open-source models), the gateway injects tool descriptions into the system prompt using ReAct format and parses `Action:` / `Action Input:` from the response. This means every agent works with every model, even ones without tool support.

**Why:** The system must work with local models that may not support function calling natively. ReAct prompting is well-understood and reliable for simple tool use. This prevents "this agent only works with OpenAI" lock-in.

### 10. Canary state is in-memory with periodic checkpoint

Active canary experiments (traffic percentages, accumulated metrics) live in memory for fast access on every request. Metrics are checkpointed to disk periodically. If the gateway restarts, active canaries resume from the last checkpoint (may lose a few minutes of metrics, but the experiment continues).

**Why:** Canary decisions happen on every request (fast path). Disk I/O on every request is unacceptable. Losing a few data points on restart is fine — the experiment requires 30+ samples anyway.

---

## Request Lifecycle (Complete)

```mermaid
sequenceDiagram
    participant A as Agent
    participant API as API Handler
    participant RL as Rate Limiter
    participant RES as Route Resolver
    participant CAN as Canary Splitter
    participant TX as Tool Translator
    participant ADAPT as Provider Adapter
    participant CONF as Confidence Extractor
    participant ESC as Escalation Engine
    participant COST as Cost Calculator
    participant LOG as Logger

    A->>API: POST /v1/complete {messages, task, agent, tenant_id, tools, ...}
    
    API->>RL: check(tenant_id, estimated_tokens)
    RL-->>API: OK (or 429)
    
    API->>RES: resolve(agent, task, tenant_id)
    RES-->>API: {tier: mid, model: vllm-70b, provider: vllm}
    
    API->>CAN: check_canary(agent, task)
    CAN-->>API: {use_canary: false, variant: "control"}
    
    API->>TX: translate_tools(tools, provider=vllm)
    TX-->>API: translated_tools
    
    API->>ADAPT: complete(messages, translated_tools, model_config)
    ADAPT-->>API: raw_response
    
    API->>TX: normalize_response(raw_response, provider=vllm)
    TX-->>API: normalized_response (OpenAI format tool_calls)
    
    API->>CONF: extract_confidence(normalized_response, task)
    CONF-->>API: confidence=0.85
    
    API->>ESC: check(confidence=0.85, threshold=0.8)
    ESC-->>API: no_escalation_needed
    
    API->>COST: calculate(model, input_tokens, output_tokens)
    COST-->>API: cost_usd=0.0012
    
    API->>LOG: log_request({all fields})
    
    API-->>A: {content, model_used, tier_used, escalated, usage, confidence, tool_calls, cost}
```

---

## Deployment Topology

```mermaid
graph LR
    subgraph "Docker Compose / K8s"
        subgraph "LLM Gateway"
            GW[llm-gateway<br/>Ports: 4000, 4001<br/>No GPU]
            VOL_CFG[/config/routing.yaml<br/>mounted volume/]
            VOL_LOG[/logs/<br/>mounted volume/]
        end

        subgraph "Local Models"
            OLL[Ollama<br/>Port 11434<br/>GPU: 1x for 8B]
            VLLM[vLLM<br/>Port 8000<br/>GPU: 2-4x for 70B]
        end

        subgraph "Other Services"
            OBS[Observer<br/>reads /logs/ volume]
            AGENTS[Agent containers<br/>call port 4000]
        end
    end

    subgraph "Cloud APIs (external)"
        ANT[api.anthropic.com]
        OAI[api.openai.com]
        BDK[bedrock.us-east-1.amazonaws.com]
        AZR[your-resource.openai.azure.com]
        VTX[us-central1-aiplatform.googleapis.com]
    end

    GW --> VOL_CFG
    GW --> VOL_LOG
    GW --> OLL
    GW --> VLLM
    GW --> ANT & OAI & BDK & AZR & VTX
    OBS --> VOL_LOG
    AGENTS --> GW
```

---

## Error Handling Strategy

| Error Type | Handling | Visible to Agent? |
|-----------|----------|-------------------|
| Model timeout | Fallback to next model in tier | No (transparent retry) |
| Model 5xx | Fallback to next model in tier | No |
| Model rate limited (429) | Fallback to next model; if all limited, return 429 to agent | Only if all models exhausted |
| Invalid tool call format | Log warning, attempt best-effort parse | No (degraded tool_calls) |
| All models in tier fail | Escalate to next tier (if enabled) | No (escalation is transparent) |
| All tiers exhausted | Return error to agent with last error detail | Yes |
| Config invalid on reload | Keep previous config, log error | No |
| Tenant over daily budget | Return 429 with budget_exhausted reason | Yes |
| Tenant rate limited | Return 429 with retry_after | Yes |
| Unparseable response (expected JSON) | Confidence = 0.3, may trigger escalation | No (escalation handles it) |
| Provider auth failure (bad API key) | Mark model unhealthy, fallback | No (if fallback succeeds) |

---

## Configuration Reference

```yaml
# config/routing.yaml — the single source of truth for routing

tiers:
  fast:
    models:
      - id: ollama-8b          # unique identifier
        provider: ollama       # adapter to use
        model: llama3.1:8b     # provider-specific model name
        endpoint: http://ollama:11434
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

# 3-level routing hierarchy
task_routing:        # Level 3 (default)
  classify_intent: fast
  evaluate_control: mid
  complex_reasoning: strong
  # ... (see REQUIREMENTS.md for full list)

agent_routing:       # Level 2 (per-agent override)
  agent-eval:
    evaluate_control: mid
    generate_code:
      model: sonnet-cloud

tenant_routing:      # Level 1 (most specific, wins)
  acme_corp:
    evaluate_control:
      model: opus-cloud

# Canary experiments (managed by observer or ops)
canary:
  agent-eval/evaluate_control:
    model: sonnet-4.6
    traffic_pct: 20
    min_samples: 30
    min_duration_hours: 4

# Escalation
escalation:
  enabled: true
  max_escalations: 2
  path: [fast, mid, strong]

# Embedding
embedding:
  model:
    provider: ollama
    model: nomic-embed-text
    endpoint: http://ollama:11434

# Limits
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

# Health checks
health:
  interval_seconds: 30
  timeout_ms: 5000
  unhealthy_threshold: 3    # consecutive failures before marking unhealthy
  healthy_threshold: 1      # consecutive successes to recover

# Policy
policy:
  allow_cloud_fallback: true
  log_prompts: true
  log_responses: true
```

---

## Summary

The LLM Gateway is a stateless routing service that sits between all agents and all model providers. Its core value propositions:

1. **Decoupling**: Agents never know which model they are using. Models can be swapped freely.
2. **Intelligence**: Routing hierarchy + escalation + canary = the system gets smarter over time via the observer.
3. **Reliability**: Fallback chains ensure requests succeed even when individual models fail.
4. **Universality**: Tool format translation means any agent works with any model, regardless of native capabilities.
5. **Observability**: Complete structured logs enable the observer to diagnose and fix issues autonomously.
6. **Simplicity**: One YAML file controls all routing. No code changes for model operations.
