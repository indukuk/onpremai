# Shared: Common Libraries (common/)

## Purpose

Shared client libraries used by ALL agents. These are the abstraction layer that makes agents portable across environments. Every agent imports from `common/` — no agent talks to infrastructure directly.

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
- No agent uses `boto3.client('s3')` directly
- Uses `boto3` or `minio` under the hood (auto-detect based on endpoint)
- If endpoint is `http://...` (non-AWS): use MinIO client
- If endpoint is `https://s3.amazonaws.com` or missing: use boto3 with default credentials
- All calls include timeout and retry (default 3 retries)

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

Structured logging that the observer can parse.

```python
class AgentLogger:
    def __init__(self, agent_name: str, trace_id: str = None, tenant_id: str = None):
        # Auto-generates trace_id if not provided

    def info(self, message: str, **context): ...
    def error(self, message: str, error: Exception = None, **context): ...
    def debug(self, message: str, **context): ...

    def node_start(self, node_name: str) -> float: ...    # returns start time
    def node_end(self, node_name: str, start: float, **context): ...

    def llm_call(self, task: str, latency_ms: float, success: bool, **context): ...
    def tool_call(self, tool_name: str, latency_ms: float, success: bool, **context): ...
```

**Output format:** structured JSON to stdout (container logging picks it up)
```json
{"timestamp": "...", "level": "info", "agent": "agent-eval", "trace_id": "...", "tenant_id": "...", "message": "...", "context": {...}}
```

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

## Configuration (shared across all agents)

All common libraries read from environment variables with sensible defaults:

```bash
# LLM
LLM_GATEWAY_URL=http://llm-gateway:4000

# Memory
MEMORY_URL=http://memory-service:5000

# Storage
STORAGE_ENDPOINT=http://minio:9000
STORAGE_BUCKET=compliance-artifacts
STORAGE_ACCESS_KEY=minioadmin
STORAGE_SECRET_KEY=minioadmin

# State
STATE_BACKEND=postgres
STATE_DSN=postgresql://compliance:pass@postgres:5432/compliance

# Logging
LOG_LEVEL=info
LOG_FORMAT=json
```

For local development, everything has defaults that work with `docker compose up`.
