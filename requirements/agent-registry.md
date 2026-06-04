# Agent Registry

## Purpose

A dynamic registry where agents declare their identity, capabilities, and health status. Enables capability-based routing, version coexistence, and graceful degradation when agents are unavailable. As the system grows beyond the initial 8 services, new agent types can join without hardcoded wiring.

## System Requirements Covered

| System Requirement | This module's role |
|---|---|
| LLM Agnostic | Registry stores task→agent mappings alongside gateway's task→model mappings |
| Graceful Degradation | Health-aware routing — skip degraded agents, queue work for offline agents |
| Self-Improving | Observer reads registry to understand system topology, tunes routing weights |
| Independent Deploy | New agents register on startup, deregister on shutdown — no config changes needed |
| Memory is Shared | Registry lives in memory-service (shared state) |

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                     Agent Registry                             │
│              (memory-service /registry/ routes)                │
│                                                               │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │  Registry Table (PostgreSQL)                             │ │
│  │                                                          │ │
│  │  agent_id │ agent_type │ capabilities │ version │ health │ │
│  │  ─────────┼────────────┼──────────────┼─────────┼─────── │ │
│  │  eval-01  │ agent-eval │ [evaluate_*] │ 1.5.0   │ healthy│ │
│  │  eval-02  │ agent-eval │ [evaluate_*] │ 1.6.0   │ healthy│ │
│  │  assist-1 │ assistant  │ [chat,skill] │ 2.0.0   │ healthy│ │
│  │  vendor-1 │ vendor-risk│ [assess_*]   │ 1.0.0   │ warm   │ │
│  └─────────────────────────────────────────────────────────┘ │
│                                                               │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │  Heartbeat Cache (Redis)                                 │ │
│  │  agent:{id}:heartbeat → last_seen, load, queue_depth    │ │
│  └─────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
         │                    │                    │
         ▼                    ▼                    ▼
   ┌───────────┐      ┌────────────┐      ┌────────────┐
   │ Agents    │      │ llm-gateway│      │  observer  │
   │ (register │      │ (resolve   │      │ (topology  │
   │  on start)│      │  task→agent)│      │  aware)    │
   └───────────┘      └────────────┘      └────────────┘
```

---

## Data Model

### R1: Agent Registration Record

Each running agent instance registers with:

```python
@dataclass
class AgentRegistration:
    agent_id: str              # Unique instance ID (e.g., "agent-eval-abc123")
    agent_type: str            # Logical type (e.g., "agent-eval", "compliance-assistant", "vendor-risk")
    version: str               # Semver (e.g., "1.5.0")
    capabilities: list[str]    # Task names this agent can handle (e.g., ["evaluate_control", "evaluate_vendor"])
    endpoint: str              # How to reach this instance (e.g., "http://agent-eval:8080")
    tenant_scope: str | None   # None = all tenants, or specific tenant_id for dedicated instances
    max_concurrency: int       # Max parallel requests this instance accepts
    metadata: dict             # Arbitrary k/v (model preferences, supported frameworks, etc.)
    registered_at: datetime
    last_heartbeat: datetime
    health: AgentHealth        # healthy | degraded | unhealthy | draining
```

### R2: Agent Capabilities Schema

Capabilities are task names matching the llm-gateway's task routing. An agent advertises what tasks it can fulfill:

```python
class AgentCapability:
    task: str                  # Task name (matches gateway routing, e.g., "evaluate_control")
    priority: int              # 0-100, higher = prefer this agent for this task (default 50)
    constraints: dict | None   # Optional: {"frameworks": ["SOC2", "ISO27001"], "max_evidence_size_mb": 100}
```

Example registrations:

```yaml
# agent-eval v1.5 (current production)
agent_type: agent-eval
capabilities:
  - task: evaluate_control
    priority: 50
  - task: evaluate_vendor
    priority: 50
  - task: generate_evidence_report
    priority: 30

# agent-eval v1.6 (canary, 10% traffic)
agent_type: agent-eval
capabilities:
  - task: evaluate_control
    priority: 10    # Lower priority = canary gets less traffic
  - task: evaluate_vendor
    priority: 10
  - task: evaluate_regulatory_change   # New capability in v1.6
    priority: 100

# vendor-risk-agent (new agent type)
agent_type: vendor-risk
capabilities:
  - task: assess_vendor_risk
    priority: 100
  - task: vendor_questionnaire_review
    priority: 100
  - task: evaluate_vendor
    priority: 80   # Can also handle this, higher priority than agent-eval
```

---

## API

### R3: Registration Lifecycle

Agents register on startup, heartbeat during operation, deregister on shutdown:

```
POST   /registry/agents              — Register (or re-register) an agent instance
PUT    /registry/agents/{agent_id}/heartbeat — Heartbeat with load metrics
DELETE /registry/agents/{agent_id}   — Deregister (graceful shutdown)
GET    /registry/agents              — List all registered agents (observer, admin)
GET    /registry/agents?capability={task} — Find agents that can handle a task
GET    /registry/capabilities        — List all available capabilities across all agents
```

**Registration request:**

```python
class RegisterRequest(BaseModel):
    agent_type: str
    version: str
    capabilities: list[AgentCapability]
    endpoint: str
    tenant_scope: str | None = None
    max_concurrency: int = 10
    metadata: dict = {}
```

**Registration response:**

```python
class RegisterResponse(BaseModel):
    agent_id: str              # Assigned by registry (or echoed if re-registration)
    lease_ttl_sec: int         # Heartbeat must arrive within this window (default 30s)
    registry_version: int      # Monotonic counter — changes when any agent registers/deregisters
```

### R4: Heartbeat & Health

Agents send heartbeats every `lease_ttl_sec / 3` (default: every 10s):

```python
class HeartbeatRequest(BaseModel):
    health: AgentHealth                    # healthy | degraded | unhealthy | draining
    current_load: int                      # Active requests in flight
    queue_depth: int                       # Pending requests in local queue
    degradation_reason: str | None = None  # Why degraded (e.g., "LLM credits exhausted")
    metrics: dict = {}                     # Optional: latency_p99, error_rate, etc.
```

**Health state machine:**

```
healthy → degraded → unhealthy → expired (missed heartbeat)
healthy → draining (graceful shutdown in progress)
any → healthy (recovery)
```

**Missed heartbeat handling:**
- 1 missed (>30s): mark `unhealthy`, stop routing new work
- 3 missed (>90s): mark `expired`, remove from active routing
- Instance record preserved for 24h (allows re-registration with same agent_id)

### R5: Capability Discovery

The primary consumer is task routing — "given task X, which agents can handle it?"

```python
class DiscoverRequest(BaseModel):
    task: str                       # Required: what task needs handling
    tenant_id: str | None = None    # Optional: filter to agents scoped to this tenant
    health_filter: list[AgentHealth] = ["healthy", "degraded"]  # Skip unhealthy by default
    
class DiscoverResponse(BaseModel):
    agents: list[AgentMatch]        # Sorted by priority (descending), then load (ascending)
    
class AgentMatch(BaseModel):
    agent_id: str
    agent_type: str
    endpoint: str
    priority: int
    current_load: int
    max_concurrency: int
    health: AgentHealth
    version: str
```

---

## Integration Points

### R6: Integration with llm-gateway

The gateway currently resolves `task → model`. With the registry, it can also resolve `task → agent` for inter-agent delegation:

```python
# In llm-gateway routing — extended flow:
async def route_request(request: CompletionRequest) -> Response:
    # 1. Existing: resolve task → model (for LLM calls)
    model = resolve_model(request.task, request.tenant_id)
    
    # 2. NEW: if task maps to an agent capability (not just a model),
    #    delegate to that agent instead of calling LLM directly
    if is_agent_task(request.task):
        agent = await registry_client.discover(request.task, request.tenant_id)
        if agent:
            return await delegate_to_agent(agent, request)
        # No agent available — queue or fallback
```

This enables the gateway to act as a **unified router** — callers don't need to know whether a task is handled by an LLM or by another agent.

### R7: Integration with common/ (RegistryClient)

New client in `common/` for all services to use:

```python
from common import RegistryClient

registry = RegistryClient()  # Talks to memory-service /registry/ routes

# On startup — register this agent
registration = await registry.register(
    agent_type="agent-eval",
    version="1.5.0",
    capabilities=[
        {"task": "evaluate_control", "priority": 50},
        {"task": "evaluate_vendor", "priority": 50},
    ],
    endpoint="http://agent-eval:8080",
    max_concurrency=10,
)

# Heartbeat loop (background task)
async def heartbeat_loop(agent_id: str, ttl: int):
    while True:
        await registry.heartbeat(agent_id, health="healthy", load=current_load())
        await asyncio.sleep(ttl // 3)

# On shutdown — deregister
await registry.deregister(registration.agent_id)

# Discovery — find who can handle a task
agents = await registry.discover(task="evaluate_vendor", tenant_id="acme-corp")
# Returns: sorted list of healthy agents with capacity
```

### R8: Integration with observer

Observer uses the registry for:
1. **Topology awareness** — knows all running agents, versions, and health
2. **Canary monitoring** — compares metrics between versions of the same agent_type
3. **Capacity planning** — detects when all instances of a capability are near max_concurrency
4. **Self-governance reporting** — agent inventory (what's running, what version, what model each uses)

### R9: Integration with compliance-assistant (Inter-Agent Messaging)

Shadow AI agents discover each other via the registry to coordinate:

```python
# Compliance manager's agent wants to nudge a control owner's agent
async def send_inter_agent_message(from_session: Session, target_user_id: str, message: dict):
    # Find the target user's agent instance
    agents = await registry.discover(task="receive_notification", tenant_id=from_session.tenant_id)
    
    # Route message to the appropriate instance
    target_agent = next((a for a in agents if a.metadata.get("user_scope") == target_user_id), None)
    
    if target_agent:
        await httpx_client.post(f"{target_agent.endpoint}/notify", json=message)
    else:
        # User's agent not active — store in memory for next session
        await memory.store_pending_notification(target_user_id, message)
```

---

## Routing Strategy

### R10: Priority-Based Routing with Load Balancing

When multiple agents can handle a task, select using:

```
1. Filter: health in [healthy, degraded] AND current_load < max_concurrency
2. Filter: tenant_scope matches (None = any tenant, or specific match)
3. Sort: priority DESC, then (current_load / max_concurrency) ASC
4. Select: top agent (or weighted random across top N for load distribution)
```

### R11: Version Coexistence (Canary Deployments)

Multiple versions of the same agent_type can coexist. Traffic split is controlled by priority values:

```yaml
# Production agent-eval (90% traffic)
agent_type: agent-eval
version: "1.5.0"
capabilities:
  - task: evaluate_control
    priority: 90

# Canary agent-eval (10% traffic)  
agent_type: agent-eval
version: "1.6.0"
capabilities:
  - task: evaluate_control
    priority: 10
```

Observer monitors both and can:
- Promote canary: update priority to 90, demote old to 10, then 0
- Rollback canary: set priority to 0 (or deregister)

### R12: Graceful Degradation When No Agent Available

```
Level 0: Healthy agents available → route normally
Level 1: Only degraded agents → route with warning header, expect slower response
Level 2: No agents available → queue request in memory-service (persistent)
Level 3: Queue full → reject with 503 + estimated recovery time
```

Queued requests are processed FIFO when an agent registers (or recovers) with the matching capability.

---

## Storage

### R13: PostgreSQL Table (memory-service)

```sql
CREATE TABLE agent_registry (
    agent_id        TEXT PRIMARY KEY,
    agent_type      TEXT NOT NULL,
    version         TEXT NOT NULL,
    capabilities    JSONB NOT NULL,         -- [{task, priority, constraints}]
    endpoint        TEXT NOT NULL,
    tenant_scope    TEXT,                   -- NULL = all tenants
    max_concurrency INT NOT NULL DEFAULT 10,
    metadata        JSONB DEFAULT '{}',
    health          TEXT NOT NULL DEFAULT 'healthy',
    current_load    INT NOT NULL DEFAULT 0,
    queue_depth     INT NOT NULL DEFAULT 0,
    registered_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_heartbeat  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    degradation_reason TEXT
);

CREATE INDEX idx_registry_capability ON agent_registry USING GIN (capabilities);
CREATE INDEX idx_registry_type ON agent_registry (agent_type);
CREATE INDEX idx_registry_health ON agent_registry (health);

-- No RLS: registry is cross-tenant (agents serve multiple tenants)
-- Access control: only the registering service can update its own record (enforced by S2S auth)
```

### R14: Redis Heartbeat Cache

Fast-path health checks bypass PostgreSQL:

```
Key:    agent:{agent_id}:heartbeat
Value:  {"health": "healthy", "load": 3, "queue": 0, "ts": 1717420800}
TTL:    lease_ttl_sec (30s default)
```

Discovery queries check Redis first (sub-ms), fall back to PostgreSQL if Redis is down.

---

## Startup Behavior

### R15: Self-Registration on Startup

Every agent includes registration as a startup step (after health dependencies are verified):

```python
# In service main.py lifespan
@asynccontextmanager
async def lifespan(app: FastAPI):
    # ... existing startup checks ...
    
    # Register with agent registry
    registration = await registry_client.register(
        agent_type=settings.agent_type,
        version=settings.version,
        capabilities=settings.capabilities,
        endpoint=f"http://{settings.hostname}:{settings.port}",
        max_concurrency=settings.max_concurrency,
    )
    app.state.agent_id = registration.agent_id
    app.state.heartbeat_task = asyncio.create_task(
        heartbeat_loop(registration.agent_id, registration.lease_ttl_sec)
    )
    
    yield
    
    # Graceful shutdown: drain + deregister
    await registry_client.heartbeat(app.state.agent_id, health="draining")
    await drain_in_flight_requests(timeout=30)
    await registry_client.deregister(app.state.agent_id)
    app.state.heartbeat_task.cancel()
```

### R16: Startup Without Registry (Degradation)

If memory-service (which hosts the registry) is unavailable at startup:
- Agent still starts and serves requests via direct HTTP (existing behavior)
- Registration retries in background every 10s
- Once registered, agent becomes discoverable
- System functions without registry — it's an enhancement, not a hard dependency

---

## Configuration

```yaml
# Per-service environment variables
AGENT_TYPE: agent-eval                    # Logical agent type
AGENT_VERSION: 1.5.0                      # From image tag / build
AGENT_CAPABILITIES: '["evaluate_control","evaluate_vendor"]'  # JSON list of task names
AGENT_MAX_CONCURRENCY: 10                 # Max parallel requests
REGISTRY_ENABLED: true                    # Can disable for dev/testing
HEARTBEAT_INTERVAL_SEC: 10               # How often to heartbeat
LEASE_TTL_SEC: 30                        # How long before missed heartbeat = unhealthy
```

---

## Security Invariants

### R17: Tenant-Scoped Discovery

All discovery queries MUST include `tenant_id`. The registry never returns agents scoped to a different tenant:

```python
# In discover() implementation:
def filter_agents(agents: list, request_tenant_id: str) -> list:
    return [
        a for a in agents
        if a.tenant_scope is None            # Shared agent (serves all tenants)
        or a.tenant_scope == request_tenant_id  # Dedicated agent for this tenant
    ]
    # An agent with tenant_scope="acme" is NEVER returned for tenant "globex"
```

### R18: JWT Propagation on Inter-Agent Delegation

When the gateway or an agent delegates work to another agent, the original user's security context MUST travel with the request:

```python
# In llm-gateway delegate_to_agent():
async def delegate_to_agent(agent: AgentMatch, request: CompletionRequest):
    """Delegate task to another agent — propagate full security context."""
    headers = {
        "X-Service-Id": "llm-gateway",
        "X-Service-Key": settings.service_key,
        "X-Tenant-Id": request.tenant_id,          # From original JWT
        "X-User-Id": request.user_id,              # From original JWT
        "X-User-Role": request.user_role,           # From original JWT
        "X-Trace-Id": request.trace_id,
        "X-Original-JWT": request.raw_jwt,          # Pass through for MCP calls
    }
    return await httpx_client.post(f"{agent.endpoint}/v1/execute", headers=headers, json=request.body)
```

The receiving agent operates under the **delegator's identity**, not its own. It can never escalate privileges:
- If an admin's agent delegates to agent-eval, the eval runs scoped to the admin's tenant
- If agent-eval then calls MCP tools, it passes the original JWT — MCP enforces that user's permissions
- The receiving agent MUST NOT use its own service credentials to bypass tenant scoping

### R19: No Cross-Tenant Inter-Agent Messaging

Shadow AI agents can only message other agents within the same tenant:

```python
async def send_inter_agent_message(from_session: Session, target_user_id: str, message: dict):
    # MUST verify target user belongs to same tenant
    target_user = await memory.get_user(from_session.tenant_id, target_user_id)
    if not target_user:
        raise AuthorizationError("Cannot message users outside your organization")
    
    # Discovery is already tenant-scoped (R17), but belt-and-suspenders:
    agents = await registry.discover(
        task="receive_notification",
        tenant_id=from_session.tenant_id  # Same tenant only
    )
    ...
```

Even if an admin has full permissions within their tenant, they cannot:
- Discover agents belonging to other tenants
- Send messages to users in other tenants
- Read memory, evidence, or evaluation results from other tenants

### R20: Audit Trail for Inter-Agent Actions

Every delegation and inter-agent message is logged to the append-only audit trail:

```python
AUDITABLE_AGENT_ACTIONS = [
    "agent.delegated_task",         # Gateway delegated task to another agent
    "agent.received_delegation",    # Agent received delegated work
    "agent.sent_message",           # Shadow AI sent inter-agent message
    "agent.received_message",       # Shadow AI received inter-agent message
    "agent.registered",             # Agent registered with registry
    "agent.deregistered",           # Agent deregistered
    "agent.health_changed",         # Health state transition (healthy → degraded, etc.)
]
```

Each audit entry includes: `{from_agent_id, to_agent_id, tenant_id, user_id, action, task, timestamp, trace_id}`

### R21: Agent Identity Verification

Agents authenticate to the registry and to each other using S2S API keys (same mechanism as all internal services). An agent cannot:
- Register with a `tenant_scope` it doesn't own (registry validates against known service keys)
- Send heartbeats for another agent's `agent_id` (agent_id bound to service key at registration)
- Call another agent's endpoint without valid S2S credentials

```python
# Registry registration validates caller identity:
async def register_agent(request: RegisterRequest, service: ServiceIdentity = Depends(verify_service)):
    # Only the declaring service can register its own agents
    if request.agent_type != service.service_id:
        raise HTTPException(403, f"Service {service.service_id} cannot register as {request.agent_type}")
    
    # Tenant-scoped agents: service must have authority for that tenant
    if request.tenant_scope and not await can_serve_tenant(service.service_id, request.tenant_scope):
        raise HTTPException(403, "Service not authorized for this tenant scope")
    ...
```

### Security Model Summary

```
┌───────────────────────────────────────────────────────────────────────┐
│  User (Browser)                                                        │
│  JWT: {sub, tenant_id: "acme", role: "admin", exp}                    │
└───────────────────────┬───────────────────────────────────────────────┘
                        │ JWT
                        ▼
┌───────────────────────────────────────────────────────────────────────┐
│  compliance-assistant                                                  │
│  • Passes JWT through — ZERO permission logic                         │
│  • Uses role for persona only (system prompt, not enforcement)        │
│  • Inter-agent messages: tenant_id from JWT, never from user input    │
└───────────────────────┬───────────────────────────────────────────────┘
                        │ JWT (to MCP) / X-Tenant-Id + S2S key (to services)
                        ▼
┌───────────────────────────────────────────────────────────────────────┐
│  MCP Server / Backend                                                  │
│  • Validates JWT signature + expiry                                    │
│  • Extracts tenant_id + role from claims (not from request body)      │
│  • TOOL_ACCESS matrix: pre-filters tools by role                      │
│  • All DB queries scoped by tenant_id                                 │
└───────────────────────┬───────────────────────────────────────────────┘
                        │ tenant_id in every query
                        ▼
┌───────────────────────────────────────────────────────────────────────┐
│  memory-service / PostgreSQL                                           │
│  • SET app.current_tenant before every query (RLS)                    │
│  • Even application bugs can't leak cross-tenant data                 │
│  • Audit trail: append-only, no UPDATE/DELETE                         │
└───────────────────────────────────────────────────────────────────────┘

Key invariant: tenant_id is ALWAYS extracted from the JWT (issued by Cognito,
signed with RS256). It is NEVER taken from user-supplied request parameters.
An admin of Tenant A has full admin tools — but those tools only see Tenant A's data.
```

---

## Future Extensions

These are NOT in scope for V1 but the design accommodates them:

- **Agent-to-agent RPC**: registry provides endpoints, agents call each other directly (bypass gateway for agent tasks)
- **Capability negotiation**: agents can reject work they've accepted (e.g., "I can evaluate SOC2 but not HIPAA") — constraints field enables this
- **Auto-scaling signals**: registry exposes "all instances of type X are at 80% capacity" → triggers ECS scaling
- **Multi-region**: registry per region, cross-region discovery for DR failover
- **Agent marketplace**: third-party agents register capabilities (e.g., a specialized "PCI-DSS evaluator")
