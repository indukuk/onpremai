# Security, Authentication & Authorization — Low-Level Design

## Overview

This document specifies the security implementation across all modules: identity management, token validation, role-based access, service-to-service auth, multi-tenant isolation, and data protection.

---

## Authentication Architecture

### Layer 1: User Authentication (Cognito → JWT)

```
User → Frontend (SPA) → Cognito User Pool → JWT (Access + ID + Refresh)
                                                    │
                                                    ▼
                      Backend validates JWT on every request
```

**AWS Cognito User Pool Configuration:**

```yaml
UserPool: onpremai-users
  MFA: required (TOTP preferred, SMS fallback)
  PasswordPolicy:
    MinimumLength: 12
    RequireUppercase: true
    RequireLowercase: true
    RequireNumbers: true
    RequireSymbols: true
  TokenExpiry:
    AccessToken: 60 minutes
    IdToken: 60 minutes
    RefreshToken: 30 days
  CustomAttributes:
    - custom:tenant_id (String, mutable by admin only)
    - custom:role (String, mutable by admin only)
  Groups:  # Map to roles
    - admin
    - compliance_manager
    - contributor
    - auditor
    - viewer
  Triggers:
    PreTokenGeneration: Lambda that injects tenant_id + role into token claims
```

**Pre-Token Generation Lambda** (injects custom claims):

```python
def handler(event, context):
    """Inject tenant_id and role into Cognito tokens."""
    user_attributes = event["request"]["userAttributes"]
    
    event["response"]["claimsOverrideDetails"] = {
        "claimsToAddOrOverride": {
            "custom:tenant_id": user_attributes.get("custom:tenant_id", ""),
            "custom:role": user_attributes.get("custom:role", "viewer"),
        }
    }
    return event
```

---

### Layer 2: JWT Validation (Backend / All Services)

Every user-facing endpoint validates the Cognito JWT. This is implemented in `common/auth/`.

**`common/auth/cognito.py`:**

```python
from jose import jwt, JWTError, jwk
from jose.utils import base64url_decode
import httpx
from functools import lru_cache
from dataclasses import dataclass
from datetime import datetime

@dataclass
class UserContext:
    user_id: str
    tenant_id: str
    role: str
    email: str
    groups: list[str]
    token_exp: datetime

class CognitoTokenValidator:
    """Validates Cognito JWTs using JWKS public keys."""
    
    def __init__(self, region: str, user_pool_id: str, client_id: str):
        self._issuer = f"https://cognito-idp.{region}.amazonaws.com/{user_pool_id}"
        self._jwks_url = f"{self._issuer}/.well-known/jwks.json"
        self._client_id = client_id
        self._jwks_cache: dict | None = None
        self._jwks_fetched_at: float = 0
    
    async def validate(self, token: str) -> UserContext:
        """Validate JWT and extract user context. Raises on failure."""
        # 1. Decode header to get key ID (kid)
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get("kid")
        if not kid:
            raise AuthenticationError("Token missing key ID")
        
        # 2. Find matching public key from JWKS
        key = await self._get_signing_key(kid)
        
        # 3. Verify signature, expiry, issuer, audience
        try:
            payload = jwt.decode(
                token,
                key=key,
                algorithms=["RS256"],
                audience=self._client_id,
                issuer=self._issuer,
                options={"verify_exp": True, "verify_iss": True, "verify_aud": True}
            )
        except JWTError as e:
            raise AuthenticationError(f"Token validation failed: {e}")
        
        # 4. Extract user context
        return UserContext(
            user_id=payload["sub"],
            tenant_id=payload.get("custom:tenant_id", ""),
            role=payload.get("custom:role", "viewer"),
            email=payload.get("email", ""),
            groups=payload.get("cognito:groups", []),
            token_exp=datetime.fromtimestamp(payload["exp"]),
        )
    
    async def _get_signing_key(self, kid: str) -> dict:
        """Fetch JWKS and find key by kid. Cached with 1-hour refresh."""
        if not self._jwks_cache or (time.time() - self._jwks_fetched_at > 3600):
            async with httpx.AsyncClient() as client:
                resp = await client.get(self._jwks_url, timeout=5.0)
                resp.raise_for_status()
                self._jwks_cache = resp.json()
                self._jwks_fetched_at = time.time()
        
        for key in self._jwks_cache.get("keys", []):
            if key["kid"] == kid:
                return key
        
        raise AuthenticationError(f"Key {kid} not found in JWKS")


class AuthenticationError(Exception):
    """Raised when JWT validation fails."""
    pass
```

**FastAPI dependency (used by backend + compliance-assistant):**

```python
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBearer

security = HTTPBearer()

async def get_current_user(
    request: Request,
    credentials = Depends(security),
) -> UserContext:
    """FastAPI dependency: validate JWT, return UserContext."""
    validator: CognitoTokenValidator = request.app.state.token_validator
    try:
        user = await validator.validate(credentials.credentials)
    except AuthenticationError as e:
        raise HTTPException(status_code=401, detail=str(e))
    
    if not user.tenant_id:
        raise HTTPException(status_code=403, detail="User has no tenant assignment")
    
    # Attach to request state for downstream use
    request.state.user = user
    return user
```

---

### Layer 3: Service-to-Service Authentication

Internal services authenticate via HMAC-signed API keys. No user JWT is involved.

**`common/auth/service_auth.py`:**

```python
import hmac
import hashlib
import time
from dataclasses import dataclass

@dataclass
class ServiceIdentity:
    service_id: str       # "agent-eval", "compliance-assistant", etc.
    tenant_id: str | None # propagated from user request, if applicable
    trace_id: str | None

class ServiceAuthenticator:
    """Validates service-to-service API keys."""
    
    def __init__(self, valid_keys: dict[str, str]):
        """
        valid_keys: {"agent-eval": "hashed-key-abc", "compliance-assistant": "hashed-key-def"}
        Keys loaded from Secrets Manager at startup.
        """
        self._valid_keys = valid_keys
    
    def validate(self, service_id: str, api_key: str) -> bool:
        """Verify API key for a service using constant-time comparison."""
        expected_hash = self._valid_keys.get(service_id)
        if not expected_hash:
            return False
        
        # HMAC-SHA256 the provided key and compare
        provided_hash = hashlib.sha256(api_key.encode()).hexdigest()
        return hmac.compare_digest(provided_hash, expected_hash)
```

**FastAPI dependency for internal endpoints:**

```python
from fastapi import Header, HTTPException

async def verify_service(
    x_service_id: str = Header(...),
    x_service_key: str = Header(...),
    x_tenant_id: str = Header(None),
    x_trace_id: str = Header(None),
) -> ServiceIdentity:
    """Validate service-to-service call."""
    authenticator: ServiceAuthenticator = app.state.service_auth
    
    if not authenticator.validate(x_service_id, x_service_key):
        raise HTTPException(status_code=403, detail="Invalid service credentials")
    
    return ServiceIdentity(
        service_id=x_service_id,
        tenant_id=x_tenant_id,
        trace_id=x_trace_id,
    )
```

**Key rotation:**
- Keys stored in AWS Secrets Manager with 90-day rotation schedule
- Services read key at startup and cache for lifetime of task
- On rotation: Secrets Manager stores both old and new key (dual-key window of 24h)
- After 24h: old key removed, only new key valid

---

## Authorization (RBAC)

### Role Hierarchy

```
admin > compliance_manager > contributor
                           > auditor (separate branch, not above contributor)
viewer (read-only, lowest)
```

### Role Definitions

| Role | Can Read | Can Write | Can Admin | Scope |
|------|:--------:|:---------:|:---------:|-------|
| admin | All | All | All | Entire tenant |
| compliance_manager | All | Controls, evidence, policies, tasks | Team mgmt (limited) | Assigned frameworks |
| contributor | Own controls | Own controls only | None | Assigned controls |
| auditor | All | Findings, test results | None | Entire tenant (read) |
| viewer | All (summary) | None | None | Entire tenant (read) |

### RBAC Implementation

**`common/auth/rbac.py`:**

```python
from functools import wraps
from fastapi import Depends, HTTPException

def require_role(*allowed_roles: str):
    """Factory for role-based access control dependency."""
    async def _check(user: UserContext = Depends(get_current_user)) -> UserContext:
        if user.role not in allowed_roles:
            raise HTTPException(
                status_code=403,
                detail=f"Role '{user.role}' cannot access this resource. Required: {allowed_roles}"
            )
        return user
    return _check

def require_scope(resource_type: str, resource_id_param: str = None):
    """Check that user has access to this specific resource (not just the role)."""
    async def _check(
        user: UserContext = Depends(get_current_user),
        **kwargs
    ) -> UserContext:
        # Contributors can only access their own controls
        if user.role == "contributor" and resource_type == "control":
            resource_id = kwargs.get(resource_id_param)
            if resource_id and not await is_control_owner(user.user_id, resource_id):
                raise HTTPException(status_code=403, detail="You can only access controls assigned to you")
        return user
    return _check

# Usage in routes:
@app.post("/policies")
async def create_policy(
    policy: PolicyCreate,
    user: UserContext = Depends(require_role("admin", "compliance_manager"))
):
    ...

@app.get("/controls/{control_id}/evidence")
async def get_evidence(
    control_id: str,
    user: UserContext = Depends(require_role("admin", "compliance_manager", "contributor", "auditor"))
):
    # Additional scope check for contributors
    if user.role == "contributor":
        if not await is_control_owner(user.user_id, control_id):
            raise HTTPException(status_code=403, detail="Not your control")
    ...
```

### MCP Tool Access Matrix

The MCP module pre-filters the tool list before returning to compliance-assistant. The assistant never sees tools the user can't call:

```python
TOOL_ACCESS = {
    "admin": {"*"},  # all tools
    "compliance_manager": {
        "evidence.*", "escalation.*", "policy.*", "risk.*",
        "users.list", "users.get_workload", "users.suggest_assignments",
        "audit.get_readiness", "audit.generate_checklist", "controls.*",
    },
    "contributor": {
        "evidence.upload_url", "evidence.bind_to_control", "evidence.check_coverage",
        "escalation.check_overdue", "escalation.get_timeline", "users.get_workload",
    },
    "auditor": {
        "evidence.check_coverage", "evidence.get_stale",
        "audit.*", "risk.list", "risk.get_heatmap_data",
        "policy.list_templates", "policy.get_coverage", "users.list",
    },
    "viewer": {
        "evidence.check_coverage", "escalation.get_timeline",
        "policy.list_templates", "policy.get_coverage",
        "risk.list", "risk.get_heatmap_data",
        "audit.get_readiness", "audit.track_remediation",
    },
}

def filter_tools_for_role(all_tools: list[dict], role: str) -> list[dict]:
    """Return only tools this role can access."""
    allowed = TOOL_ACCESS.get(role, set())
    if "*" in allowed:
        return all_tools
    
    filtered = []
    for tool in all_tools:
        tool_name = tool["name"]
        # Check exact match or prefix match (e.g., "evidence.*")
        if tool_name in allowed or f"{tool_name.split('.')[0]}.*" in allowed:
            filtered.append(tool)
    return filtered
```

---

## Multi-Tenant Data Isolation

### Application Layer (Primary)

Every database query includes `tenant_id` filter. Implemented via repository pattern:

```python
class TenantScopedRepository:
    """Base repository that enforces tenant isolation on all queries."""
    
    def __init__(self, session: AsyncSession, tenant_id: str):
        self._session = session
        self._tenant_id = tenant_id
    
    def _scoped(self, stmt):
        """Add tenant_id filter to any SELECT/UPDATE/DELETE."""
        return stmt.where(self._model.tenant_id == self._tenant_id)
    
    async def get_by_id(self, id: str):
        stmt = select(self._model).where(
            self._model.id == id,
            self._model.tenant_id == self._tenant_id  # ALWAYS included
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()
    
    async def create(self, data: dict):
        """Insert with tenant_id automatically set."""
        data["tenant_id"] = self._tenant_id  # Enforce, never trust caller
        ...
```

### Database Layer (Defense in Depth — PostgreSQL RLS)

Row-Level Security as a second barrier:

```sql
-- Enable RLS on all tenant-scoped tables
ALTER TABLE tenant_memory ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_memory ENABLE ROW LEVEL SECURITY;
ALTER TABLE tasks ENABLE ROW LEVEL SECURITY;
ALTER TABLE eval_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE interactions ENABLE ROW LEVEL SECURITY;

-- Policy: application must SET app.current_tenant before queries
CREATE POLICY tenant_isolation ON tenant_memory
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant', true));

CREATE POLICY tenant_isolation ON user_memory
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant', true));

CREATE POLICY tenant_isolation ON tasks
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant', true));

CREATE POLICY tenant_isolation ON eval_history
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant', true));

-- Patterns table is cross-tenant (no RLS)
-- Audit trail is append-only (separate policy: INSERT only, no UPDATE/DELETE)
CREATE POLICY audit_append_only ON audit_trail
    FOR INSERT
    USING (true);
-- No UPDATE or DELETE policy = those operations are denied by RLS

-- Observer role can read cross-tenant aggregates
CREATE ROLE observer_role;
ALTER TABLE tenant_memory FORCE ROW LEVEL SECURITY;
-- observer_role bypasses RLS for read-only aggregate queries
GRANT SELECT ON ALL TABLES IN SCHEMA public TO observer_role;
ALTER ROLE observer_role BYPASSRLS;  -- only for observer service
```

**Setting tenant context per request:**

```python
class TenantDBMiddleware:
    """Sets PostgreSQL session variable for RLS enforcement."""
    
    async def __call__(self, request: Request, call_next):
        user = request.state.user  # Set by auth middleware
        if user and user.tenant_id:
            async with get_db_session() as session:
                await session.execute(
                    text("SET app.current_tenant = :tid"),
                    {"tid": user.tenant_id}
                )
        response = await call_next(request)
        return response
```

### S3 Isolation

Evidence files are prefixed by tenant_id:

```
s3://compliance-artifacts/{tenant_id}/evidence/...
```

IAM policy on agent-eval task role uses `${aws:PrincipalTag/tenant_id}` for dynamic scoping (or application-layer prefix enforcement via StorageClient).

---

## Rate Limiting

### Per-Tenant Rate Limiting (Redis-backed)

```python
class TenantRateLimiter:
    """Sliding window rate limiter per tenant."""
    
    def __init__(self, redis: Redis, default_rpm: int = 60):
        self._redis = redis
        self._default_rpm = default_rpm
    
    async def check(self, tenant_id: str, endpoint: str) -> tuple[bool, int]:
        """
        Returns (allowed: bool, remaining: int).
        Uses sliding window counter in Redis.
        """
        key = f"ratelimit:{tenant_id}:{endpoint}:{int(time.time()) // 60}"
        
        pipe = self._redis.pipeline()
        pipe.incr(key)
        pipe.expire(key, 120)  # 2-minute TTL (covers current + previous window)
        count, _ = await pipe.execute()
        
        limit = await self._get_tenant_limit(tenant_id)
        remaining = max(0, limit - count)
        
        return (count <= limit, remaining)
    
    async def _get_tenant_limit(self, tenant_id: str) -> int:
        """Look up tenant's rate limit (cached)."""
        cached = await self._redis.get(f"tenant_limit:{tenant_id}")
        if cached:
            return int(cached)
        return self._default_rpm
```

### Rate Limit Tiers

| Tier | Requests/min | Tokens/min | Daily Budget |
|------|:------------:|:----------:|:------------:|
| Free/trial | 20 | 20,000 | $5 |
| Standard | 60 | 100,000 | $50 |
| Enterprise | 200 | 500,000 | $500 |
| Unlimited | 1000 | 2,000,000 | Custom |

---

## Secrets Management

### What Goes in Secrets Manager

| Secret | Used By | Rotation |
|--------|---------|----------|
| `app/db/password` | memory-service, backend | 90 days |
| `app/redis/auth-token` | memory-service, llm-gateway | 90 days |
| `app/llm-gateway/anthropic-key` | llm-gateway | Manual (provider-issued) |
| `app/services/agent-eval-key` | agent-eval (sends), llm-gateway (validates) | 90 days |
| `app/services/assistant-key` | compliance-assistant (sends), backend (validates) | 90 days |
| `app/services/observer-key` | observer (sends), llm-gateway admin (validates) | 90 days |
| `app/pii/hmac-key` | All services (PII hashing in logs) | 365 days |
| `app/cognito/client-secret` | backend (token validation) | Manual |

### How Secrets Reach Services

```
Secrets Manager → ECS Task Definition (secrets field) → Container env var at launch
```

```json
{
  "containerDefinitions": [{
    "secrets": [
      {"name": "DB_PASSWORD", "valueFrom": "arn:aws:secretsmanager:us-east-1:123:secret:app/db/password"},
      {"name": "SERVICE_API_KEY", "valueFrom": "arn:aws:secretsmanager:us-east-1:123:secret:app/services/agent-eval-key"},
      {"name": "PII_HMAC_KEY", "valueFrom": "arn:aws:secretsmanager:us-east-1:123:secret:app/pii/hmac-key"}
    ]
  }]
}
```

Secrets are resolved at task launch — if a secret rotates, new tasks get the new value. Running tasks keep the old value until replaced.

---

## CORS Configuration

```python
from fastapi.middleware.cors import CORSMiddleware

ALLOWED_ORIGINS = [
    f"https://{os.getenv('FRONTEND_DOMAIN')}",  # e.g., https://app.onpremai.com
]

if os.getenv("ENVIRONMENT") == "development":
    ALLOWED_ORIGINS.append("http://localhost:3000")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "X-Trace-Id"],
    expose_headers=["X-Request-Id", "X-RateLimit-Remaining"],
    max_age=600,
)
```

**Rules:**
- Never `allow_origins=["*"]` with `allow_credentials=True`
- Internal service-to-service calls don't go through CORS (same VPC, no browser)
- Only the ALB-facing services (backend, compliance-assistant) need CORS

---

## Audit Trail

Every security-relevant action is logged to the append-only audit trail in memory-service:

```python
AUDITABLE_ACTIONS = [
    "user.login", "user.logout", "user.mfa_challenge",
    "token.validated", "token.expired", "token.rejected",
    "role.changed", "user.invited", "user.removed",
    "tool.called", "tool.confirmed", "tool.denied",
    "evidence.uploaded", "evidence.deleted",
    "policy.created", "policy.approved",
    "evaluation.started", "evaluation.completed",
    "escalation.sent", "escalation.escalated",
    "api_key.generated", "api_key.rotated", "api_key.revoked",
    "budget.exceeded", "budget.warning",
    "observer.change_applied", "observer.change_rolled_back",
]
```

Audit entries are written via the memory-service audit trail API (append-only, no DELETE).

---

## Security Checklist Per Module

| Module | Auth Type | RBAC | Tenant Isolation | PII Logging | Rate Limited |
|--------|-----------|:----:|:----------------:|:-----------:|:------------:|
| **backend (MCP)** | Cognito JWT | Yes (tool matrix) | App + RLS | Audit trail (full) | Per-tenant |
| **compliance-assistant** | Cognito JWT (passed through) | Via MCP pre-filter | Via MCP scoping | Operational (PII-free) | Per-tenant |
| **agent-eval** | S2S API key | N/A (internal) | tenant_id from header | Operational (PII-free) | Via gateway |
| **llm-gateway** | S2S API key | N/A (internal) | Per-tenant budget | Operational (PII-free) | Per-tenant + per-model |
| **memory-service** | S2S API key | N/A (internal) | App + RLS | Audit (full) + Ops (redacted) | Per-tenant |
| **observer** | S2S API key | N/A (internal) | Admin scope (aggregates only) | Operational (PII-free) | Self-budgeted |
| **sandbox-service** | S2S API key | N/A (internal) | Scoped to tenant file prefix | Operational (PII-free) | Concurrency limit |
| **preprocessor** | S2S API key | N/A (internal) | Scoped to tenant file prefix | Operational (PII-free) | Concurrency limit |
