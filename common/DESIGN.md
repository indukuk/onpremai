# Common Libraries - Design Document

## Overview

The `common/` directory contains shared client libraries used by ALL agents in the system. These libraries form the abstraction layer that makes agents portable across environments (on-prem, cloud, hybrid). No agent talks to infrastructure directly — every external interaction goes through a common client.

**Core principle:** Agents are environment-agnostic. Only `common/` knows about infrastructure.

---

## How Agents Use Common Libraries

```mermaid
graph TD
    subgraph "Agents"
        EVAL[Evaluation Agent]
        CHAT[Chat Agent]
        PREPROC[Preprocessor]
        ORCHESTRATOR[Orchestrator]
    end

    subgraph "Common Libraries"
        LLM[LLMClient]
        MEM[MemoryClient]
        STORE[StorageClient]
        STATE[StateClient]
        SANDBOX[SandboxClient]
        LOG[AgentLogger]
    end

    subgraph "Infrastructure"
        GW[LLM Gateway]
        MEMSVC[Memory Service]
        MINIO[(MinIO / S3)]
        PG[(PostgreSQL / DynamoDB)]
        SBSVC[Sandbox Service]
        STDOUT[stdout / container logs]
    end

    EVAL --> LLM
    EVAL --> MEM
    EVAL --> STORE
    EVAL --> STATE
    EVAL --> SANDBOX
    EVAL --> LOG

    CHAT --> LLM
    CHAT --> MEM
    CHAT --> STORE
    CHAT --> LOG

    PREPROC --> STORE
    PREPROC --> MEM
    PREPROC --> LLM
    PREPROC --> LOG

    ORCHESTRATOR --> STATE
    ORCHESTRATOR --> MEM
    ORCHESTRATOR --> LOG

    LLM --> GW
    MEM --> MEMSVC
    STORE --> MINIO
    STATE --> PG
    SANDBOX --> SBSVC
    LOG --> STDOUT
```

---

## LLMClient Flow

```mermaid
sequenceDiagram
    participant Agent
    participant LLMClient
    participant Gateway as LLM Gateway
    participant Provider as LLM Provider<br/>(OpenAI/Anthropic/Local)

    Agent->>LLMClient: complete(messages, task="evaluate_control")
    LLMClient->>LLMClient: Validate inputs, set defaults
    LLMClient->>Gateway: POST /v1/complete<br/>{messages, task, tenant_id, trace_id}

    Note over Gateway: Route by task → tier mapping<br/>Retry on transient errors<br/>Escalate if confidence < threshold

    Gateway->>Provider: Forward to selected model
    Provider-->>Gateway: Response + usage metrics
    Gateway-->>LLMClient: {content, model_used, tier_used, tokens, latency}
    LLMClient-->>Agent: LLMResponse(content, model_used, tier_used, ...)

    Note over Agent: Agent never knows which model<br/>Agent never retries<br/>Agent only specifies task name

    alt Gateway unreachable
        LLMClient-->>Agent: raise LLMUnavailableError
        Note over Agent: Agent decides: fail gracefully<br/>or degrade functionality
    end
```

**Key behaviors:**
- Agent specifies `task` (e.g., "evaluate_control", "extract_schema"), never a model name
- Gateway maps tasks to tiers (fast/mid/strong) and tiers to models
- Retries, fallbacks, and escalation are handled entirely by the gateway
- Client raises `LLMUnavailableError` on connection failure — agent decides how to handle

---

## MemoryClient Flow

```mermaid
sequenceDiagram
    participant Agent
    participant MemoryClient
    participant MemSvc as Memory Service
    participant PG as PostgreSQL
    participant Redis as Redis Cache

    Agent->>MemoryClient: tenant_recall(tenant_id, query, top_k=5)
    MemoryClient->>MemSvc: GET /api/tenant/{id}/recall?q=...&top_k=5

    MemSvc->>Redis: Check cache for query
    alt Cache hit
        Redis-->>MemSvc: Cached results
    else Cache miss
        MemSvc->>PG: Vector similarity search<br/>(pgvector)
        PG-->>MemSvc: Matching facts
        MemSvc->>Redis: Cache results (TTL 60s)
    end

    MemSvc-->>MemoryClient: [{fact, category, confidence, created_at}, ...]
    MemoryClient-->>Agent: list[dict]

    alt Memory Service Down
        MemoryClient-->>Agent: return [] (empty list)
        Note over Agent: Agent continues with<br/>reduced context — no crash
    end
```

**Key behaviors:**
- All memory operations have a 5-second timeout
- On failure: return empty results (recall) or silently drop writes (remember)
- Connection pooling handled internally
- Agent never touches PostgreSQL or Redis directly

---

## StorageClient Abstraction

```mermaid
flowchart TD
    AGENT[Agent Code] --> SC[StorageClient]

    SC --> DETECT{Endpoint<br/>Detection}

    DETECT -->|"http://..." endpoint<br/>non-AWS URL| MINIO_PATH[MinIO Backend]
    DETECT -->|"https://s3..." or<br/>no endpoint set| S3_PATH[S3/boto3 Backend]

    MINIO_PATH --> MINIO_CLIENT[minio Python client<br/>+ access key/secret key]
    S3_PATH --> BOTO3[boto3 S3 client<br/>+ IAM role / env creds]

    MINIO_CLIENT --> OPS[Unified Operations:<br/>get, put, list, exists,<br/>delete, presigned URLs]
    BOTO3 --> OPS

    subgraph "Auto-Detection Logic"
        direction LR
        CHECK1["endpoint starts with http://<br/>AND not *.amazonaws.com"]
        CHECK1 -->|True| USE_MINIO[Use MinIO client]
        CHECK1 -->|False| USE_S3[Use boto3 client]
    end
```

**Key behaviors:**
- Agent calls `StorageClient()` — backend is auto-detected from `STORAGE_ENDPOINT`
- Same API whether talking to MinIO on localhost or S3 in production
- Retries: 3 attempts with exponential backoff on transient errors
- Presigned URLs work for both backends (useful for direct browser uploads)

---

## Error Handling Patterns

```mermaid
flowchart TD
    subgraph "Retry Pattern"
        R1[Call external service] --> R2{Success?}
        R2 -->|Yes| R3[Return result]
        R2 -->|No, transient| R4{Retries<br/>remaining?}
        R4 -->|Yes| R5[Exponential backoff<br/>100ms, 200ms, 400ms]
        R5 --> R1
        R4 -->|No| R6[Raise/degrade]
    end

    subgraph "Timeout Pattern"
        T1[Start request] --> T2[Wait up to timeout]
        T2 -->|Response received| T3[Return result]
        T2 -->|Timeout exceeded| T4[Raise TimeoutError<br/>or return default]
    end

    subgraph "Graceful Degradation"
        G1[Service call fails] --> G2{Which service?}
        G2 -->|Memory| G3[Return empty list/None<br/>Agent has less context]
        G2 -->|LLM| G4[Raise LLMUnavailableError<br/>Agent decides fallback]
        G2 -->|Storage| G5[Raise StorageError<br/>Cannot continue without data]
        G2 -->|Sandbox| G6[Return ExecutionResult<br/>success=False]
        G2 -->|State| G7[Log warning<br/>Retry on next cycle]
    end
```

**Degradation hierarchy (least to most critical):**

| Service | On Failure | Impact |
|---------|-----------|--------|
| Memory Service | Return empty results | Agent works with less context |
| LLM Gateway | Raise `LLMUnavailableError` | Agent may skip LLM-dependent steps |
| Sandbox Service | Return `success=False` | Agent cannot execute generated code |
| State Backend | Log + retry next cycle | Job status temporarily stale |
| Storage | Raise `StorageError` | Cannot proceed — data inaccessible |

---

## Module Structure

```mermaid
graph TD
    subgraph "common/"
        INIT[__init__.py<br/>Public exports]
        LLM[llm_client.py<br/>LLMClient, LLMResponse,<br/>LLMUnavailableError]
        MEM[memory_client.py<br/>MemoryClient]
        STORE[storage_client.py<br/>StorageClient, StorageError]
        STATE[state_client.py<br/>StateClient]
        SANDBOX[sandbox_client.py<br/>SandboxClient, ExecutionResult]
        LOG[logger.py<br/>AgentLogger]
        CONFIG[config.py<br/>Shared environment defaults]
        RETRY[retry.py<br/>Retry/backoff utilities]
        ERRORS[errors.py<br/>Common exception hierarchy]
    end

    INIT --> LLM
    INIT --> MEM
    INIT --> STORE
    INIT --> STATE
    INIT --> SANDBOX
    INIT --> LOG

    LLM --> RETRY
    LLM --> ERRORS
    LLM --> CONFIG
    MEM --> RETRY
    MEM --> ERRORS
    MEM --> CONFIG
    STORE --> RETRY
    STORE --> ERRORS
    STORE --> CONFIG
    STATE --> RETRY
    STATE --> ERRORS
    STATE --> CONFIG
    SANDBOX --> RETRY
    SANDBOX --> ERRORS
    SANDBOX --> CONFIG
    LOG --> CONFIG
```

---

## Detailed Source Layout

```
common/
├── __init__.py              # Re-exports: LLMClient, MemoryClient, StorageClient, etc.
├── config.py                # Shared env var reading with defaults
├── errors.py                # Exception hierarchy (LLMUnavailableError, StorageError, etc.)
├── retry.py                 # @retry decorator, exponential backoff utility
├── llm_client.py            # LLMClient, LLMResponse dataclass
├── memory_client.py         # MemoryClient with all memory operations
├── storage_client.py        # StorageClient with S3/MinIO auto-detection
├── state_client.py          # StateClient with PostgreSQL/DynamoDB backends
├── sandbox_client.py        # SandboxClient, ExecutionResult dataclass
├── logger.py                # AgentLogger with structured JSON output
├── tests/
│   ├── test_llm_client.py
│   ├── test_memory_client.py
│   ├── test_storage_client.py
│   ├── test_state_client.py
│   ├── test_sandbox_client.py
│   └── test_logger.py
├── REQUIREMENTS.md
└── DESIGN.md
```

---

## Key Design Decisions

### 1. Why Copy into Each Image (Not pip Package) — For Now

**Decision:** Use `COPY common/ /app/common/` in each service Dockerfile rather than publishing a pip package.

**Rationale:**
- **Simplicity:** No private PyPI server to maintain, no package versioning dance during rapid iteration
- **Atomic deploys:** Each image is self-contained — no risk of a broken package version breaking all services at once
- **Development speed:** Change common code, rebuild one image, test — no publish/install cycle
- **Consistency enforcement:** CI lint check verifies all services use the same `common/` commit hash
- **Transition plan:** When the system has >5 agents and the common API stabilizes, migrate to a versioned pip package with semantic versioning

**Trade-offs accepted:**
- Slight image size overhead (common/ is small: ~50KB of Python)
- Must rebuild all images when common/ changes (CI handles this)
- No independent versioning of common/ (acceptable during early development)

### 2. Graceful Degradation

**Decision:** Non-critical services failing should never crash an agent.

**Implementation pattern:**
```python
class MemoryClient:
    def tenant_recall(self, tenant_id: str, query: str, top_k: int = 5) -> list[dict]:
        try:
            response = self._http.get(
                f"/api/tenant/{tenant_id}/recall",
                params={"q": query, "top_k": top_k},
                timeout=self._timeout
            )
            return response.json()
        except (ConnectionError, Timeout, HTTPError) as e:
            self._logger.error("Memory service unavailable", error=e)
            return []  # Agent continues with empty context
```

**Degradation levels:**
1. **Memory down:** Agents work with no historical context (reduced quality, not failure)
2. **LLM down:** Agents that require LLM raise explicit error; preprocessor skips optional LLM steps
3. **Storage down:** Hard failure — no data means no work possible
4. **Sandbox down:** Code execution fails gracefully; agent reports inability

### 3. Configuration via Environment Variables with Defaults

**Decision:** All configuration reads from environment variables. Every variable has a sensible default that works with `docker compose up`.

**Rationale:**
- 12-factor app compliance — configuration is in the environment, not code
- Defaults enable zero-config local development
- Override per environment (dev/staging/prod) without code changes
- No config files to mount or manage

**Pattern:**
```python
class CommonConfig:
    LLM_GATEWAY_URL: str = os.getenv("LLM_GATEWAY_URL", "http://llm-gateway:4000")
    MEMORY_URL: str = os.getenv("MEMORY_URL", "http://memory-service:5000")
    STORAGE_ENDPOINT: str = os.getenv("STORAGE_ENDPOINT", "http://minio:9000")
    STORAGE_BUCKET: str = os.getenv("STORAGE_BUCKET", "compliance-artifacts")
    STATE_BACKEND: str = os.getenv("STATE_BACKEND", "postgres")
    STATE_DSN: str = os.getenv("STATE_DSN", "postgresql://compliance:pass@postgres:5432/compliance")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "info")
    LOG_FORMAT: str = os.getenv("LOG_FORMAT", "json")
```

### 4. Thread Safety Considerations

**Decision:** All clients are thread-safe and reusable across concurrent requests.

**Implementation:**
- **HTTP sessions:** Each client uses a `requests.Session` (or `httpx.Client`) with connection pooling. Sessions are created once at init and reused.
- **No mutable shared state:** Clients store only configuration (immutable after init). No request-specific state lives on the client instance.
- **Logger context:** `AgentLogger` uses thread-local storage for trace IDs when used in threaded contexts, or relies on structured fields passed per call.
- **StateClient with PostgreSQL:** Uses connection pooling (e.g., `psycopg2.pool.ThreadedConnectionPool`) to safely share across threads.
- **StorageClient:** boto3 clients are not thread-safe by default. The StorageClient creates one client per thread using `threading.local()`.

**Thread-safety guarantee:** Any client can be instantiated once at service startup and shared across all request-handling threads or async tasks without external synchronization.

---

## Exception Hierarchy

```python
class CommonError(Exception):
    """Base for all common library errors."""
    pass

class LLMUnavailableError(CommonError):
    """LLM gateway is unreachable or returned 5xx."""
    pass

class LLMTimeoutError(LLMUnavailableError):
    """LLM request exceeded timeout."""
    pass

class StorageError(CommonError):
    """Storage operation failed after retries."""
    pass

class StorageNotFoundError(StorageError):
    """Requested key does not exist."""
    pass

class SandboxError(CommonError):
    """Sandbox service is unreachable."""
    pass

class StateError(CommonError):
    """State backend operation failed."""
    pass
```

---

## Configuration Reference

| Variable | Default | Used By | Description |
|----------|---------|---------|-------------|
| `LLM_GATEWAY_URL` | `http://llm-gateway:4000` | LLMClient | Gateway endpoint |
| `MEMORY_URL` | `http://memory-service:5000` | MemoryClient | Memory service endpoint |
| `STORAGE_ENDPOINT` | `http://minio:9000` | StorageClient | S3-compatible endpoint |
| `STORAGE_BUCKET` | `compliance-artifacts` | StorageClient | Default bucket |
| `STORAGE_ACCESS_KEY` | `minioadmin` | StorageClient | Access key (MinIO mode) |
| `STORAGE_SECRET_KEY` | `minioadmin` | StorageClient | Secret key (MinIO mode) |
| `STATE_BACKEND` | `postgres` | StateClient | `postgres` or `dynamodb` |
| `STATE_DSN` | `postgresql://...` | StateClient | Connection string |
| `SANDBOX_URL` | `http://sandbox:6000` | SandboxClient | Sandbox service endpoint |
| `LOG_LEVEL` | `info` | AgentLogger | `debug`, `info`, `warning`, `error` |
| `LOG_FORMAT` | `json` | AgentLogger | `json` or `text` (dev mode) |

---

## Usage Example

```python
from common import LLMClient, MemoryClient, StorageClient, AgentLogger

# Initialize once at service startup
logger = AgentLogger(agent_name="agent-eval")
llm = LLMClient()        # reads LLM_GATEWAY_URL from env
memory = MemoryClient()   # reads MEMORY_URL from env
storage = StorageClient() # reads STORAGE_ENDPOINT from env

# Use in request handling
def evaluate_control(tenant_id: str, control_id: str, trace_id: str):
    log = logger.with_context(trace_id=trace_id, tenant_id=tenant_id)

    # Get evidence from storage
    metadata = storage.get_json(f"{tenant_id}/evidence/{control_id}/metadata.json")

    # Recall relevant context from memory
    context = memory.tenant_recall(tenant_id, f"control {control_id} evaluation history")

    # Call LLM for evaluation
    response = llm.complete(
        messages=[...],
        task="evaluate_control",
        tenant_id=tenant_id,
        trace_id=trace_id,
    )

    # Store result in memory
    memory.eval_store(tenant_id, framework="SOC2", control_id=control_id, result={...})

    log.info("Control evaluation complete", control_id=control_id, result="pass")
```

---

## Testing Strategy

Each client has unit tests using mocked HTTP backends:

- **LLMClient tests:** Mock gateway responses, verify retry behavior, test timeout handling, test `LLMUnavailableError` propagation
- **MemoryClient tests:** Mock memory service, verify graceful degradation returns empty, test all CRUD operations
- **StorageClient tests:** Mock both MinIO and S3 paths, verify auto-detection logic, test presigned URL generation
- **StateClient tests:** Mock PostgreSQL and DynamoDB backends, verify job lifecycle
- **SandboxClient tests:** Mock sandbox responses, verify timeout enforcement, test failure returns
- **AgentLogger tests:** Capture stdout, verify JSON structure, verify context propagation

Integration tests run against real services in Docker Compose (separate test profile).
