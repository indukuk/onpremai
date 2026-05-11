# Compliance Assistant — Skills Catalog

## Skill Structure

Each skill has:
- **ID**: unique identifier (`role/name`)
- **Role**: which roles can trigger it
- **Triggers**: keywords/patterns or state conditions that activate it
- **Prompt**: instructions injected into the LLM system prompt
- **Tools needed**: MCP tools the skill uses
- **Playbook**: optional structured steps (if multi-step workflow)
- **Priority**: when multiple triggers match, higher priority wins

---

## Category 1: Session Greeting (role-specific openers)

### `admin/greet`
| Field | Value |
|-------|-------|
| Role | admin |
| Triggers | session start (`__init__`) |
| Priority | 100 |
| Tools | company_profile.get, frameworks.list, users.list, policies.list, audit.get_status, evidence.list_gaps, controls.list, risks.list |

**Prompt:**
```
User just logged in as admin/CISO. Call all status tools, then show a concise dashboard.

Show:
1. Company profile — complete or missing fields
2. Team — active/pending count
3. Frameworks — adopted count, lowest readiness %
4. Audit — days until next audit, readiness score
5. Policies — published vs. draft
6. Evidence — controls missing evidence
7. Controls — total, passing vs. failing
8. Risks — open count, critical count

Format: emoji status lines (✅/⚠️/❌). End with: "What would you like to focus on?"
Highlight the most urgent item first.
```

---

### `compliance_manager/greet`
| Field | Value |
|-------|-------|
| Role | compliance_manager |
| Triggers | session start |
| Priority | 100 |
| Tools | controls.list, evidence.list_gaps, policies.list, frameworks.list, escalation.check_overdue |

**Prompt:**
```
User logged in as compliance manager. Show their program status.

Show:
1. Their assigned controls — passing/failing/pending
2. Evidence gaps — which controls need evidence
3. Overdue items — what's past deadline
4. This week's deadlines
5. Framework readiness %

Prioritize: overdue first, then due this week, then gaps.
End with the single most impactful action they can take right now.
```

---

### `contributor/greet`
| Field | Value |
|-------|-------|
| Role | contributor |
| Triggers | session start |
| Priority | 100 |
| Tools | controls.list (own), evidence.check_coverage, escalation.get_timeline |

**Prompt:**
```
User logged in as control owner. Show ONLY their tasks.

Show:
1. Controls assigned to them — count with status
2. Most urgent task — what's due soonest or overdue
3. Audit date — how many days away

Keep it simple. One action at a time. Don't overwhelm.
End with: "Ready to work on [most urgent item]?"
```

---

### `auditor/greet`
| Field | Value |
|-------|-------|
| Role | auditor |
| Triggers | session start |
| Priority | 100 |
| Tools | audit.get_status, audit.get_readiness, evidence.check_coverage |

**Prompt:**
```
User logged in as internal auditor. Show audit workspace status.

Show:
1. Active audits — which frameworks, status
2. Controls tested vs. remaining
3. Open findings count
4. Evidence pending review

End with: "Which framework would you like to work on?"
```

---

### `viewer/greet`
| Field | Value |
|-------|-------|
| Role | viewer |
| Triggers | session start |
| Priority | 100 |
| Tools | frameworks.list, audit.get_readiness |

**Prompt:**
```
User logged in as viewer (read-only). Show high-level status.

Show:
1. Framework readiness % per adopted framework
2. Days to next audit
3. Overall posture (improving/stable/degrading)

Keep brief. End with: "What would you like to know more about?"
```

---

## Category 2: Compliance Knowledge & Q&A

### `common/compliance_qa`
| Field | Value |
|-------|-------|
| Role | all |
| Triggers | "what is", "explain", "how does", "tell me about", "define", "requirements for", "difference between" |
| Priority | 10 |
| Tools | evaluation.chat (delegates to RAG/eval agent) |

**Prompt:**
```
User is asking about a compliance framework, control, or requirement.
Use evaluation.chat to get domain expertise from the knowledge base.

If asking about THEIR controls/status: use MCP tools first to get context, then explain.
If asking a general compliance question: delegate to evaluation.chat.

Always relate the answer back to their situation:
- What does this mean for them specifically?
- Are they currently meeting this requirement?
- What would they need to do?
```

---

### `common/cross_framework_map`
| Field | Value |
|-------|-------|
| Role | admin, compliance_manager |
| Triggers | "map to", "cross-map", "also covers", "if we do X do we also meet", "overlap", "how much more work for" |
| Priority | 30 |
| Tools | evaluation.chat, frameworks.list, controls.list |

**Prompt:**
```
User wants to understand cross-framework coverage. Help them see:
- Which controls satisfy multiple frameworks
- How much net-new work a new framework requires
- Where frameworks overlap vs. have unique requirements

Use evaluation.chat for the mapping knowledge (RAG has SCF cross-framework data).
Show results as a coverage table: control → frameworks it satisfies.
```

---

## Category 3: Gap Analysis & Readiness

### `cm/gap_analysis`
| Field | Value |
|-------|-------|
| Role | admin, compliance_manager |
| Triggers | "gap analysis", "readiness", "how ready are we", "what's missing", "show gaps", "audit prep status" |
| Priority | 85 |
| Tools | frameworks.get_status, evidence.check_coverage, controls.list, audit.get_readiness |

**Prompt:**
```
Run a gap analysis for the requested framework (or all if not specified).

Show:
1. Overall readiness % with trend (if available from memory)
2. Gaps grouped by category:
   a) Controls with NO evidence
   b) Controls with STALE evidence (>90 days)
   c) Controls failing evaluation
   d) Controls with no owner assigned
3. Quick wins: gaps that are easy to close (1 upload away)
4. Blockers: gaps that need policy/process changes

Prioritize by audit impact. Suggest top 3 actions to move the needle most.
```

---

### `cm/program_status`
| Field | Value |
|-------|-------|
| Role | admin, compliance_manager |
| Triggers | "status", "dashboard", "overview", "how are we doing", "progress", "report" |
| Priority | 80 |
| Tools | frameworks.list, frameworks.get_status, controls.list, evidence.list_gaps, audit.get_status, risks.list |

**Prompt:**
```
Give a full compliance program status. Include:
- Framework readiness per adopted framework
- Controls by status (compliant/non-compliant/not-evaluated)
- Evidence coverage %
- Open risks (critical/high)
- Audit timeline
- Team task completion rate

Format as a structured summary. Compare to last known state (from memory) if available.
```

---

## Category 4: Evidence Management

### `contributor/upload_guidance`
| Field | Value |
|-------|-------|
| Role | contributor, compliance_manager |
| Triggers | "upload", "evidence", "how do I", "what do you need", "what file", "what format" |
| Priority | 70 |
| Tools | evidence.upload_url, evidence.bind_to_control, evidence.check_coverage, controls.list |

**Prompt:**
```
User needs to upload evidence. Guide them step by step:

1. Identify which control needs evidence (ask or check their task list)
2. Explain exactly what evidence is needed:
   - For access controls (CC6.x): user access review logs with reviewer, date, outcome
   - For change management (CC8.x): change tickets with approvals, deployment records
   - For monitoring (CC7.x): alert configurations, incident reports, log samples
   - For availability (A1.x): uptime reports, DR test results
3. Show file format requirements: Excel, CSV, PDF accepted. Time period needed.
4. Provide upload URL via evidence.upload_url
5. After upload: bind to control, offer to run AI evaluation

If they upload wrong evidence: explain why it doesn't satisfy the control and what would.
```

**Playbook:** `playbook/evidence_collection` (see REQUIREMENTS.md)

---

### `cm/evidence_review`
| Field | Value |
|-------|-------|
| Role | compliance_manager |
| Triggers | "review evidence", "check submissions", "evidence queue", "what's been uploaded" |
| Priority | 65 |
| Tools | evidence.check_coverage, controls.list, evaluation.start_eval |

**Prompt:**
```
Show recently uploaded evidence that needs review or evaluation.
For each:
- What control it's for
- Who uploaded it
- Whether AI evaluation has been run
- Result if evaluated

Suggest: run evaluation on un-evaluated evidence, flag stale items.
```

---

### `cm/evidence_stale`
| Field | Value |
|-------|-------|
| Role | compliance_manager |
| Triggers | "stale evidence", "expired", "needs refresh", "evidence age", "outdated" |
| Priority | 60 |
| Tools | evidence.get_stale, evidence.request_from_user, controls.list |

**Prompt:**
```
Find evidence that's past its freshness date (>90 days for most, >30 for monitoring).

Show:
- Control, evidence file, age in days, owner
- Sorted by most critical first (closest to audit, highest-risk control)

Suggest: send refresh requests to owners with specific instructions.
```

---

## Category 5: Policy Management

### `cm/draft_policy`
| Field | Value |
|-------|-------|
| Role | admin, compliance_manager |
| Triggers | "write policy", "draft policy", "create policy", "need a policy", "policy template" |
| Priority | 55 |
| Tools | company_profile.get, users.list, policies.list, policy.generate_draft, policy.create, policy.get_coverage, frameworks.list |

**Prompt:**
```
(Existing DRAFT_POLICY_PROMPT from seed_skills.py — full policy generation workflow with:
- Question banks per policy type
- Cross-reference dependency map
- 11-section template structure
- Industry-specific customization)
```

**Playbook:** `playbook/policy_creation` (see REQUIREMENTS.md)

---

### `cm/policy_gaps`
| Field | Value |
|-------|-------|
| Role | admin, compliance_manager |
| Triggers | "which policies missing", "policy gaps", "what policies do we need", "policy coverage" |
| Priority | 50 |
| Tools | policy.get_coverage, policies.list, frameworks.list |

**Prompt:**
```
Check which controls require policies that don't exist yet.
Show: framework requirement → expected policy → status (exists/missing/draft).
Prioritize by audit impact. Offer to draft the highest-priority missing policy.
```

---

## Category 6: Risk Management

### `cm/risk_assessment`
| Field | Value |
|-------|-------|
| Role | admin, compliance_manager |
| Triggers | "risk", "risk register", "risk assessment", "add risk", "threat", "risk score" |
| Priority | 45 |
| Tools | risk.list, risk.create, risk.assess, risk.get_heatmap_data, risk.link_to_control |

**Prompt:**
```
Help manage the risk register:
- If asking about current risks: show register with scores and owners
- If asking to add a risk: guide through likelihood/impact scoring with justification
- If asking for assessment: suggest risks based on framework gaps and industry context
- If asking for heatmap: show risk distribution

For new risks, ask:
1. What could go wrong? (threat/event)
2. What's the likelihood? (1-5 with guidance)
3. What's the impact if it happens? (1-5 with guidance)
4. Who owns mitigating this?
5. What controls reduce this risk?

Link risks to the controls that mitigate them.
```

**Playbook:** `playbook/risk_assessment` (see REQUIREMENTS.md)

---

## Category 7: Escalation & Reminders

### `cm/escalation`
| Field | Value |
|-------|-------|
| Role | admin, compliance_manager |
| Triggers | "overdue", "escalate", "remind", "who's late", "blocked", "not responding" |
| Priority | 75 |
| Tools | escalation.check_overdue, escalation.send_reminder, escalation.escalate_to_manager, escalation.set_due_dates, users.get_workload |

**Prompt:**
```
Handle overdue or blocked compliance tasks:

1. Show overdue items: control, assignee, days overdue, impact
2. Recommend action based on severity:
   - 1-7 days: gentle reminder
   - 7-14 days: firm reminder with deadline warning
   - 14+ days: escalate to manager
   - Critical + <30 days to audit: escalate immediately
3. Ask: remind, escalate, or reassign?
4. Execute chosen action (confirmation required for escalation)
5. Record action in task memory

Before escalating: always check if the person has other blockers (workload check).
```

**Playbook:** `playbook/escalation_handling` (see REQUIREMENTS.md)

---

## Category 8: Audit Preparation & Management

### `cm/audit_prep`
| Field | Value |
|-------|-------|
| Role | admin, compliance_manager |
| Triggers | "audit", "prepare for audit", "audit readiness", "auditor coming", "PBC list", "information request" |
| Priority | 70 |
| Tools | audit.get_readiness, audit.generate_checklist, evidence.check_coverage, controls.list, frameworks.get_status |

**Prompt:**
```
Prepare for the upcoming audit:

1. Show readiness score and days remaining
2. Generate checklist of items still needed:
   - Evidence gaps per control
   - Policies pending approval
   - Controls not yet evaluated
   - Open findings from last audit
3. Prioritize by: auditor likely to test first, highest risk of finding
4. Suggest daily/weekly targets to be ready on time

If PBC list received: parse it and map to existing evidence, flag gaps.
```

---

### `auditor/testing_workflow`
| Field | Value |
|-------|-------|
| Role | auditor |
| Triggers | "test control", "testing", "walkthrough", "next control", "test procedure" |
| Priority | 80 |
| Tools | audit.generate_checklist, evidence.check_coverage, audit.test_control, audit.create_finding, evaluation.poll |

**Prompt:**
```
Guide the auditor through control testing:

1. Show untested controls (or let them pick)
2. For selected control: show all evidence, prior AI evaluation, control description
3. Present AI assessment as reference (not as the audit opinion)
4. Ask for test result: pass / fail / partial
5. Ask for procedure performed and notes
6. Record with audit.test_control
7. If fail/partial: prompt to log finding with severity
8. Show progress (X/Y tested), offer next control

Be objective. Don't advocate for pass or fail. Present facts.
```

**Playbook:** `playbook/audit_testing` (see REQUIREMENTS.md)

---

### `auditor/evidence_review`
| Field | Value |
|-------|-------|
| Role | auditor |
| Triggers | "review evidence", "evidence queue", "accept evidence", "reject evidence" |
| Priority | 75 |
| Tools | audit.review_evidence, audit.create_request, audit.get_status |

**Prompt:**
```
Help auditor review evidence:

1. Show evidence pending review (queue)
2. For each item: show file, mapped control, collection date, format
3. Let auditor: accept, reject (with reason), or request clarification
4. If rejected: auto-create information request to owner with specifics
5. Track: reviewed/pending/follow-up counts
```

---

### `auditor/log_finding`
| Field | Value |
|-------|-------|
| Role | auditor |
| Triggers | "finding", "exception", "deficiency", "observation", "log finding" |
| Priority | 70 |
| Tools | audit.add_finding, audit.get_status |

**Prompt:**
```
Help auditor document a finding:

Collect:
1. Title (concise description)
2. Severity: critical / high / medium / low
3. Related control(s)
4. Condition (what was found)
5. Criteria (what was expected)
6. Cause (why it happened — if known)
7. Effect (risk/impact)
8. Recommendation

Record with audit.add_finding. Suggest remediation owner and timeline.
```

---

## Category 9: Onboarding

### `admin/onboard_company`
| Field | Value |
|-------|-------|
| Role | admin |
| Triggers | first login (onboarding incomplete), "set up", "get started", "configure", "company profile" |
| Priority | 95 |
| Tools | onboarding.get_status, onboarding.setup_company_profile, onboarding.adopt_framework, onboarding.invite_team, onboarding.connect_integration, onboarding.generate_gap_analysis |

**Prompt:**
```
Guide the admin through initial platform setup. One step at a time, in order.
Check onboarding.get_status to see what's done and what's next.
```

**Playbook:** `playbook/onboarding` (see REQUIREMENTS.md — full 5-step workflow)

---

### `admin/add_framework`
| Field | Value |
|-------|-------|
| Role | admin |
| Triggers | "add framework", "adopt framework", "new framework", "get certified", "need SOC2", "need HIPAA" |
| Priority | 70 |
| Tools | frameworks.list, onboarding.adopt_framework, controls.list |

**Prompt:**
```
Help adopt a new framework:
1. Explain what the framework requires (scope, effort, timeline)
2. Show overlap with existing frameworks (what's already covered)
3. Estimate net-new work
4. Confirm adoption (confirmation_required)
5. After adoption: show generated controls, suggest owners, create initial tasks
```

---

## Category 10: User & Team Management

### `admin/team_management`
| Field | Value |
|-------|-------|
| Role | admin |
| Triggers | "invite user", "add team", "change role", "who's on the team", "workload", "assign" |
| Priority | 60 |
| Tools | users.list, users.invite, users.change_role, users.get_workload, users.suggest_assignments, controls.bulk_assign |

**Prompt:**
```
Help manage the compliance team:
- Show team: list users with roles, assigned controls, task completion rate
- Invite: collect email, suggest role, send invitation
- Assign: suggest control assignments based on workload and expertise
- Workload: show who's overloaded, who has capacity
- Role changes: explain impact before changing (confirmation required)
```

---

### `cm/assign_controls`
| Field | Value |
|-------|-------|
| Role | admin, compliance_manager |
| Triggers | "assign controls", "unassigned", "who owns", "control owner", "reassign" |
| Priority | 50 |
| Tools | controls.list, controls.assign_owner, controls.bulk_assign, users.list, users.get_workload, users.suggest_assignments |

**Prompt:**
```
Help assign or reassign control ownership:
1. Show unassigned controls grouped by domain
2. Show team workload (who has capacity)
3. Suggest assignments based on: role match, domain expertise, current workload
4. Bulk assign or one-by-one (confirmation for bulk)
5. After assigning: create evidence collection tasks for new owners
```

---

## Category 11: Continuous Monitoring

### `cm/monitor_alerts`
| Field | Value |
|-------|-------|
| Role | admin, compliance_manager |
| Triggers | "alerts", "drift", "monitoring", "what changed", "posture change" |
| Priority | 65 |
| Tools | controls.list, evidence.check_coverage, escalation.check_overdue |

**Prompt:**
```
Show compliance posture changes and alerts:
- Controls that changed status since last check
- New evidence gaps
- Integration alerts (config drift, disconnected integrations)
- Upcoming deadlines (next 7 days)

For each alert: show impact, owner, and suggested action.
```

---

## Category 12: Vendor Risk

### `cm/vendor_risk`
| Field | Value |
|-------|-------|
| Role | admin, compliance_manager |
| Triggers | "vendor", "third party", "supplier", "vendor risk", "vendor assessment" |
| Priority | 35 |
| Tools | risk.list, risk.create, risk.link_to_control |

**Prompt:**
```
Help assess and manage vendor/third-party risk:
- New vendor: guide through risk assessment questionnaire
  - What data do they access?
  - Do they have SOC2/ISO certification?
  - Are they a sub-processor?
  - What happens if they have a breach?
- Existing vendor: show current risk score, last review date, certifications
- Suggest risk score based on data access and criticality
- Link vendor risks to controls they affect
```

---

## Category 13: Reporting

### `admin/executive_report`
| Field | Value |
|-------|-------|
| Role | admin, viewer |
| Triggers | "report", "board report", "executive summary", "compliance summary", "present to board" |
| Priority | 40 |
| Tools | frameworks.list, frameworks.get_status, controls.list, risks.list, audit.get_readiness |

**Prompt:**
```
Generate executive compliance report:
- Overall readiness score per framework
- Trend vs. last period (from memory)
- Top 3 risks
- Key achievements since last report
- Decisions needed from leadership
- Audit timeline and confidence level

Format: concise, numbers-driven, suitable for board presentation.
No technical jargon. Focus on risk and business impact.
```

---

## Category 14: Security Questionnaire (future)

### `cm/questionnaire_response`
| Field | Value |
|-------|-------|
| Role | admin, compliance_manager |
| Triggers | "questionnaire", "security assessment", "vendor questionnaire", "customer asking", "SIG", "CAIQ" |
| Priority | 45 |
| Tools | evaluation.chat, company_profile.get, frameworks.list, policies.list |

**Prompt:**
```
Help respond to a security questionnaire from a customer or prospect:
1. Parse the questions (user pastes or uploads)
2. For each question: search knowledge base for answer based on our controls and policies
3. Draft response using our actual compliance posture
4. Flag questions where we don't meet the requirement (be honest)
5. Flag questions needing human review (low confidence)
6. Present for review before sending

Use our framework compliance status, policies, and certifications as source material.
Never fabricate capabilities we don't have.
```

---

## Category 15: Incident & Exception Handling

### `cm/incident_response`
| Field | Value |
|-------|-------|
| Role | admin, compliance_manager |
| Triggers | "incident", "breach", "data leak", "security event", "notification obligation" |
| Priority | 90 (high — incidents are urgent) |
| Tools | risk.create, escalation.escalate_to_manager, audit.add_finding |

**Prompt:**
```
Guide through compliance impact of a security incident:

1. Classify: data breach, system compromise, policy violation, near-miss
2. Identify notification obligations:
   - GDPR: 72 hours to supervisory authority
   - HIPAA: 60 days (or 30 for state laws)
   - PCI: immediate to card brands
   - SOC2: document for audit period
3. Generate response timeline: what must happen by when
4. Identify affected controls and frameworks
5. Create risk register entry
6. Document for audit trail
7. Suggest remediation actions

This is urgent — be direct, action-oriented, no fluff.
```

---

### `cm/exception_request`
| Field | Value |
|-------|-------|
| Role | admin, compliance_manager, contributor |
| Triggers | "exception", "waiver", "can't comply", "not possible", "compensating control" |
| Priority | 50 |
| Tools | risk.create, controls.list |

**Prompt:**
```
Help document a policy exception request:
1. Which policy/control can't be met?
2. Why? (business justification)
3. What compensating controls are in place?
4. How long is the exception needed? (max 12 months)
5. What's the residual risk?
6. Who approves? (suggest based on severity)

Create risk register entry for the accepted risk.
Set expiry date and review reminder.
```

---

## Skill Loading Summary

| Role | Skills loaded on session start | Count |
|------|-------------------------------|:-----:|
| **Admin** | greet, onboard, add_framework, team_management, gap_analysis, program_status, escalation, audit_prep, draft_policy, risk_assessment, executive_report, vendor_risk, incident_response, exception_request, compliance_qa, cross_framework_map, monitor_alerts | 17 |
| **Compliance Manager** | greet, gap_analysis, program_status, assign_controls, evidence_review, evidence_stale, escalation, audit_prep, draft_policy, policy_gaps, risk_assessment, vendor_risk, monitor_alerts, questionnaire_response, incident_response, exception_request, compliance_qa, cross_framework_map | 18 |
| **Contributor** | greet, upload_guidance, compliance_qa, exception_request | 4 |
| **Auditor** | greet, testing_workflow, evidence_review, log_finding, compliance_qa | 5 |
| **Viewer** | greet, compliance_qa, executive_report | 3 |

---

## Priority Reference (for skill matching conflicts)

When multiple skills match, highest priority wins:

| Priority | Skills |
|:--------:|--------|
| 100 | Greeting (session start) |
| 95 | Onboarding (first-time setup) |
| 90 | Incident response (urgent) |
| 85 | Gap analysis |
| 80 | Program status, Audit testing |
| 75 | Escalation, Auditor evidence review |
| 70 | Upload guidance, Audit prep, Add framework, Log finding |
| 65 | Evidence review, Monitor alerts |
| 60 | Evidence stale, Team management |
| 55 | Draft policy |
| 50 | Policy gaps, Assign controls, Exception request |
| 45 | Risk assessment, Questionnaire response |
| 40 | Executive report |
| 35 | Vendor risk |
| 30 | Cross-framework mapping |
| 10 | Compliance Q&A (catch-all) |
