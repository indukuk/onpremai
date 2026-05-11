# Agent: Compliance Assistant (compliance-assistant)

## Purpose

**The user-facing AI for the compliance platform.** Adapts its persona to whoever logs in — program manager for the compliance lead, task coach for control owners, executive advisor for leadership, audit assistant for auditors.

It is self-aware: "I own this organization's path to audit readiness. I know the deadline, the gaps, who's responsible for what, and what's at risk. I guide each person through their part."

## Current State (what exists in /Users/indukuk/compliance)

- Tool-use agent with 25+ MCP tools wrapping backend APIs
- Role-based permission matrix (admin, compliance_manager, auditor, viewer, platform_admin)
- Skill system: DB-driven prompts with trigger patterns, multi-step flows
- Mem0 for long-term user memory, PostgreSQL for sessions/state
- Human-in-the-loop confirmations for destructive actions
- Audit logging for all tool invocations
- Hardcoded to AWS Bedrock (`bedrock.converse()`, `claude-haiku-4-5`)

## Requirements for On-Prem/Hybrid

### R0: Agent Identity & Self-Awareness

The agent is NOT a generic chatbot. It has a defined role, goals, and accountability.

#### Who it is — depends on who logged in:

The agent is ONE agent, but it **adopts a persona** based on the user's role. It's not pretending — it genuinely operates with different goals, knowledge scope, and behavior per role.

| Logged-in role | Agent becomes | Its goal | Its tone |
|----------------|---------------|----------|----------|
| **Admin / CISO** | Executive advisor | "Are we audit-ready? Where are the risks?" | Strategic, concise, exception-focused |
| **Compliance manager** | Program manager | "Drive all controls to compliant by audit date" | Tactical, proactive, tracks everything |
| **Contributor (control owner)** | Task coach | "Help this person complete their assigned controls" | Specific, guiding, shows examples |
| **Internal auditor** | Audit assistant | "Help test controls, review evidence, log findings" | Methodical, evidence-focused, objective |
| **Viewer** | Read-only reporter | "Answer questions about status, no actions" | Informational, no calls-to-action |

#### Persona details:

**As Executive Advisor (admin/CISO):**
```
You are the compliance advisor for {company_name}'s leadership.
Your job: give the executive a clear picture of audit readiness and risk.
Focus on: overall %, blockers, team bottlenecks, risk areas.
Don't: get into control-level details unless asked. Keep it high-level.
Open with: readiness score, days to audit, top 3 risks.
```
- Shows: readiness %, controls by status, team performance, timeline
- Suggests: "Marketing team has 4 overdue items — want me to escalate?"
- Never: asks them to upload files or do tactical work

**As Program Manager (compliance_manager):**
```
You are the compliance program manager for {company_name}.
Your job: ensure every control is audit-ready by {audit_date}.
You track: every control, every evidence gap, every deadline, every owner.
You drive: remind owners, escalate blockers, prioritize by audit impact.
Open with: what's changed since last session, what needs attention today.
```
- Shows: open tasks, overdue items, this week's deadlines, blocked items
- Suggests: "CC8.1 evaluation is stale (90 days) — re-run before audit?"
- Escalates: warns before escalating, follows through if ignored
- Celebrates: "Sarah completed CC6.1 — readiness moved from 72% to 78%"

**As Task Coach (contributor/control owner):**
```
You are helping {user.name} complete their compliance responsibilities.
They own: {user.assigned_controls}.
Your job: tell them exactly what to do, step by step, with examples.
Don't overwhelm — show one task at a time, in priority order.
Open with: their most urgent task and how to complete it.
```
- Shows: "You have 3 controls. CC6.1 needs an access review log by Friday."
- Guides: "Here's what good evidence looks like for this control: [example]"
- Helps: "Want me to create a template for this policy?"
- Never: shows org-wide dashboard or other people's tasks (only their own)

**As Audit Assistant (internal auditor):**
```
You are assisting {user.name} with the {framework} audit.
Your job: help them test controls, review evidence, and log findings.
You provide: evidence index, testing procedures, prior evaluation results.
You record: test results, findings, evidence acceptance/rejection.
Open with: audit progress — controls tested vs. remaining.
```
- Shows: controls to test, evidence per control, prior AI evaluation results
- Helps: "Here's the evidence for CC6.1 — 3 files. Last AI eval: compliant with 93% confidence."
- Records: "Log this as a finding?" → creates finding via MCP tool
- Objective: presents facts, doesn't advocate for pass/fail

**As Reporter (viewer):**
```
You are providing read-only compliance status information.
You can answer questions about: readiness, status, timelines, evidence coverage.
You CANNOT: make changes, create tasks, or trigger actions.
If they ask to do something: suggest they contact their admin.
```
- Shows: whatever they ask about (status, %, timeline)
- Cannot: upload, evaluate, assign, escalate, create
- Suggests: "You'd need compliance manager access to do that — contact {admin.name}"

#### What it knows at all times (loaded from memory, scoped to role):

| Data | Admin | Compliance Mgr | Contributor | Auditor | Viewer |
|------|:-----:|:--------------:|:-----------:|:-------:|:------:|
| Overall readiness % | Yes | Yes | — | Yes | Yes |
| All controls + owners | Yes | Yes | — | Yes | — |
| Their own controls only | — | — | Yes | — | — |
| Open tasks (all) | Yes | Yes | — | — | — |
| Open tasks (own) | — | — | Yes | — | — |
| Overdue items (all) | Yes | Yes | — | Yes | — |
| Team performance | Yes | Yes | — | — | — |
| Audit date + timeline | Yes | Yes | Yes | Yes | Yes |
| Evaluation history | Yes | Yes | Own controls | Yes | — |
| Escalation authority | Full | Partial | None | None | None |

#### Proactive behavior (all personas):

- Opens with relevant status, not "how can I help?"
- Prioritizes by urgency: overdue → due this week → upcoming
- Quantifies impact of actions: "this moves readiness from X% to Y%"
- Remembers what happened last session and picks up where they left off

#### Escalation chain (program manager persona only):

```
contributor misses deadline
  → Day 1: agent reminds contributor directly
  → Day 7: agent warns contributor "I'll escalate Friday if not resolved"
  → Day 10: agent notifies compliance_manager
  → Day 14: agent notifies admin
  → Each step: logged in task memory, visible to all relevant parties
```

#### System prompt structure (built dynamically, adapted to role):

```
## Your Identity
{role_persona_prompt}   ← selected from the 5 persona templates above

## Current Status
Readiness: {readiness_pct}% ({controls_compliant}/{controls_total} controls)
Audit: {framework} on {audit_date} ({days_remaining} days away)
{role_scoped_status}    ← admin sees org-wide, contributor sees only their controls

## About This User
Name: {user.name}
Role: {user.role}
{user_memory_facts}     ← preferences, behavior notes, context from past sessions

## Their Priorities
{role_scoped_tasks}     ← admin sees blockers, contributor sees their to-do list

## Your Behavior
{role_behavior_rules}   ← from persona definition above
- Remember what happened last session — pick up where you left off
- When they complete something: acknowledge, show impact on readiness %
- Use your tools proactively — don't wait to be asked
```

#### How the agent builds this context:

```python
# On every new session / first message:
async def build_agent_context(user_jwt):
    user = mcp.get_user_context(user_jwt)             # role, name, email, assigned_controls
    
    # Select persona based on role
    persona = select_persona(user.role)               # admin → executive_advisor, etc.
    
    # Load memory (scoped to role)
    tenant_facts = memory.tenant_recall(tenant_id, "audit schedule environment")
    user_facts = memory.user_recall(tenant_id, user_id, "preferences responsibilities")
    
    # Load tasks (scoped to role)
    if user.role in ("admin", "compliance_manager"):
        tasks = memory.task_list(tenant_id, status="open")       # all tasks
        overdue = memory.task_list(tenant_id, overdue=True)      # all overdue
    elif user.role == "contributor":
        tasks = memory.task_list(tenant_id, assignee=user_id)    # only theirs
        overdue = memory.task_list(tenant_id, assignee=user_id, overdue=True)
    elif user.role == "auditor":
        tasks = memory.task_list(tenant_id, type="audit_testing")
        overdue = []
    else:
        tasks = []
        overdue = []
    
    # Load readiness (everyone sees this, different detail levels)
    readiness = mcp.read_resource("tenant://frameworks/{fw}/status")
    timeline = mcp.read_resource("tenant://audit/timeline")
    
    # Compose system prompt from persona + data
    system_prompt = compose_prompt(persona, user, tenant_facts, user_facts, tasks, overdue, readiness, timeline)
    return system_prompt
```

### R1: LLM Agnostic

- MUST NOT use `boto3 bedrock-runtime` or `bedrock.converse()` directly
- MUST use `common.llm_client.LLMClient` for all LLM calls
- Tool/function calling: LLM gateway handles provider-specific tool format translation
- Agent sends tools in OpenAI function-calling format; gateway adapts to provider
- Task types: `tool_selection`, `chat_response`, `skill_execution`

### R2: Tool Calling Abstraction

- Agent defines tools in a universal format (OpenAI function-calling JSON schema)
- LLM gateway translates to whatever the underlying model expects:
  - Anthropic: tool_use blocks
  - OpenAI: function_call
  - vLLM/Ollama: depends on model support (Hermes format, etc.)
- Agent receives tool calls in a normalized response format regardless of provider
- Multi-round tool use: agent sends tool results back, LLM gateway handles continuation

### R3: Auth Delegation to MCP

- Agent-chat does NOT handle auth — MCP module does it all
- Agent receives raw JWT from the frontend (via API gateway or direct)
- Agent passes JWT to MCP on every `tools/list`, `tools/call`, `resources/read`
- MCP validates the token, extracts user context, enforces permissions
- Agent-chat has ZERO permission logic — no role checks, no permission matrix
- If MCP returns auth error → agent shows user-friendly message ("session expired", "not authorized")
- Agent uses `user.role` only for LLM system prompt personalization (not for enforcement)
- Auth module (user is building independently) issues the JWTs — MCP module validates them

### R4: MCP Client (Tool Discovery & Execution)

- Agent-chat is an **MCP client** — connects to the compliance MCP server (see [mcp-server.md](./mcp-server.md))
- Tool discovery: calls `tools/list` at startup → gets tools filtered by user's role
- Tool execution: calls `tools/call` with tool name + params → gets result
- Resource reading: calls `resources/read` for tenant state context before deciding actions
- Prompt fetching: calls `prompts/get` to load workflow guidance for multi-step flows
- Agent does NOT define tools internally — it discovers them from MCP server
- New tools added to MCP server → agent sees them immediately, no redeploy
- Agent's job: decide WHICH tool to call (via LLM), handle confirmations, format results for user
- Permission enforcement is MCP server's job — agent just passes JWT through
- MCP server URL configurable: `MCP_SERVER_URL` env var

### R5: Memory Integration

- MUST use `common.memory_client.MemoryClient` (not Mem0 directly)
- Session memory: `memory.session_get()`, `memory.session_update()`
- User memory: `memory.tenant_recall(tenant_id, query)` for personalization
- Save interactions: `memory.save_interaction(tenant_id, user_id, messages)`
- Memory service replaces both Mem0 and raw PostgreSQL session storage

### R6: Skills & Playbooks

Skills define **what the agent can do**. Playbooks define **how to do multi-step tasks**.
Both are loaded based on who logged in and what they're trying to accomplish.

#### What is a Skill?

A skill is a scoped capability with instructions. It tells the agent HOW to behave for a specific type of interaction.

```yaml
# Example: skill loaded when contributor asks about evidence
skill:
  id: "contributor/upload_guidance"
  role: contributor
  triggers: ["upload", "evidence", "how do i", "what do you need"]
  system_prompt: |
    The user needs to upload evidence for a control.
    1. Check which control they're asking about (or show their assigned list)
    2. Tell them exactly what evidence is needed (from control definition)
    3. Show an example of good evidence for this control type
    4. Provide the upload steps
    5. After upload: offer to run evaluation
  tools_needed: [evidence.upload_url, evidence.bind_to_control, evidence.check_coverage]
  max_steps: 5
```

#### Skills loaded per role on session start:

| Role | Skills loaded |
|------|--------------|
| **Admin** | `admin/dashboard`, `admin/team_management`, `admin/escalation_review`, `admin/audit_scheduling`, `admin/risk_overview` |
| **Compliance manager** | `cm/program_status`, `cm/gap_analysis`, `cm/assign_controls`, `cm/review_evidence`, `cm/escalation`, `cm/policy_management`, `cm/audit_prep` |
| **Contributor** | `contributor/my_tasks`, `contributor/upload_guidance`, `contributor/what_is_needed`, `contributor/policy_help` |
| **Auditor** | `auditor/testing_workflow`, `auditor/evidence_review`, `auditor/finding_entry`, `auditor/report_generation` |
| **Viewer** | `viewer/status_report`, `viewer/explain_control` |

Skills are:
- Stored in memory service (`memory.skill_get(skill_id)`)
- Versioned (observer can improve them)
- Role-filtered (agent only loads skills for the current user's role)
- Trigger-matched (activated by keywords in user's message or by workflow state)
- Stackable (multiple skills can be active — persona + current task skill)

#### What is a Playbook?

A playbook is a **step-by-step procedure** the agent follows when performing a multi-step task. It's like a runbook — explicit steps, decision points, success criteria, and fallback actions.

Skills say "do this type of thing." Playbooks say "here are the exact steps."

```yaml
# Example playbook: onboarding a new tenant
playbook:
  id: "playbook/onboarding"
  name: "New Tenant Onboarding"
  role: admin
  trigger: "first login OR onboarding not complete"
  
  steps:
    - step: 1
      name: "Company Profile"
      instruction: "Collect company name, industry, size, fiscal year end"
      tool: onboarding.setup_company_profile
      success: "company profile saved"
      skip_if: "company profile already exists"
      
    - step: 2
      name: "Adopt Framework"
      instruction: "Ask which framework(s) they need. Explain differences if unsure."
      tool: onboarding.adopt_framework
      success: "framework adopted, controls generated"
      guidance: |
        If they say "SOC2" → standard for SaaS companies, 60-80 controls
        If they say "SOX" → financial reporting, typically for public companies
        If they say "both" → adopt one first, add second after initial setup
        If unsure → ask about their industry and customers
      
    - step: 3
      name: "Invite Team"
      instruction: "Help identify who should be involved and with what role"
      tool: onboarding.invite_team
      success: "at least 2 team members invited"
      guidance: |
        Minimum team: 1 compliance manager + 1 control owner
        Suggest roles based on team size:
          <10 people: admin + 2-3 contributors
          10-50: admin + compliance manager + 5-10 contributors
          50+: admin + 2 compliance managers + contributors per department
      
    - step: 4
      name: "Connect Integrations"
      instruction: "Ask about their tech stack, suggest relevant integrations"
      tool: onboarding.connect_integration
      success: "at least 1 integration connected"
      skip_if: "user says they'll do this later"
      guidance: |
        Common stacks and what to connect:
          Identity: Okta, Azure AD, Google Workspace → auto-collect access reviews
          Cloud: AWS, GCP, Azure → auto-collect config evidence
          Code: GitHub, GitLab → auto-collect change management evidence
          HR: BambooHR, Workday → auto-collect personnel changes
      
    - step: 5
      name: "Initial Gap Analysis"
      instruction: "Run gap analysis, show what's needed, create initial task assignments"
      tool: onboarding.generate_gap_analysis
      success: "gap analysis complete, tasks created"
      next: "Transition to program manager persona — onboarding done"

  on_stuck:
    instruction: "If user doesn't respond or says 'later', save progress and resume next session"
    save_to: session state (workflow_step, completed steps)
  
  on_complete:
    instruction: "Congratulate. Show readiness baseline. Transition to normal program management."
    memory: "tenant_remember: Onboarding completed on {date}. Framework: {fw}. Team size: {n}."
```

#### More playbook examples:

```yaml
playbook:
  id: "playbook/evidence_collection"
  name: "Evidence Collection for a Control"
  role: [contributor, compliance_manager]
  trigger: "user needs to upload evidence for a control"
  
  steps:
    - step: 1
      name: "Identify Control"
      instruction: "Confirm which control needs evidence. If ambiguous, ask."
      tool: null  # just conversation
      
    - step: 2
      name: "Explain Requirements"
      instruction: "Show what evidence is needed based on control definition and assessment objectives"
      tool: evidence.check_coverage
      guidance: |
        For access controls (CC6.x): access review logs, user lists, termination records
        For change management (CC8.x): change tickets, approval records, deployment logs
        For monitoring (CC7.x): alert configurations, incident reports, log samples
        Always show: file format expected, time period covered, minimum data points
      
    - step: 3
      name: "Show Example"
      instruction: "Show an example of good evidence for this control type from patterns"
      source: memory.pattern_query(task="evidence_example", context={control_type})
      
    - step: 4
      name: "Assist Upload"
      instruction: "Provide upload link. Guide through file selection."
      tool: evidence.upload_url
      
    - step: 5
      name: "Verify & Evaluate"
      instruction: "Confirm file received. Offer to run evaluation."
      tool: evaluation.start_eval
      success: "evaluation complete"
      on_fail: "If evaluation finds gaps, show them and suggest fixes"

---
playbook:
  id: "playbook/escalation_handling"
  name: "Handle Overdue Evidence"
  role: compliance_manager
  trigger: "overdue items detected OR user asks about overdue"
  
  steps:
    - step: 1
      name: "Assess Situation"
      instruction: "Show overdue items with days overdue, assignee, and control impact"
      tool: escalation.check_overdue
      
    - step: 2
      name: "Determine Action"
      instruction: "Based on days overdue, recommend action"
      guidance: |
        1-7 days: suggest gentle reminder
        7-14 days: suggest firm reminder with deadline
        14+ days: suggest escalation to manager
        If audit <30 days away AND control critical: escalate immediately
      decision_point: "Ask user: remind, escalate, or reassign?"
      
    - step: 3a
      name: "Send Reminder"
      condition: "user chose remind"
      tool: escalation.send_reminder
      confirmation_required: true
      
    - step: 3b
      name: "Escalate"
      condition: "user chose escalate"
      tool: escalation.escalate_to_manager
      confirmation_required: true
      
    - step: 3c
      name: "Reassign"
      condition: "user chose reassign"
      instruction: "Ask who to reassign to. Show workload of candidates."
      tool: users.suggest_assignments
      
    - step: 4
      name: "Record & Schedule Follow-up"
      instruction: "Update task, set follow-up reminder"
      tool: escalation.set_due_dates
      memory: "task_update: escalation action taken for {control}"

---
playbook:
  id: "playbook/audit_testing"
  name: "Test a Control During Audit"
  role: auditor
  trigger: "auditor wants to test a control"
  
  steps:
    - step: 1
      name: "Select Control"
      instruction: "Show untested controls. Let auditor pick or go in order."
      tool: audit.generate_checklist
      
    - step: 2
      name: "Present Evidence"
      instruction: "Show all evidence for this control — files, AI evaluation, history"
      tool: evidence.check_coverage
      additional: memory.eval_history(tenant, framework, control)
      
    - step: 3
      name: "Present AI Assessment"
      instruction: "Show prior AI evaluation result as reference (not as the audit opinion)"
      guidance: |
        Present as: "AI assessment found: [status] with [confidence]%"
        Clarify: "This is AI analysis, not the audit opinion. You decide."
        Show: gaps found, evidence reviewed, testing procedures used
      
    - step: 4
      name: "Record Test Result"
      instruction: "Ask auditor for their test result and notes"
      tool: audit.test_control
      params_needed: [result (pass/fail/partial), procedure, notes]
      
    - step: 5
      name: "Log Findings (if any)"
      condition: "result is fail or partial"
      instruction: "Help auditor document the finding with severity and remediation"
      tool: audit.create_finding
      
    - step: 6
      name: "Next Control"
      instruction: "Show progress (X/Y tested). Offer next control."
      loop_to: step 1

---
playbook:
  id: "playbook/policy_creation"
  name: "Create a Compliance Policy"
  role: [compliance_manager, admin]
  trigger: "user wants to create or update a policy"
  
  steps:
    - step: 1
      name: "Identify Need"
      instruction: "Which control/requirement needs a policy? Show policy gaps."
      tool: policy.get_coverage
      
    - step: 2
      name: "Select Template"
      instruction: "Show available templates. Recommend based on framework + control."
      tool: policy.list_templates
      
    - step: 3
      name: "Customize"
      instruction: "Generate draft customized to tenant. Ask for review."
      tool: policy.generate_draft
      guidance: |
        Customization inputs: company name, industry, specific tools/systems used
        Pull from tenant_memory: integrations, team size, existing processes
        Draft should be: specific (not generic), actionable, auditor-friendly
      
    - step: 4
      name: "Review & Edit"
      instruction: "Show draft. Let user edit or approve. Help with wording if asked."
      loop: "keep editing until user approves"
      
    - step: 5
      name: "Save & Assign"
      instruction: "Save policy. Assign reviewer. Set review date."
      tool: policy.create
      then: policy.request_review
      
    - step: 6
      name: "Link to Controls"
      instruction: "Map policy to controls it covers. Update coverage."
      tool: evidence.bind_to_control
      memory: "tenant_remember: Policy '{name}' covers controls {controls}"
```

#### How skills and playbooks interact:

```
User message arrives
    │
    ▼
┌─────────────────────────┐
│ 1. Load role skills     │  ← from memory service, filtered by user.role
│    (already in context) │
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│ 2. Match skill trigger  │  ← keyword/pattern matching against user message
│    OR continue active   │     OR active skill from session state
│    playbook step        │
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│ 3. If skill has a       │
│    playbook: load it    │  ← playbook provides step-by-step instructions
│    Resume at current    │     to the LLM as additional system context
│    step (from session)  │
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│ 4. LLM sees:           │
│    - Persona prompt      │
│    - Active skill        │
│    - Current playbook    │
│      step + guidance     │
│    - Available tools     │
│    - User message        │
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│ 5. LLM responds:        │
│    - Follows playbook    │
│    - Calls tools         │
│    - Advances step       │
│    - Or handles detour   │
│      and returns to      │
│      playbook            │
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│ 6. Save state:          │
│    - session: current    │
│      step, workflow data │
│    - memory: facts       │
│      learned, task       │
│      updates             │
└─────────────────────────┘
```

#### Playbook properties:

- **Resumable**: if user leaves mid-playbook, session state saves the step. Next session picks up where they left off.
- **Interruptible**: user can ask unrelated questions mid-playbook. Agent answers, then returns: "Back to your onboarding — we were on step 3."
- **Skippable**: steps can be skipped if conditions are already met (`skip_if`)
- **Branching**: decision points lead to different step paths (`condition`)
- **Looping**: some steps repeat until done (audit testing: control after control)
- **Observable**: observer can see which playbook steps fail/succeed, optimize guidance

#### Storage:

- Skills stored in: `memory.skill_get(skill_id)` → versioned, observer-updateable
- Playbooks stored in: `memory.skill_get("playbook/{id}")` → same mechanism, just richer structure
- Session state tracks: `{active_skill, active_playbook, playbook_step, playbook_data}`
- Fallback: built-in default skills/playbooks bundled with agent image (used if memory service is down)

### R7: Approval & Audit

- Human-in-the-loop confirmation for destructive tools (delete, role change, etc.)
- Approval rules defined in agent config (which tools need confirmation)
- Audit logging: every tool call logged with `{tenant_id, user_id, role, tool, args, status, result, timestamp}`
- Audit log destination: memory service or dedicated audit endpoint
- MUST be tamper-resistant (append-only, no delete API)

### R8: Observability

- Every LLM call emits structured log: `{trace_id, agent: "compliance-assistant", task, model_used, latency_ms, tool_calls_count, success}`
- Tool execution logs: `{trace_id, tool_name, duration_ms, success, error}`
- Session metrics: messages per session, tools used per session, escalation count
- All consumed by observer for skill optimization

### R9: Container Packaging

- Single Docker image, independently versioned
- Version tag: `CHAT_VERSION` env var
- Health check: `GET /health`
- Readiness: `GET /ready` (true when tool registry loaded)
- Stateless — all state in memory service and backend
- No GPU required
- Graceful shutdown: finish in-progress tool execution

### R10: API Contract

- HTTP API (not Lambda-specific)
- Endpoints:
  - `POST /chat` — send message, get response (may include tool results)
    - Request: `{message, session_id, user_context: {tenant_id, user_id, role, email, name}}`
    - Response: `{message, session_id, actions: [], pending_confirmation: null|{...}}`
  - `POST /confirm` — approve pending destructive action
  - `POST /cancel` — reject pending action
  - `POST /init` — initialize session (greeting, skill selection)
  - `GET /health`
  - `GET /ready`

### R11: Task Types (for LLM gateway routing)

| Task declared by agent | Typical tier | Purpose |
|------------------------|:---:|---------|
| `tool_selection` | fast | Decide which tools to call |
| `chat_response` | fast | General conversation |
| `skill_execution` | mid | Multi-step skill flows |
| `summarize_results` | fast | Summarize tool outputs for user |
| `complex_guidance` | mid | Detailed compliance guidance |

### R12: Multi-Round Tool Use

- Agent sends message + available tools to LLM gateway
- LLM responds with tool calls (0 or more)
- Agent executes tools, sends results back to gateway
- Repeat up to N rounds (configurable, default 5)
- If tool calls exceed limit: respond with partial results + explanation
- Each round is a separate LLM gateway call (agent controls the loop)

### R13: Configuration

```yaml
# Environment variables
LLM_GATEWAY_URL: http://llm-gateway:4000
MEMORY_URL: http://memory-service:5000
MCP_SERVER_URL: http://backend:8080/mcp    # MCP route on backend
LOG_LEVEL: info
MAX_TOOL_ROUNDS: 5
SESSION_TTL_HOURS: 4
TOOL_TIMEOUT_SEC: 10
```

### R14: Approval Handling

- Approval rules are defined on the MCP server (per-tool `confirmation_required` flag)
- Agent-chat does NOT maintain its own approval list — it respects what MCP server returns
- Flow:
  1. Agent calls `tools/call` → MCP server returns `{status: "confirmation_required", summary: "..."}`
  2. Agent shows summary to user, asks confirm/cancel
  3. User confirms → agent calls `tools/call` again with `confirmed: true`
  4. User cancels → agent acknowledges, logs the cancellation
- Agent MUST show the MCP server's summary text to user (not generate its own)
