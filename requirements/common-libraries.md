# Shared: Common Libraries (common/)

## Purpose

Shared client libraries used by ALL agents. These are the abstraction layer that makes agents portable across environments. Every agent imports from `common/` — no agent talks to infrastructure directly.

## System Requirements Covered

| System Requirement | This module's role | Section |
|---|---|---|
| LLM Agnostic | LLMClient sends task name only, never model | §1 LLM Client |
| Storage Agnostic | StorageClient adapter selects S3/MinIO by env var | §3 Storage Client |
| AWS-First w/ Adapters | S3Adapter primary (boto3 + IAM), MinIOAdapter for on-prem | §Adapter Pattern |
| Per-Tenant Budget | LLMCreditExhaustedError with degradation metadata | §Error Hierarchy |
| Graceful Degradation | Each client defines degradation behavior (empty, error, fail) | §Error Hierarchy |
| PII-Aware Logging | AgentLogger: PII() wrapper, HMAC hashing, regex redaction, safe field allowlist | §6 Logger |
| Observability | Structured JSON logging with trace_id, node timing, LLM/tool call metrics | §6 Logger |
| Security Isolation | SandboxClient is the only code execution interface | §5 Sandbox Client |
| Memory is Shared | MemoryClient is the sole interface to memory-service | §2 Memory Client |
| Independent Deploy | COPY'd into each Docker image at build time | §Distribution |

## Libraries

### 1. LLM Client (`common/llm_client.py`)

The ONLY way agents interact with LLMs.

```python
class LLMResponse:
    content: str
    model_used: str
    tier_used: str             # fast | mid | strong
    escalated: bool
    input_tokens: int
    output_tokens: int
    latency_ms: float
    confidence: float | None
    tool_calls: list[dict]     # normalized tool calls (OpenAI format)

class LLMClient:
    def __init__(self, gateway_url: str = None):
        # Default from env: LLM_GATEWAY_URL

    def complete(
        self,
        messages: list[dict],
        task: str,                              # REQUIRED: what the agent is doing
        confidence_threshold: float = 0.0,     # escalation trigger
        structured_output: Type[BaseModel] = None,
        tools: list[dict] = None,              # OpenAI function-calling format
        max_tokens: int = 4096,
        temperature: float = 0.0,
        tenant_id: str = None,                 # for per-tenant tracking
        trace_id: str = None,                  # for correlation
    ) -> LLMResponse: ...

    def embed(self, texts: list[str]) -> list[list[float]]: ...
```

**Rules:**
- No agent imports `langchain_aws`, `openai`, `anthropic`, or any provider SDK
- No agent sets a model name — only a task name
- No agent handles retries or fallbacks — gateway does this
- Timeout: caller can set, default 120s
- Connection errors: raise `LLMUnavailableError` (agent decides how to handle)
- Credit/quota exhaustion: raise `LLMCreditExhaustedError` (agent enters degraded mode)

---

### 2. Memory Client (`common/memory_client.py`)

The ONLY way agents interact with memory.

```python
class MemoryClient:
    def __init__(self, memory_url: str = None):
        # Default from env: MEMORY_URL

    # Session
    def session_get(self, session_id: str) -> dict: ...
    def session_update(self, session_id: str, data: dict): ...
    def session_delete(self, session_id: str): ...

    # User memory (per-user preferences, responsibilities, behavior)
    def user_remember(self, tenant_id: str, user_id: str, fact: str, category: str, source: str): ...
    def user_recall(self, tenant_id: str, user_id: str, query: str, top_k: int = 5) -> list[dict]: ...
    def user_facts(self, tenant_id: str, user_id: str, category: str = None) -> list[dict]: ...

    # Tenant knowledge (org-wide)
    def tenant_remember(self, tenant_id: str, fact: str, category: str, source: str): ...
    def tenant_recall(self, tenant_id: str, query: str, top_k: int = 5) -> list[dict]: ...
    def tenant_facts(self, tenant_id: str, category: str = None) -> list[dict]: ...

    # Tasks & workflows
    def task_create(self, tenant_id: str, type: str, assignee_id: str = None, **kwargs) -> str: ...
    def task_update(self, tenant_id: str, task_id: str, status: str, **kwargs): ...
    def task_list(self, tenant_id: str, assignee: str = None, status: str = None, overdue: bool = False) -> list[dict]: ...
    def task_summary(self, tenant_id: str) -> dict: ...

    # Evaluation history
    def eval_store(self, tenant_id: str, framework: str, control_id: str, result: dict): ...
    def eval_last(self, tenant_id: str, framework: str, control_id: str) -> dict | None: ...
    def eval_history(self, tenant_id: str, framework: str, control_id: str, limit: int = 20) -> list[dict]: ...

    # Patterns
    def pattern_record(self, pattern: str, context: dict, confidence: float, source: str): ...
    def pattern_query(self, task: str, context: dict, top_k: int = 5) -> list[dict]: ...
    def pattern_boost(self, pattern_id: str): ...

    # Skills
    def skill_get(self, skill_id: str) -> dict | None: ...
    def skill_update(self, skill_id: str, new_version: dict, reason: str, author: str): ...
    def skill_rollback(self, skill_id: str, version: int): ...
    def skill_history(self, skill_id: str) -> list[dict]: ...

    # Interactions
    def save_interaction(self, tenant_id: str, user_id: str, session_id: str, messages: list[dict]): ...
```

**Rules:**
- No agent uses raw PostgreSQL, Redis, or DynamoDB
- Memory client handles connection pooling and retries
- Graceful degradation: if memory service is down, methods return empty/None (not crash)
- All calls include timeout (default 5s)

---

### 3. Storage Client (`common/storage_client.py`)

The ONLY way agents interact with file storage.

```python
class StorageClient:
    def __init__(self, endpoint: str = None, bucket: str = None):
        # Defaults from env: STORAGE_ENDPOINT, STORAGE_BUCKET
        # Works with: MinIO, S3, any S3-compatible store

    def get(self, key: str) -> bytes: ...
    def get_json(self, key: str) -> dict: ...
    def put(self, key: str, data: bytes, content_type: str = None): ...
    def put_json(self, key: str, obj: dict): ...
    def list(self, prefix: str) -> list[str]: ...
    def exists(self, key: str) -> bool: ...
    def delete(self, key: str): ...
    def presigned_upload_url(self, key: str, expires_sec: int = 3600) -> str: ...
    def presigned_download_url(self, key: str, expires_sec: int = 3600) -> str: ...
```

**Rules:**
- No agent uses `boto3.client('s3')` directly — always go through StorageClient
- Backend selected by `STORAGE_BACKEND` env var (`s3` or `minio`)
- `s3` backend: uses boto3 with IAM role credentials (default credential chain) — no access keys needed on AWS
- `minio` backend: uses minio SDK with explicit endpoint + access/secret keys
- All calls include timeout and retry (default 3 retries)
- Adding a new backend (e.g., Azure Blob, GCS): implement the adapter interface, zero agent changes

---

### 4. State Client (`common/state_client.py`)

For job tracking and async state (replaces DynamoDB-specific code).

```python
class StateClient:
    def __init__(self, backend: str = None, dsn: str = None):
        # backend from env: STATE_BACKEND (postgres | dynamodb)
        # dsn from env: STATE_DSN

    def set_job_status(self, job_id: str, status: str, data: dict = None): ...
    def get_job_status(self, job_id: str) -> dict | None: ...
    def set_job_result(self, job_id: str, result: dict): ...
    def get_job_result(self, job_id: str) -> dict | None: ...
    def cleanup_expired(self, ttl_hours: int = 24): ...
```

**Rules:**
- On-prem: uses PostgreSQL
- Cloud: uses DynamoDB (or PostgreSQL)
- Job data has TTL (auto-cleanup)
- Agents don't know or care which backend

---

### 5. Sandbox Client (`common/sandbox_client.py`)

The ONLY way agents execute untrusted code.

```python
@dataclass
class ExecutionResult:
    success: bool
    stdout: str
    stderr: str
    duration_ms: int
    memory_used_mb: int

class SandboxClient:
    def __init__(self, sandbox_url: str = None):
        # Default from env: SANDBOX_URL

    def execute(
        self,
        code: str,
        files: list[dict],               # [{storage_key, load_as, type}]
        timeout_sec: int = 60,
        memory_limit_mb: int = 512,
        trace_id: str = None,
    ) -> ExecutionResult: ...
```

**Rules:**
- No agent executes code in its own process (security boundary)
- Agent generates code, sandbox runs it
- Agent sends storage keys for data — sandbox downloads and loads them
- Timeout and memory limits enforced by sandbox service
- If sandbox service is down: return `ExecutionResult(success=False, stderr="Sandbox unavailable")`

---

### 6. Logger (`common/logger.py`)

Structured, PII-aware logging that the observer can parse safely. The logger enforces a separation between operational logs (PII-free, readable by observer and ops) and audit logs (full data, access-controlled in memory-service).

```python
from common.logger import AgentLogger, PII

class AgentLogger:
    def __init__(self, agent_name: str, trace_id: str = None, tenant_id: str = None):
        # Auto-generates trace_id if not provided

    def info(self, message: str, **context): ...
    def error(self, message: str, error: Exception = None, **context): ...
    def warn(self, message: str, **context): ...
    def debug(self, message: str, **context): ...

    def node_start(self, node_name: str) -> float: ...    # returns start time
    def node_end(self, node_name: str, start: float, **context): ...

    def llm_call(self, task: str, latency_ms: float, success: bool, **context): ...
    def tool_call(self, tool_name: str, latency_ms: float, success: bool, **context): ...

    def with_context(self, **kwargs) -> "AgentLogger": ...  # returns child logger with extra fields
```

#### PII-Aware Logging

The logger handles PII through three mechanisms:

**1. Explicit `PII()` wrapper** — for fields agents know contain user data:

```python
from common.logger import PII

# PII fields are hashed in operational logs (stdout), preserved in audit trail
logger.info("Reminder sent",
    control_id="CC6.1",                       # safe: logged as-is
    assignee=PII("john@acme.com"),            # → operational: assignee="[redacted:a3f2b1]"
    assignee_name=PII("John Smith"),          # → operational: assignee_name="[redacted:8c4d21]"
)
# The hash is deterministic (HMAC-SHA256 with service-level key) so the same
# value always produces the same token — useful for correlation without exposing PII
```

**2. Automatic regex redaction** — catches accidental PII in free-text message fields:

```python
# These patterns are scrubbed from the `message` field automatically:
REDACTION_PATTERNS = [
    (r'[\w.-]+@[\w.-]+\.\w+', '[EMAIL]'),               # email addresses
    (r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b', '[PHONE]'),     # phone numbers (US)
    (r'\b\d{3}-\d{2}-\d{4}\b', '[SSN]'),               # SSN
    (r'\b(?:\d{4}[-\s]?){3}\d{4}\b', '[CARD]'),        # credit card numbers
    (r'(?i)\b[A-Z]{2}\d{2}[\s]?\d{4}[\s]?\d{4}[\s]?\d{4}[\s]?\d{4}[\s]?\d{0,2}\b', '[IBAN]'),
]

# Example:
logger.info("User john@acme.com uploaded file")
# → operational log: message="User [EMAIL] uploaded file"
```

**3. Safe field allowlist** — context fields not wrapped in `PII()` are logged as-is only if they match the safe allowlist. Unknown fields trigger a warning in debug mode:

```python
SAFE_FIELDS = {
    # Identifiers (not PII — internal system IDs)
    "trace_id", "tenant_id", "session_id", "job_id", "task_id",
    "control_id", "framework", "framework_id", "skill_id", "pattern_id",
    # Operational metrics
    "duration_ms", "latency_ms", "memory_used_mb", "tokens", "cost_usd",
    "input_tokens", "output_tokens", "retries", "queue_position",
    # Status/type fields
    "status", "level", "task", "tier", "model_used", "tier_used",
    "success", "error_type", "degradation_level", "node_name",
    "tool_name", "file_type", "file_key", "storage_key",
    # Counts
    "count", "total", "row_count", "file_count", "queue_depth",
}

# Fields not in SAFE_FIELDS and not wrapped in PII() are:
# - Logged with a warning prefix in debug mode: "[UNCLASSIFIED:field_name]=value"
# - In production: treated as potentially sensitive, hashed like PII()
```

#### Two Output Streams

| Stream | Contains | Destination | Who reads it |
|--------|----------|-------------|-------------|
| **Operational log** | PII-free structured JSON | stdout (container logs) | Observer, ops, log aggregator |
| **Audit log** | Full data including PII | Memory service audit trail | Compliance auditors, authorized admins |

```python
# Internal implementation:
def _emit(self, level: str, message: str, context: dict):
    # Operational log (PII redacted) → stdout
    ops_entry = {
        "timestamp": now_iso(),
        "level": level,
        "service": self._agent_name,
        "trace_id": self._trace_id,
        "tenant_id": self._tenant_id,
        "message": self._redact_message(message),
        "context": self._redact_context(context),
    }
    print(json.dumps(ops_entry))
    
    # Audit log (full, unredacted) → memory service (async, best-effort)
    if self._audit_enabled and level in ("info", "warn", "error"):
        audit_entry = {
            **ops_entry,
            "message": message,              # original, unredacted
            "context": self._resolve_pii(context),  # PII() unwrapped to real values
        }
        self._audit_queue.put_nowait(audit_entry)
```

#### LLM Prompt/Response Logging

The LLM gateway log volume (consumed by observer) has special rules:

```python
# Gateway logging behavior (configurable in routing.yaml):
# log_prompts: true     → log prompts with PII redaction applied
# log_prompts: false    → don't log prompt content at all (only metadata)
# log_responses: true   → log responses with PII redaction applied
# log_responses: false  → don't log response content

# When logging prompts/responses, the gateway applies the same regex redaction
# so observer never sees raw user content that may contain PII
```

#### Configuration

```python
# Environment variables for logger behavior
LOG_LEVEL: str = "info"                    # debug | info | warn | error
LOG_FORMAT: str = "json"                   # json | text (text for local dev)
LOG_PII_REDACTION: bool = True             # enable/disable PII redaction (always True in prod)
LOG_AUDIT_ENABLED: bool = True             # send full logs to audit trail
LOG_AUDIT_URL: str = "http://memory-service:5000"  # audit trail endpoint
LOG_PII_HMAC_KEY: str = "${PII_HMAC_KEY}"  # HMAC key for deterministic hashing
LOG_UNKNOWN_FIELDS_ACTION: str = "redact"  # redact | warn | allow (prod=redact, dev=warn)
```

**Output format (operational — PII-free):**
```json
{
  "timestamp": "2026-06-01T14:32:01.456Z",
  "level": "info",
  "service": "agent-eval",
  "trace_id": "abc-123-def",
  "tenant_id": "acme_corp",
  "message": "Reminder sent for overdue evidence",
  "context": {
    "control_id": "CC6.1",
    "assignee": "[redacted:a3f2b1]",
    "days_overdue": 12,
    "framework": "soc2"
  }
}
```

**Rules:**
- No agent uses `print()` for logging — always `AgentLogger`
- All PII fields MUST be wrapped in `PII()` — code review enforces this
- Operational logs (stdout) MUST be safe for observer and ops consumption
- Audit trail in memory-service stores unredacted data (access-controlled, append-only)
- `PII_HMAC_KEY` MUST be set in production — logger refuses to start without it
- Same PII value always produces the same hash (enables correlation across logs without exposing data)
- Regex redaction is defense-in-depth — catches PII that wasn't wrapped in `PII()` by mistake

---

## Distribution

Two options (decide during implementation):

### Option A: Python Package (pip install)
```
common/
├── pyproject.toml
├── common/
│   ├── __init__.py
│   ├── llm_client.py
│   ├── memory_client.py
│   ├── storage_client.py
│   ├── state_client.py
│   └── logger.py
```
- Published to private PyPI (or local wheel)
- Each agent's `requirements.txt` includes `compliance-common==1.2.0`
- Versioned independently from agents
- Upgrade: bump version in agent's requirements, rebuild

### Option B: Copied into each image (simpler)
```
# In each agent's Dockerfile:
COPY common/ /app/common/
```
- No package management
- Kept in sync via CI (lint check: all agents use same common/ version)
- Slightly more duplication, much simpler ops

**Recommendation:** Start with Option B (copy). Move to Option A when you have >5 agents and the common lib stabilizes.

---

## Error Hierarchy

```python
class CommonError(Exception):
    """Base for all common library errors."""

class LLMUnavailableError(CommonError):
    """LLM gateway is unreachable or returned 5xx."""

class LLMTimeoutError(LLMUnavailableError):
    """LLM request exceeded timeout."""

class LLMCreditExhaustedError(LLMUnavailableError):
    """All LLM budget/credits exhausted for this tenant. System in degraded mode."""
    degradation_level: int      # 1=strong gone, 2=mid gone, 3=fast gone, 4=all gone
    tier_availability: dict     # {"fast": "available", "mid": "exhausted", "strong": "exhausted"}
    estimated_recovery: str | None  # ISO timestamp when budget resets, or None if unknown
    can_queue: bool             # True if gateway will queue and process when credits return
    queued_position: int | None # Position in queue if request was queued

class StorageError(CommonError):
    """Storage operation failed after retries."""

class StorageNotFoundError(StorageError):
    """Requested key does not exist."""

class SandboxError(CommonError):
    """Sandbox service is unreachable."""

class StateError(CommonError):
    """State backend operation failed."""
```

**Agent behavior on `LLMCreditExhaustedError`:**
- agent-eval: fall back to Layer 1 (rules-only) results, mark `partial_evaluation=True`
- compliance-assistant: switch to data-only mode (MCP tools, memory, status still work)
- observer: pause all diagnosis and optimization, continue metric collection
- preprocessor: continue deterministic processing, skip optional LLM schema detection

---

## Configuration (shared across all agents)

All common libraries read from environment variables with sensible defaults.

**AWS deployment defaults (primary):**

```bash
# LLM
LLM_GATEWAY_URL=http://llm-gateway:4000

# Memory
MEMORY_URL=http://memory-service:5000

# Storage (AWS-first: S3 via IAM role — no endpoint needed)
STORAGE_BACKEND=s3              # s3 | minio
STORAGE_BUCKET=compliance-artifacts
# When STORAGE_BACKEND=s3: uses boto3 with IAM role credentials (no keys needed)
# When STORAGE_BACKEND=minio: uses STORAGE_ENDPOINT + access/secret keys
STORAGE_ENDPOINT=              # Only for minio: http://minio:9000
STORAGE_ACCESS_KEY=            # Only for minio
STORAGE_SECRET_KEY=            # Only for minio
AWS_REGION=us-east-1           # S3 region

# State (AWS-first: RDS PostgreSQL)
STATE_BACKEND=postgres
STATE_DSN=postgresql://compliance:${DB_PASSWORD}@${DB_HOST}:5432/compliance

# Logging
LOG_LEVEL=info
LOG_FORMAT=json
```

**Local development overrides:**

```bash
# Local dev uses MinIO and local PostgreSQL
STORAGE_BACKEND=minio
STORAGE_ENDPOINT=http://minio:9000
STORAGE_ACCESS_KEY=minioadmin
STORAGE_SECRET_KEY=minioadmin
STATE_DSN=postgresql://compliance:pass@postgres:5432/compliance
```

---

## Adapter Pattern

The common libraries use an adapter pattern to decouple agents from infrastructure:

```
Agent Code → Common Client (interface) → Adapter (implementation) → Infrastructure
```

| Client | Adapters | Selection |
|--------|----------|-----------|
| StorageClient | S3Adapter, MinIOAdapter | `STORAGE_BACKEND` env var |
| StateClient | PostgreSQLAdapter, DynamoDBAdapter | `STATE_BACKEND` env var |
| LLMClient | (talks to gateway, not directly to providers) | N/A — gateway handles |
| MemoryClient | (talks to memory-service, not directly to DB) | N/A — service handles |

Agents are completely unaware of which adapter is active. Adding a new backend (e.g., Azure Blob for storage) means adding one adapter class — zero agent changes.

```python
class StorageClient:
    def __init__(self):
        backend = os.getenv("STORAGE_BACKEND", "s3")
        if backend == "s3":
            self._adapter = S3Adapter(region=os.getenv("AWS_REGION", "us-east-1"))
        elif backend == "minio":
            self._adapter = MinIOAdapter(
                endpoint=os.getenv("STORAGE_ENDPOINT"),
                access_key=os.getenv("STORAGE_ACCESS_KEY"),
                secret_key=os.getenv("STORAGE_SECRET_KEY"),
            )
        else:
            raise ValueError(f"Unknown storage backend: {backend}")

    def get(self, key: str) -> bytes:
        return self._adapter.get(key)
    # ... all methods delegate to self._adapter
```

For local development, everything has defaults that work with `docker compose up`.
