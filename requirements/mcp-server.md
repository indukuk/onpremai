# MCP Module (part of the backend web server)

## Purpose

Exposes the compliance platform's capabilities as a standard MCP (Model Context Protocol) endpoint. NOT a separate service — it's a route on the backend web server that can be enabled/disabled per tenant via feature flag.

The AI assistant is a **feature**, not a core dependency. If a customer disables it, the MCP route returns 404 and everything else continues working.

## Why MCP as a Backend Module (not a separate service)

1. **Same business logic**: MCP tools call the same service layer as the REST API. No duplication.
2. **Feature flag**: AI assistant is toggleable per tenant — a separate container can't be half-running.
3. **Permissions already enforced**: backend already has the auth/permission middleware. MCP route reuses it.
4. **Single deploy**: backend team ships REST API + MCP route together. Tools stay in sync with API automatically.
5. **No extra container**: one fewer thing to operate, version, health-check.

## Architecture

```
┌──────────────┐     ┌──────────────┐     ┌──────────────────┐
│  compliance-assistant  │     │ future-agent │     │  Claude Desktop  │
│ (MCP client) │     │ (MCP client) │     │  (MCP client)    │
└──────┬───────┘     └──────┬───────┘     └────────┬─────────┘
       │                     │                      │
       └─────────────────────┼──────────────────────┘
                             │
              ┌──────────────▼──────────────────────────┐
              │         Backend Web Server               │
              │                                         │
              │  /api/v1/...    ← Frontend REST API     │
              │  /mcp           ← MCP transport (AI)    │
              │                                         │
              │  ┌───────────────────────────────────┐  │
              │  │         Service Layer             │  │
              │  │  (same for REST and MCP)          │  │
              │  │  controls, evidence, policies,    │  │
              │  │  users, risks, audit, workflows   │  │
              │  └───────────────────────────────────┘  │
              │                                         │
              │  Feature flags:                         │
              │    ai_assistant: per-tenant on/off      │
              │    If off: /mcp returns 404             │
              └─────────────────────────────────────────┘
```

## Requirements

### R1: MCP Protocol Compliance

- Implements MCP specification (https://spec.modelcontextprotocol.io/)
- Transport: HTTP + SSE (Streamable HTTP transport, MCP 2025 spec)
- Mounted at `/mcp` on the backend web server
- Supports: `tools/list`, `tools/call`, `resources/list`, `resources/read`, `prompts/list`, `prompts/get`
- Authentication: same JWT middleware as REST API — user context already available
- Permission enforcement: same role-based checks as REST API
- Feature flag: `ai_assistant` per tenant
  - Enabled: `/mcp` responds normally
  - Disabled: `/mcp` returns `404 Not Found` (compliance-assistant gets "service unavailable")
  - Tenant can enable/disable at runtime via admin settings

### R2: Workflow Tools

These are multi-step, guided workflows the assistant uses to help users:

#### Onboarding Workflow
```yaml
tools:
  - onboarding.get_status:
      description: "Get tenant onboarding progress — completed steps, next steps, blockers"
      output: {completed: [...], pending: [...], next_action: "..."}

  - onboarding.setup_company_profile:
      description: "Set company name, industry, size, fiscal year for compliance scoping"
      params: {name, industry, size, fiscal_year_end}

  - onboarding.adopt_framework:
      description: "Adopt a compliance framework — generates all controls and maps evidence requirements"
      params: {framework_id}
      confirmation_required: true

  - onboarding.invite_team:
      description: "Invite team members with appropriate roles for the compliance program"
      params: {users: [{email, role, name}]}
      confirmation_required: true

  - onboarding.connect_integration:
      description: "Connect a third-party tool (Okta, AWS, GitHub, Jira) for automated evidence collection"
      params: {integration_type, config}

  - onboarding.generate_gap_analysis:
      description: "Run initial gap analysis — which controls have evidence, which don't"
      params: {framework_id}
```

#### Evidence Management Workflow
```yaml
tools:
  - evidence.upload_url:
      description: "Get presigned URL to upload evidence file"
      params: {filename, control_id, framework_id}

  - evidence.bind_to_control:
      description: "Link uploaded evidence to a specific control"
      params: {evidence_id, control_id}

  - evidence.check_coverage:
      description: "Check which controls have evidence and which are missing"
      params: {framework_id}
      output: {covered: [...], gaps: [...], stale: [...]}

  - evidence.get_stale:
      description: "List evidence older than retention period that needs refresh"
      params: {framework_id, max_age_days}

  - evidence.request_from_user:
      description: "Create an evidence request assigned to a user with a due date"
      params: {control_id, assignee_email, due_date, description}
      confirmation_required: true

  - evidence.bulk_map:
      description: "Map multiple evidence files to controls based on naming patterns"
      params: {mappings: [{filename_pattern, control_ids}]}
```

#### Escalation Workflow
```yaml
tools:
  - escalation.check_overdue:
      description: "Find controls with overdue evidence — past due date with no upload"
      params: {framework_id}
      output: {overdue: [{control_id, assignee, due_date, days_overdue}]}

  - escalation.send_reminder:
      description: "Send reminder notification to evidence owner about overdue items"
      params: {user_email, control_ids, message}
      confirmation_required: true

  - escalation.escalate_to_manager:
      description: "Escalate overdue evidence to the assignee's manager"
      params: {user_email, control_ids, reason}
      confirmation_required: true

  - escalation.set_due_dates:
      description: "Set or update due dates for evidence collection"
      params: {assignments: [{control_id, assignee, due_date}]}

  - escalation.get_timeline:
      description: "Get audit timeline — days until audit, items remaining, risk level"
      params: {framework_id}
```

#### Policy Workflow
```yaml
tools:
  - policy.list_templates:
      description: "List available policy templates for a framework"
      params: {framework_id}

  - policy.generate_draft:
      description: "Generate a policy draft from template, customized for the tenant"
      params: {template_id, customization: {company_name, industry_specifics}}

  - policy.create:
      description: "Create a new policy document in the system"
      params: {title, content, framework_id, owner, review_date}
      confirmation_required: true

  - policy.request_review:
      description: "Send policy for review/approval to specified approver"
      params: {policy_id, reviewer_email, due_date}
      confirmation_required: true

  - policy.get_coverage:
      description: "Check which controls are covered by policies and which need new ones"
      params: {framework_id}
```

#### Risk Register Workflow
```yaml
tools:
  - risk.list:
      description: "List all risks in the register with scores and owners"
      params: {category?, status?}

  - risk.create:
      description: "Add a new risk to the register"
      params: {title, description, category, likelihood, impact, owner, mitigation}
      confirmation_required: true

  - risk.assess:
      description: "Run risk assessment — suggest risks based on adopted frameworks and evidence gaps"
      params: {framework_id}
      output: {suggested_risks: [{title, category, likelihood, impact, rationale}]}

  - risk.link_to_control:
      description: "Link a risk to the controls that mitigate it"
      params: {risk_id, control_ids}

  - risk.get_heatmap_data:
      description: "Get risk heatmap data (likelihood x impact matrix)"
      params: {}
```

#### User & Access Workflow
```yaml
tools:
  - users.list:
      description: "List all users with roles and assigned controls"

  - users.invite:
      description: "Invite new user with role"
      params: {email, role, name}
      confirmation_required: true

  - users.change_role:
      description: "Change user's role"
      params: {user_id, new_role}
      confirmation_required: true

  - users.get_workload:
      description: "Get user's assigned controls, overdue items, and capacity"
      params: {user_id}

  - users.suggest_assignments:
      description: "Suggest control ownership assignments based on role and workload"
      params: {framework_id}
```

#### Audit Preparation Workflow
```yaml
tools:
  - audit.schedule:
      description: "Schedule audit date and assign auditor"
      params: {framework_id, date, auditor_email}
      confirmation_required: true

  - audit.get_readiness:
      description: "Get audit readiness score — evidence coverage, policy status, open risks"
      params: {framework_id}
      output: {readiness_pct, gaps, blockers, days_until_audit}

  - audit.generate_checklist:
      description: "Generate pre-audit checklist of items to complete"
      params: {framework_id}

  - audit.create_finding:
      description: "Log an audit finding"
      params: {title, severity, control_id, description, remediation}
      confirmation_required: true

  - audit.track_remediation:
      description: "Get status of finding remediation — open, in progress, closed"
      params: {framework_id}
```

### R3: MCP Resources (read-only context)

Resources give agents read access to current state without tool calls:

```yaml
resources:
  - tenant://profile:
      description: "Company profile — name, industry, size, frameworks adopted"
      
  - tenant://frameworks/{framework_id}/status:
      description: "Framework readiness — percentage complete, controls by status"

  - tenant://controls/{framework_id}:
      description: "All controls with status, owner, last evidence date"

  - tenant://evidence/gaps:
      description: "Current evidence gaps across all frameworks"

  - tenant://audit/timeline:
      description: "Upcoming audit dates and preparation status"

  - tenant://risks/summary:
      description: "Risk register summary — total risks by category and severity"

  - tenant://users/roster:
      description: "Team members, roles, and workload"

  - tenant://activity/recent:
      description: "Recent platform activity — uploads, evaluations, changes"
```

Agents read resources to understand current state BEFORE deciding which tools to call. This replaces the compliance-assistant pattern of calling `frameworks.list` + `controls.list` + `evidence.list_gaps` just to build context.

### R4: MCP Prompts (workflow guidance)

Prompts are pre-built instruction templates the agent can request for multi-step workflows:

```yaml
prompts:
  - onboarding/new_tenant:
      description: "Guide a new tenant through initial setup"
      arguments: [{name: "company_name", required: true}]
      # Returns system prompt with step-by-step onboarding instructions

  - workflow/evidence_collection:
      description: "Guide user through uploading and mapping evidence for a control"
      arguments: [{name: "framework_id"}, {name: "control_id"}]

  - workflow/policy_creation:
      description: "Guide user through creating a compliance policy"
      arguments: [{name: "framework_id"}, {name: "policy_type"}]

  - workflow/risk_assessment:
      description: "Guide user through identifying and scoring risks"
      arguments: [{name: "framework_id"}]

  - workflow/audit_prep:
      description: "Guide user through preparing for an upcoming audit"
      arguments: [{name: "framework_id"}, {name: "audit_date"}]

  - escalation/overdue_evidence:
      description: "Handle overdue evidence — check status, remind, escalate"
      arguments: [{name: "framework_id"}]
```

### R5: Role-Based Access Control

Every `tools/call` and `resources/read` is checked against the user's role. The agent only sees tools the user is allowed to call — `tools/list` is pre-filtered.

#### Roles

| Role | Description | Typical user |
|------|-------------|--------------|
| `admin` | Full platform access, manages team and settings | CISO, Head of Compliance |
| `compliance_manager` | Manages controls, evidence, policies for assigned scope | Compliance lead, GRC analyst |
| `contributor` | Uploads evidence, completes assigned tasks | Engineering lead, IT admin |
| `auditor` | Read-only + audit-specific tools (findings, testing, reviews) | External/internal auditor |
| `viewer` | Read-only access, no mutations | Executive, board member |

#### Tool Access Matrix

| Tool | admin | compliance_manager | contributor | auditor | viewer |
|------|:-----:|:------------------:|:-----------:|:-------:|:------:|
| **Onboarding** | | | | | |
| onboarding.get_status | Yes | Yes | — | — | — |
| onboarding.setup_company_profile | Yes | — | — | — | — |
| onboarding.adopt_framework | Yes | — | — | — | — |
| onboarding.invite_team | Yes | — | — | — | — |
| onboarding.connect_integration | Yes | — | — | — | — |
| onboarding.generate_gap_analysis | Yes | Yes | — | — | — |
| **Evidence** | | | | | |
| evidence.upload_url | Yes | Yes | Own controls | — | — |
| evidence.bind_to_control | Yes | Yes | Own controls | — | — |
| evidence.check_coverage | Yes | Yes | Own scope | Yes | Yes |
| evidence.get_stale | Yes | Yes | — | Yes | — |
| evidence.request_from_user | Yes | Yes | — | Yes | — |
| evidence.bulk_map | Yes | Yes | — | — | — |
| **Escalation** | | | | | |
| escalation.check_overdue | Yes | Yes | Own tasks | Yes | — |
| escalation.send_reminder | Yes | Yes | — | — | — |
| escalation.escalate_to_manager | Yes | — | — | — | — |
| escalation.set_due_dates | Yes | Yes | — | — | — |
| escalation.get_timeline | Yes | Yes | Yes | Yes | Yes |
| **Policy** | | | | | |
| policy.list_templates | Yes | Yes | — | Yes | Yes |
| policy.generate_draft | Yes | Yes | — | — | — |
| policy.create | Yes | Yes | — | — | — |
| policy.request_review | Yes | Yes | — | — | — |
| policy.get_coverage | Yes | Yes | — | Yes | Yes |
| **Risk** | | | | | |
| risk.list | Yes | Yes | — | Yes | Yes |
| risk.create | Yes | Yes | — | — | — |
| risk.assess | Yes | Yes | — | — | — |
| risk.link_to_control | Yes | Yes | — | — | — |
| risk.get_heatmap_data | Yes | Yes | — | Yes | Yes |
| **Users** | | | | | |
| users.list | Yes | Yes | — | Yes | — |
| users.invite | Yes | — | — | — | — |
| users.change_role | Yes | — | — | — | — |
| users.get_workload | Yes | Yes | Own | — | — |
| users.suggest_assignments | Yes | Yes | — | — | — |
| **Audit** | | | | | |
| audit.schedule | Yes | — | — | — | — |
| audit.get_readiness | Yes | Yes | — | Yes | Yes |
| audit.generate_checklist | Yes | Yes | — | Yes | — |
| audit.create_finding | Yes | — | — | Yes | — |
| audit.track_remediation | Yes | Yes | — | Yes | Yes |

**"Own controls" / "Own scope" / "Own tasks"** = contributor can only act on controls explicitly assigned to them. MCP server checks `control.owner_id == user_id`.

#### Scoped Access Rules

1. **Contributor scope**: can upload/bind evidence only for controls where `owner_id = user_id`
2. **Compliance manager scope**: can manage controls/evidence/policies within their assigned framework(s)
3. **Auditor read scope**: can read everything, but can only write audit-specific data (findings, test results, evidence reviews)
4. **Cross-tenant isolation**: no role can access another tenant's data, period

#### Auth is the MCP Module's Responsibility

The MCP module owns the full auth flow for AI interactions. Agent-chat passes the raw JWT — MCP validates, extracts claims, enforces permissions. Agent-chat never interprets tokens or checks roles itself.

```python
# MCP module handles everything
def mcp_handler(request):
    # 1. AUTHENTICATE: validate JWT, extract user identity
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = validate_and_decode_jwt(token)
    # user = {user_id, tenant_id, role, email, name, assigned_controls, assigned_frameworks}
    
    if not user:
        return mcp_error("UNAUTHORIZED", "Invalid or expired token")
    
    # 2. FEATURE CHECK: is AI assistant enabled for this tenant?
    if not is_feature_enabled(user.tenant_id, "ai_assistant"):
        return mcp_error("FEATURE_DISABLED", "AI assistant is not enabled")
    
    # 3. ROUTE to tools/list, tools/call, resources/read etc.
    ...

def mcp_tools_call(request, user):
    tool = request.tool_name
    params = request.params

    # 4. AUTHORIZE: does this role have access to this tool?
    if not role_can_access(user.role, tool):
        return mcp_error("PERMISSION_DENIED", "Your role cannot use this tool")

    # 5. SCOPE CHECK: is user acting within their scope?
    if requires_ownership(tool):
        resource_owner = get_resource_owner(tool, params)
        if user.role in ("contributor",) and resource_owner != user.user_id:
            return mcp_error("SCOPE_DENIED", "You can only manage controls assigned to you")

    if requires_framework_scope(tool):
        if user.role == "compliance_manager":
            framework = params.get("framework_id")
            if framework not in user.assigned_frameworks:
                return mcp_error("SCOPE_DENIED", "You don't have access to this framework")

    # 6. EXECUTE
    return execute_tool(tool, params, user)
```

**What compliance-assistant does NOT do:**
- Does NOT validate JWTs
- Does NOT check roles or permissions
- Does NOT maintain a permission matrix
- Does NOT decide what tools are available based on role

**What compliance-assistant DOES do:**
- Passes user's JWT to MCP on every call
- Receives pre-filtered tool list from MCP (only tools user can access)
- Handles MCP error responses gracefully (shows user-friendly message)
- Includes role context in LLM system prompt (for natural conversation, not for enforcement)

#### What Agent-Chat Sees Per Role

When a **viewer** connects:
```json
// tools/list returns ~10 tools (all read-only)
["evidence.check_coverage", "escalation.get_timeline", "policy.list_templates", 
 "policy.get_coverage", "risk.list", "risk.get_heatmap_data", "audit.get_readiness", 
 "audit.track_remediation"]
```

When a **contributor** connects:
```json
// tools/list returns ~15 tools (read + upload/bind for own controls)
["evidence.upload_url", "evidence.bind_to_control", "evidence.check_coverage",
 "escalation.check_overdue", "escalation.get_timeline", "users.get_workload", ...]
```

When an **admin** connects:
```json
// tools/list returns all ~40 tools
[...]
```

The LLM only sees tools the user can actually use. No "permission denied" surprises mid-conversation — the tool simply doesn't exist in the LLM's tool list if the user can't call it.

#### Agent System Prompt Adapts to Role

Agent-chat's system prompt includes the user's role context:

```
You are a compliance assistant helping {user.name} ({user.role}).

Your capabilities for this user:
- {role_description}
- You can use: {tool_names}
- You CANNOT: {restrictions}

If the user asks for something outside their access, explain what role/permission they need and suggest they contact their admin.
```

This prevents the agent from even *attempting* to call tools the user can't use.

### R6: Confirmation for Destructive Actions

- Tools marked `confirmation_required: true` return a pending state:
  ```json
  {
    "status": "confirmation_required",
    "action": "users.invite",
    "summary": "Invite john@acme.com as compliance_manager",
    "params": {...}
  }
  ```
- Agent shows user the summary, asks for confirmation
- On confirm: agent calls `tools/call` again with `confirmed: true`
- On cancel: agent acknowledges, no action taken
- MCP server enforces: first call without `confirmed` → returns pending. Second call with `confirmed: true` → executes.

### R7: Tool Discovery (Dynamic)

- `tools/list` returns all tools the current user's role can access
- Viewer gets ~15 read-only tools. Admin gets ~40+ tools.
- Tools can be added by:
  - Adding to the MCP server code (new tool handler) → requires redeploy
  - Loading from config file (for simple CRUD tools) → hot-reload
  - Loading from memory service skills (observer can register new tools) → dynamic
- Agent-chat calls `tools/list` on startup and periodically to discover new tools

### R8: Deployment (Part of Backend, Not Separate Container)

- NOT a separate container — it's a module/route within the backend web server
- No separate version tag — ships with backend version
- No additional port — same port as REST API
- Endpoint: `https://backend:8080/mcp`
- Feature flag in tenant settings table:
  ```sql
  ALTER TABLE tenant_settings ADD COLUMN ai_assistant_enabled BOOLEAN DEFAULT false;
  ```
- Backend middleware checks flag on every `/mcp` request

### R9: Configuration

```yaml
# Backend env vars (already existing) — MCP module adds:
MCP_ENABLED: true                           # global kill switch (ops-level)
NOTIFICATION_WEBHOOK: ${NOTIFY_URL}         # for escalation notifications
TOOLS_CONFIG_PATH: /app/config/tools.yaml   # hot-reloadable tool definitions (optional overrides)
```

No separate database, no separate credentials. MCP module uses the backend's existing DB connection, auth middleware, and service layer.

### R10: How compliance-assistant Uses It

```python
# In compliance-assistant, tool discovery at startup (or per-session if tools change):
mcp_tools = mcp_client.list_tools(token=user_jwt)  # filtered by role + feature flag

# If feature disabled for this tenant:
# → MCP returns 404 → compliance-assistant tells user "AI assistant is not enabled for your organization"

# During conversation:
# 1. Agent reads resources for context
tenant_state = mcp_client.read_resource("tenant://frameworks/soc2/status", token=user_jwt)

# 2. Agent decides which tool to call (via LLM)
result = mcp_client.call_tool("evidence.check_coverage", {"framework_id": "soc2"}, token=user_jwt)

# 3. If confirmation needed:
if result.get("status") == "confirmation_required":
    # Show user and wait for confirm/cancel
    ...
```

### R10b: Graceful Degradation When Feature Disabled

- compliance-assistant MUST handle MCP being unavailable (404, connection refused)
- If MCP is off for a tenant:
  - Chat still works (LLM can answer compliance questions from knowledge)
  - Tools/workflows are unavailable — agent tells user "This feature is not enabled"
  - No crash, no error page — graceful message

### R11: Relationship to Existing Code

Current `src/agent_chat/mcp_server.py` has 25 tools as Python functions. Migration:

| Current | Becomes |
|---------|---------|
| `mcp_server.py` functions | MCP server tool handlers |
| `permissions.py` matrix | MCP server permission check |
| `approval.py` confirmation | MCP `confirmation_required` pattern |
| Hardcoded tool list | Dynamic discovery via `tools/list` |
| HTTP calls to backend | Direct DB/storage access (MCP server IS the backend tool layer) |

New tools added (not in current code):
- Onboarding workflow (get_status, setup steps)
- Escalation workflow (overdue detection, reminders, escalation)
- Policy generation (templates, drafts)
- Risk assessment (AI-suggested risks from gaps)
- Audit readiness (score, checklist)
- Workload management (assignments, capacity)
