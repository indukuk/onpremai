# Observability & Installation Diagnostics

## Purpose

Every service in the system must be debuggable at two levels:
1. **Installation/startup** — what failed during deployment, why a container won't start
2. **Runtime** — what's failing during operation, which component broke, what's the impact

This document defines the logging, health-check, and diagnostic requirements that apply across ALL services.

---

## Part 1: Installation & Startup Logging

### Problem

When a customer deploys `docker compose up -d` and something doesn't work, they see:
- A container in restart loop
- A health check failing
- A service returning 503

They need to know: **what failed, why, and how to fix it** — without reading source code.

### R1: Startup Sequence Logging

Every service MUST log a structured startup sequence with pass/fail per step:

```
[2026-05-11T10:00:01Z] [INFO]  [startup] ====== compliance-assistant v1.5.0 starting ======
[2026-05-11T10:00:01Z] [INFO]  [startup] step=1/7 name="load_config" status=OK config_source=env
[2026-05-11T10:00:01Z] [INFO]  [startup] step=2/7 name="connect_redis" status=OK host=redis:6379 latency_ms=12
[2026-05-11T10:00:02Z] [INFO]  [startup] step=3/7 name="connect_memory_service" status=OK url=http://memory-service:5000 latency_ms=45
[2026-05-11T10:00:02Z] [INFO]  [startup] step=4/7 name="connect_llm_gateway" status=OK url=http://llm-gateway:4000 latency_ms=23
[2026-05-11T10:00:02Z] [INFO]  [startup] step=5/7 name="connect_mcp" status=OK url=http://backend:8080/mcp latency_ms=67
[2026-05-11T10:00:02Z] [INFO]  [startup] step=6/7 name="load_personas" status=OK count=5
[2026-05-11T10:00:02Z] [INFO]  [startup] step=7/7 name="load_default_skills" status=OK count=47
[2026-05-11T10:00:02Z] [INFO]  [startup] ====== compliance-assistant READY (1.2s) ======
```

**On failure:**

```
[2026-05-11T10:00:01Z] [INFO]  [startup] ====== memory-service v1.0.0 starting ======
[2026-05-11T10:00:01Z] [INFO]  [startup] step=1/5 name="load_config" status=OK
[2026-05-11T10:00:01Z] [INFO]  [startup] step=2/5 name="connect_postgres" status=CONNECTING host=postgres:5432
[2026-05-11T10:00:06Z] [ERROR] [startup] step=2/5 name="connect_postgres" status=FAILED error="connection refused" host=postgres:5432 retries=3
[2026-05-11T10:00:06Z] [ERROR] [startup] ====== memory-service FAILED TO START ======
[2026-05-11T10:00:06Z] [ERROR] [startup] reason="Cannot connect to PostgreSQL at postgres:5432"
[2026-05-11T10:00:06Z] [ERROR] [startup] fix="Check that postgres container is running: docker compose ps postgres"
[2026-05-11T10:00:06Z] [ERROR] [startup] fix="Check DB_HOST and DB_PORT environment variables"
[2026-05-11T10:00:06Z] [ERROR] [startup] fix="Check postgres logs: docker compose logs postgres"
```

### R2: Startup Steps Per Service

| Service | Startup steps (in order) |
|---------|-------------------------|
| **compliance-assistant** | load_config → connect_redis → connect_memory → connect_llm_gateway → connect_mcp → load_personas → load_default_skills |
| **agent-eval** | load_config → connect_memory → connect_llm_gateway → connect_storage → connect_sandbox → load_rag_index → verify_rag_index |
| **llm-gateway** | load_config → load_routing_config → verify_models (ping each) → start_health_checker → open_ports |
| **memory-service** | load_config → connect_postgres → run_migrations → connect_redis → connect_llm_gateway (for embeddings) → verify_tables |
| **observer** | load_config → connect_llm_gateway → connect_memory → verify_log_path → load_policy → start_scheduler |
| **sandbox-service** | load_config → connect_storage → verify_docker_socket → pull_runtime_image → verify_runtime_image → start_queue |
| **preprocessor** | load_config → connect_storage → connect_memory → verify_ocr_backend → start_trigger (poll/webhook) |

### R3: Dependency Check on Startup

Each service checks its dependencies BEFORE accepting traffic:

```python
# Pattern for every service
async def startup():
    checks = [
        ("postgres", check_postgres, REQUIRED),
        ("redis", check_redis, REQUIRED),
        ("llm_gateway", check_llm_gateway, OPTIONAL),  # can start without, degrades gracefully
        ("mcp", check_mcp, OPTIONAL),
    ]
    
    for name, check_fn, criticality in checks:
        try:
            await check_fn()
            log_startup_step(name, "OK")
        except Exception as e:
            if criticality == REQUIRED:
                log_startup_step(name, "FAILED", error=str(e), fix=get_fix_hint(name, e))
                raise StartupError(f"Required dependency '{name}' unavailable: {e}")
            else:
                log_startup_step(name, "DEGRADED", error=str(e))
                # Continue startup, but mark service as degraded
```

### R4: Fix Hints

Every startup failure includes a human-readable fix suggestion:

| Failure | Fix hint |
|---------|----------|
| PostgreSQL connection refused | "Check postgres container is running. Verify DB_HOST={host} DB_PORT={port}" |
| Redis connection refused | "Check redis container is running. Verify REDIS_URL={url}" |
| LLM gateway unreachable | "Check llm-gateway container is running on port 4000" |
| Storage (MinIO) unreachable | "Check minio container is running. Verify STORAGE_ENDPOINT={url}" |
| Docker socket not found | "Mount Docker socket: volumes: ['/var/run/docker.sock:/var/run/docker.sock']" |
| Runtime image not found | "Pull image: docker pull {RUNTIME_IMAGE}" |
| Migration failed | "Check postgres logs. Possible schema conflict. Try: docker compose down -v postgres" |
| RAG index not found | "Upload RAG index to storage: {bucket}/rag-kb/v2/" |
| Config file parse error | "Check config/routing.yaml syntax. Error at line {n}: {detail}" |
| Port already in use | "Port {port} is taken. Check: lsof -i :{port}" |

### R5: Installation Verification Script

A built-in diagnostic command that checks the entire stack:

```bash
# Run from deployment directory
docker compose exec compliance-assistant python -m diagnostics

# Output:
╔══════════════════════════════════════════════════════════╗
║           SYSTEM HEALTH CHECK                            ║
╠══════════════════════════════════════════════════════════╣
║ Service              │ Status │ Version │ Uptime         ║
╠══════════════════════════════════════════════════════════╣
║ compliance-assistant │ ✅ OK  │ 1.5.0   │ 2h 15m        ║
║ agent-eval           │ ✅ OK  │ 1.5.0   │ 2h 15m        ║
║ llm-gateway          │ ✅ OK  │ 1.2.0   │ 2h 15m        ║
║ memory-service       │ ✅ OK  │ 1.0.0   │ 2h 15m        ║
║ observer             │ ✅ OK  │ 1.0.0   │ 2h 15m        ║
║ sandbox-service      │ ✅ OK  │ 1.0.0   │ 2h 15m        ║
║ preprocessor         │ ✅ OK  │ 1.0.3   │ 2h 15m        ║
║ postgres             │ ✅ OK  │ 16      │ 2h 16m        ║
║ redis                │ ✅ OK  │ 7.2     │ 2h 16m        ║
║ minio                │ ✅ OK  │ latest  │ 2h 16m        ║
╠══════════════════════════════════════════════════════════╣
║ LLM Models           │ Status │ Provider │ Latency       ║
╠══════════════════════════════════════════════════════════╣
║ ollama-8b            │ ✅ OK  │ ollama   │ 120ms         ║
║ vllm-70b             │ ❌ DOWN│ vllm     │ timeout       ║
║ sonnet-cloud         │ ✅ OK  │ anthropic│ 890ms         ║
╠══════════════════════════════════════════════════════════╣
║ Integration Tests    │ Status                            ║
╠══════════════════════════════════════════════════════════╣
║ LLM round-trip       │ ✅ "Hello" → response in 1.2s    ║
║ Memory write/read    │ ✅ write + recall in 45ms         ║
║ Storage put/get      │ ✅ upload + download in 23ms      ║
║ Sandbox execute      │ ✅ print("ok") → "ok" in 650ms   ║
║ Eval pipeline        │ ✅ CC6.1 mock eval in 4.2s        ║
╠══════════════════════════════════════════════════════════╣
║ Issues Found: 1                                          ║
║ ⚠️ vllm-70b is down — gateway will use fallback models  ║
╚══════════════════════════════════════════════════════════╝
```

---

## Part 2: Runtime Failure Logging

### R6: Structured Log Format (all services)

Every log line is structured JSON (parsed by log aggregators, searched by operators):

```json
{
  "timestamp": "2026-05-11T10:15:23.456Z",
  "level": "error",
  "service": "agent-eval",
  "version": "1.5.0",
  "trace_id": "abc-123-def",
  "tenant_id": "acme_corp",
  "component": "evaluation_node",
  "message": "LLM call failed after 3 retries",
  "error": {
    "type": "LLMTimeoutError",
    "message": "Gateway returned 504 after 120s",
    "stack": "..."
  },
  "context": {
    "control_id": "CC6.1",
    "framework": "soc2",
    "task": "evaluate_control",
    "model_attempted": "vllm-70b",
    "retries": 3,
    "latency_ms": 120000
  },
  "impact": "Evaluation will use cached result or return insufficient_evidence"
}
```

### R7: Error Classification

Every error is classified by severity and impact:

| Level | Meaning | Action | Example |
|-------|---------|--------|---------|
| `fatal` | Service cannot continue | Restart required | DB connection permanently lost |
| `error` | Operation failed | Request fails, others continue | LLM timeout on one evaluation |
| `warn` | Degraded but functional | Monitor, may escalate | Model health check failed, using fallback |
| `info` | Normal operation | No action | Evaluation completed in 4.2s |
| `debug` | Diagnostic detail | For troubleshooting only | Token counts, prompt lengths |

### R8: Failure Correlation (trace_id)

Every request gets a `trace_id` that propagates across ALL service calls:

```
User sends message → compliance-assistant (trace: abc-123)
  → LLM gateway call (trace: abc-123)
  → Memory service call (trace: abc-123)
  → MCP tool call (trace: abc-123)
    → agent-eval (trace: abc-123)
      → sandbox-service (trace: abc-123)
```

When something fails, search by trace_id to see the full request path across all services:

```bash
# Find all logs for a failed request
docker compose logs --no-log-prefix | grep "abc-123" | sort
```

### R9: Health Check Endpoints (all services)

Every service exposes:

```
GET /health     → 200 if process alive (for Docker HEALTHCHECK)
GET /ready      → 200 if ready to serve (all deps connected)
GET /diagnostics → detailed status (for debugging)
```

`/diagnostics` response:

```json
{
  "service": "agent-eval",
  "version": "1.5.0",
  "status": "healthy",
  "uptime_sec": 8100,
  "dependencies": {
    "llm_gateway": {"status": "healthy", "latency_ms": 23, "last_check": "10s ago"},
    "memory_service": {"status": "healthy", "latency_ms": 12, "last_check": "10s ago"},
    "storage": {"status": "healthy", "latency_ms": 8, "last_check": "10s ago"},
    "sandbox": {"status": "degraded", "error": "high latency (2.1s)", "last_check": "10s ago"}
  },
  "metrics": {
    "requests_total": 1847,
    "requests_failed": 23,
    "avg_latency_ms": 4200,
    "active_requests": 2
  }
}
```

### R10: Common Failure Scenarios & What Gets Logged

| Failure | Which service logs it | What it logs | Impact |
|---------|----------------------|-------------|--------|
| LLM model timeout | llm-gateway | model_id, task, timeout_ms, will_retry | Retries at same tier or escalates |
| All models in tier down | llm-gateway | tier, models_attempted, escalating_to | Escalates or returns error |
| Memory service unreachable | any agent | operation, fallback_used | Agent continues with empty context |
| Storage unreachable | agent-eval, preprocessor | operation, file_key | Evaluation fails |
| Sandbox timeout | sandbox-service | code_length, timeout_sec, memory_used | Execution fails, agent retries with code_fixer |
| Sandbox OOM | sandbox-service | memory_limit, actual_used | Execution fails |
| Blocked import in sandbox | sandbox-service | import_name, code_snippet | Execution fails, logged as security event |
| PostgreSQL connection lost | memory-service | reconnect_attempts, last_error | Service degrades, retries |
| Redis down | memory-service, compliance-assistant | fallback (skip session cache) | Sessions not persisted, continues |
| Config parse error | llm-gateway | file_path, line_number, error | Hot-reload rejected, keeps old config |
| Evidence file corrupt | preprocessor | file_key, file_type, error | Metadata not generated, logged |
| Docker socket error | sandbox-service | operation, error | All executions fail |
| MCP tool fails | compliance-assistant | tool_name, error, will_retry | Tool result unavailable, agent tells user |
| Evaluation criteria missing | agent-eval | control_id, framework | Falls back to LLM-only evaluation |

### R11: Operator Alerts

Critical failures that need immediate attention send alerts (via observer notification webhook):

| Alert | Condition | Urgency |
|-------|-----------|---------|
| Service restart loop | Container restarted >3 times in 5 minutes | Critical |
| All LLM models down | No model in any tier responding | Critical |
| Database unreachable | PostgreSQL not responding for >30s | Critical |
| Storage unreachable | MinIO not responding for >30s | Critical |
| High error rate | >10% of requests failing in 5 min window | High |
| Sandbox all failing | >90% sandbox executions failing | High |
| Disk space low | <10% remaining on any volume | High |
| Memory pressure | Container using >90% memory limit | Warning |

---

## Part 3: Installation Runbook

### R12: `docker compose` Events Logging

The deployment setup includes a log collector that captures docker events:

```yaml
# docker-compose.yml addition
services:
  log-collector:
    image: alpine
    command: >
      sh -c "docker events --format '{{json .}}' 
             --filter 'event=start' 
             --filter 'event=die' 
             --filter 'event=health_status'"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - ./logs/events:/logs
    profiles: ["diagnostics"]
```

### R13: First-Run Validation

On first deployment, a validation script runs automatically:

```bash
#!/bin/bash
# scripts/validate-install.sh (runs after docker compose up)

echo "=== Waiting for services to start (max 60s) ==="
for service in postgres redis minio llm-gateway memory-service; do
  echo -n "  $service: "
  timeout 60 bash -c "until docker compose exec $service wget -q --spider http://localhost:\$(docker compose port $service | cut -d: -f2)/health 2>/dev/null; do sleep 2; done"
  echo "✅"
done

echo ""
echo "=== Running integration checks ==="
docker compose exec compliance-assistant python -m diagnostics --format=brief

echo ""
echo "=== Installation complete ==="
```

### R14: Log Retention & Access

```yaml
# Docker compose logging config for all services
x-logging: &default-logging
  driver: json-file
  options:
    max-size: "50m"
    max-file: "5"
    tag: "{{.Name}}"

services:
  compliance-assistant:
    logging: *default-logging
  agent-eval:
    logging: *default-logging
  # ... all services
```

Access logs:
```bash
# All logs for a service
docker compose logs compliance-assistant

# Last 100 lines
docker compose logs --tail 100 agent-eval

# Follow real-time
docker compose logs -f llm-gateway

# Grep across all services for a trace
docker compose logs --no-log-prefix | grep "trace_id.*abc-123"

# Only errors
docker compose logs | grep '"level":"error"'
```
