# Frontend Integration — Requirements & Design

## Overview

Integrate the new AI system (onpremai) as the backend for the existing Lotus AI compliance platform frontend (vanilla JS SPA at `/compliance/frontend/platform/`). Remove the old Lambda-based agent and rewire all AI interactions to the new microservices.

---

## Requirements

### FR1: API Rewiring

- **FR1-1:** All evaluation calls MUST route to `agent-eval:8080` instead of the old Lambda `/v3` endpoint
- **FR1-2:** All chat interactions MUST route to `compliance-assistant:8081/chat` instead of the old agent-chat Lambda
- **FR1-3:** All evaluation interaction (accept/override/comment) MUST route to `memory-service:5000/evaluations/*`
- **FR1-4:** Authentication MUST continue using Cognito JWT (unchanged) — new services validate the same token
- **FR1-5:** Frontend MUST support configurable backend URLs via `DATA.settings` (for on-prem vs AWS)

### FR2: Evaluation Justification Display

- **FR2-1:** Control detail page MUST show full evaluation justification when an evaluation exists
- **FR2-2:** Layer 1 (rules) results MUST display as a compact table with method and evidence cited
- **FR2-3:** Layer 2 (tribunal) results MUST display collapsible sections showing Prosecutor, Defender, and Judge reasoning
- **FR2-4:** Layer 3 (scoring) MUST show the formula, weights, and floor rules applied
- **FR2-5:** Each criterion MUST show its confidence level (for tribunal results)
- **FR2-6:** Policy source references MUST be displayed and linkable where available
- **FR2-7:** Decision status (pending/accepted/overridden) MUST be visible at the top of the evaluation

### FR3: Accept/Override Workflow

- **FR3-1:** Users with role `compliance_manager`, `auditor`, or `admin` MUST see Accept/Override buttons per criterion
- **FR3-2:** "Accept All" button MUST accept the entire evaluation in one action
- **FR3-3:** Override MUST require a reason (form validation — cannot submit empty)
- **FR3-4:** Override dialog MUST show the AI verdict and allow selecting PASS/PARTIAL/FAIL
- **FR3-5:** After override, both AI verdict and user verdict MUST display side-by-side
- **FR3-6:** `viewer` and `contributor` roles see evaluations read-only (no accept/override buttons)

### FR4: Comment Threads

- **FR4-1:** Comments MUST be available per-criterion and per-evaluation (overall)
- **FR4-2:** Comments MUST support threading (reply to specific comment)
- **FR4-3:** Comment author, role, and timestamp MUST display
- **FR4-4:** Users MUST be able to delete their own comments (soft delete)
- **FR4-5:** Comment count badge MUST show on each criterion section

### FR5: Shadow AI Chat Enhancement

- **FR5-1:** Chat panel MUST connect to `compliance-assistant:8081/chat` via streaming (SSE or chunked response)
- **FR5-2:** Chat MUST display pending notifications on session start (from agent)
- **FR5-3:** Chat MUST support confirmation dialogs for destructive actions (escalation, reminders)
- **FR5-4:** Chat actions (buttons below messages) MUST trigger navigation to relevant pages (e.g., "View CC6.1" navigates to control detail)
- **FR5-5:** Chat MUST persist session_id across page navigation (session survives hash changes)
- **FR5-6:** Chat MUST show role-appropriate greeting based on user's JWT role claim

### FR6: Policy Analysis Integration

- **FR6-1:** Policies page MUST show analysis status per policy document (not analyzed / in progress / completed)
- **FR6-2:** Completed policies MUST show: controls mapped, criteria generated, conflicts detected
- **FR6-3:** Conflicts MUST be surfaced with a resolution UI (choose between conflicting values)
- **FR6-4:** "Re-analyze" button MUST be available for policy documents that have changed
- **FR6-5:** Policy-to-control mapping MUST be viewable (which policy sections map to which controls)

### FR7: Auditor Workspace Enhancement

- **FR7-1:** Auditor control testing page MUST show AI evaluation as reference (with "AI Reference" label)
- **FR7-2:** Auditor MUST see tribunal justification alongside their own testing workflow
- **FR7-3:** When auditor's verdict differs from AI, both MUST display with clear labeling
- **FR7-4:** Auditor findings MUST be able to reference specific tribunal criteria
- **FR7-5:** Audit trail view MUST show: AI said X → User decided Y → because Z

### FR8: Evaluation Trigger

- **FR8-1:** "Evaluate" button on control detail page MUST call `POST /evaluate` and show a loading state
- **FR8-2:** Polling MUST occur every 3 seconds until status is `completed` or `failed`
- **FR8-3:** When evaluation completes, justification panel MUST render automatically
- **FR8-4:** "Re-evaluate" button MUST pass `bypass_cache: true` to force fresh evaluation
- **FR8-5:** If evaluation returns `cached: true`, display "Using cached result (evidence unchanged)" indicator

---

## Design

### Architecture: Frontend ↔ New Backend

```
┌────────────────────────────────────────────────────────────────────┐
│  Frontend (Vanilla JS SPA — unchanged shell)                        │
│                                                                      │
│  index.html                                                          │
│  ├── js/api.js ──────────────────┐                                  │
│  ├── js/ai-chat.js               │  API calls                       │
│  ├── js/controls.js              │                                   │
│  ├── js/detail.js                │                                   │
│  ├── js/auditor.js               │                                   │
│  ├── js/policies.js              │                                   │
│  │                               │                                   │
│  │  NEW modules:                 │                                   │
│  ├── js/evaluation-panel.js      │                                   │
│  ├── js/tribunal-display.js      │                                   │
│  ├── js/comments.js              │                                   │
│  ├── js/override-dialog.js       │                                   │
│  └── js/policy-analysis.js       │                                   │
│                                   │                                   │
└───────────────────────────────────┼───────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────┐
│  API Gateway / Reverse Proxy (nginx or ALB)                         │
│                                                                      │
│  /api/chat/*          → compliance-assistant:8081                    │
│  /api/evaluate/*      → agent-eval:8080                             │
│  /api/evaluations/*   → memory-service:5000                         │
│  /api/policies/*      → memory-service:5000                         │
│  /api/upload/*        → preprocessor:7000                           │
│  /api/auth/*          → Cognito (unchanged)                         │
└────────────────────────────────────────────────────────────────────┘
```

### New JS Module Structure

```
frontend/platform/js/
├── app.js                    (modify: add new page routes)
├── api.js                    (modify: new endpoints)
├── ai-chat.js                (modify: new backend URL, streaming)
├── controls.js               (modify: add "Evaluate" button)
├── detail.js                 (modify: add justification panel mount point)
├── auditor.js                (modify: show AI reference in testing)
├── policies.js               (modify: add analysis status, conflicts)
│
├── evaluation-panel.js       (NEW: renders full justification)
├── tribunal-display.js       (NEW: collapsible prosecution/defense/judge)
├── comments.js               (NEW: threaded comment component)
├── override-dialog.js        (NEW: override modal with form)
└── policy-analysis.js        (NEW: policy status, graph view, conflicts)
```

### Component Design: Evaluation Panel

```javascript
// evaluation-panel.js — renders inside control detail page

const EvaluationPanel = {
  async render(controlId, framework) {
    // 1. Fetch evaluation + justification + decisions + comments
    const data = await API.getEvaluation(controlId, framework);
    if (!data) return this._renderNoEval(controlId);
    
    // 2. Render sections
    return `
      <div class="eval-panel">
        ${this._header(data)}
        ${this._layer1(data.justification.layer1_justification)}
        ${this._layer2(data.justification.layer2_justification)}
        ${this._layer3(data.justification.layer3_justification)}
        ${this._actions(data)}
      </div>
    `;
  },
  
  _header(data) { /* Score, status, decision_status, policy basis */ },
  _layer1(l1) { /* Compact table of rule results */ },
  _layer2(l2) { /* Collapsible tribunal cards per criterion */ },
  _layer3(l3) { /* Scoring formula display */ },
  _actions(data) { /* Accept All, Re-evaluate, Add Comment */ },
};
```

### Component Design: Tribunal Display

```javascript
// tribunal-display.js — renders one tribunal criterion result

const TribunalDisplay = {
  render(criterion, decisions, comments) {
    const isOverridden = decisions.find(d => d.criterion_id === criterion.criterion_id);
    
    return `
      <div class="tribunal-card ${criterion.result.toLowerCase()}">
        <div class="tribunal-header" onclick="TribunalDisplay.toggle('${criterion.criterion_id}')">
          <span class="tribunal-id">${criterion.criterion_id}</span>
          <span class="tribunal-question">${criterion.question}</span>
          <span class="tribunal-verdict verdict-${criterion.result.toLowerCase()}">${criterion.result}</span>
          <span class="tribunal-confidence">${Math.round(criterion.confidence * 100)}%</span>
          ${isOverridden ? '<span class="badge badge-override">Overridden</span>' : ''}
          <span class="tribunal-expand">▼</span>
        </div>
        
        <div class="tribunal-body" id="tribunal-${criterion.criterion_id}" style="display:none">
          <div class="tribunal-section prosecution">
            <h4>⚔️ Prosecutor</h4>
            <div class="tribunal-text">${this._formatBullets(criterion.prosecution)}</div>
          </div>
          
          <div class="tribunal-section defense">
            <h4>🛡️ Defender</h4>
            <div class="tribunal-text">${this._formatBullets(criterion.defense)}</div>
          </div>
          
          <div class="tribunal-section judge">
            <h4>⚖️ Judge</h4>
            <div class="tribunal-reasoning">
              <div class="judge-accepted">
                <strong>Prosecution accepted:</strong> ${criterion.judge_reasoning.prosecution_points_accepted.join('; ')}
              </div>
              <div class="judge-rejected">
                <strong>Prosecution rejected:</strong> ${criterion.judge_reasoning.prosecution_points_rejected.join('; ')}
              </div>
              <div class="judge-justification">
                "${criterion.judge_reasoning.justification}"
              </div>
            </div>
          </div>
          
          ${criterion.policy_source ? `<div class="tribunal-policy">📋 ${criterion.policy_source}</div>` : ''}
          
          ${isOverridden ? this._overrideDisplay(isOverridden) : ''}
          
          <div class="tribunal-actions">
            ${Comments.renderCount(criterion.criterion_id, comments)}
            ${Perm.canOverride() ? `
              <button class="btn btn-sm" onclick="EvaluationPanel.accept('${criterion.criterion_id}')">Accept ✓</button>
              <button class="btn btn-sm btn-secondary" onclick="OverrideDialog.open('${criterion.criterion_id}', '${criterion.result}')">Override ✎</button>
            ` : ''}
          </div>
          
          ${Comments.renderThread(criterion.criterion_id, comments)}
        </div>
      </div>
    `;
  },
  
  toggle(id) {
    const el = document.getElementById('tribunal-' + id);
    el.style.display = el.style.display === 'none' ? 'block' : 'none';
  },
};
```

### CSS Additions

```css
/* css/evaluation.css — new file */

.eval-panel { margin-top: 24px; }

.eval-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 16px 20px; background: var(--bg-card); border-radius: 8px;
  margin-bottom: 16px; border: 1px solid var(--border);
}

.eval-score { font-size: 28px; font-weight: 700; }
.eval-score.compliant { color: var(--success); }
.eval-score.partial { color: var(--warning); }
.eval-score.non-compliant { color: var(--danger); }

.tribunal-card {
  border: 1px solid var(--border); border-radius: 8px;
  margin-bottom: 8px; overflow: hidden;
}
.tribunal-card.pass { border-left: 3px solid var(--success); }
.tribunal-card.partial { border-left: 3px solid var(--warning); }
.tribunal-card.fail { border-left: 3px solid var(--danger); }

.tribunal-header {
  display: flex; align-items: center; gap: 12px;
  padding: 12px 16px; cursor: pointer;
  background: var(--bg-card);
}
.tribunal-header:hover { background: var(--bg-hover); }

.tribunal-body { padding: 16px; background: var(--bg-subtle); }

.tribunal-section {
  margin-bottom: 16px; padding: 12px;
  border-radius: 6px; background: var(--bg-card);
}
.tribunal-section.prosecution { border-left: 3px solid var(--danger); }
.tribunal-section.defense { border-left: 3px solid var(--success); }
.tribunal-section.judge { border-left: 3px solid var(--primary); }

.tribunal-section h4 { font-size: 13px; font-weight: 600; margin-bottom: 8px; }
.tribunal-text { font-size: 13px; line-height: 1.5; color: var(--text-secondary); }

.judge-justification {
  font-style: italic; margin-top: 8px; padding: 8px 12px;
  background: var(--bg-subtle); border-radius: 4px;
}

.tribunal-policy {
  font-size: 12px; color: var(--text-muted); margin-top: 8px;
  padding: 6px 10px; background: var(--bg-subtle); border-radius: 4px;
}

.verdict-pass { color: var(--success); font-weight: 600; }
.verdict-partial { color: var(--warning); font-weight: 600; }
.verdict-fail { color: var(--danger); font-weight: 600; }

.badge-override {
  font-size: 11px; padding: 2px 6px; border-radius: 3px;
  background: var(--warning-bg); color: var(--warning);
}

/* Comments */
.comment-thread { margin-top: 12px; padding-top: 12px; border-top: 1px solid var(--border); }
.comment-item { padding: 8px 0; font-size: 13px; }
.comment-author { font-weight: 600; color: var(--text-primary); }
.comment-time { font-size: 11px; color: var(--text-muted); }
.comment-reply { margin-left: 24px; border-left: 2px solid var(--border); padding-left: 12px; }

/* Override dialog */
.override-modal { position: fixed; inset: 0; z-index: 1000; display: flex; align-items: center; justify-content: center; }
.override-backdrop { position: absolute; inset: 0; background: rgba(0,0,0,0.5); }
.override-content { position: relative; background: var(--bg-card); border-radius: 12px; padding: 24px; width: 480px; max-width: 90vw; }
```

### API Module Updates

```javascript
// api.js — new service URLs and methods

const AGENT_EVAL_URL = DATA.settings.agentEvalUrl || '/api/evaluate';
const ASSISTANT_URL = DATA.settings.assistantUrl || '/api/chat';
const MEMORY_URL = DATA.settings.memoryUrl || '/api/evaluations';

const API = {
  // ... existing methods ...

  // === NEW: Evaluation ===
  async startEval(controlId, framework) {
    const res = await this._fetch(`${AGENT_EVAL_URL}/evaluate`, {
      method: 'POST',
      body: JSON.stringify({ control_id: controlId, framework, tenant_id: Auth.getTenantId() })
    });
    return await res.json();
  },

  async pollEval(jobId) {
    const res = await this._fetch(`${AGENT_EVAL_URL}/status/${jobId}`);
    return await res.json();
  },

  async getEvaluation(controlId, framework) {
    const res = await this._fetch(`${MEMORY_URL}?control_id=${controlId}&framework=${framework}&tenant_id=${Auth.getTenantId()}`);
    if (res.status === 404) return null;
    return await res.json();
  },

  // === NEW: Decisions ===
  async acceptEval(evalId, criterionId = null) {
    return this._fetch(`${MEMORY_URL}/${evalId}/accept`, {
      method: 'POST',
      body: JSON.stringify({ criterion_id: criterionId })
    });
  },

  async overrideEval(evalId, criterionId, userVerdict, reason) {
    return this._fetch(`${MEMORY_URL}/${evalId}/override`, {
      method: 'POST',
      body: JSON.stringify({ criterion_id: criterionId, user_verdict: userVerdict, reason })
    });
  },

  // === NEW: Comments ===
  async getComments(evalId) {
    const res = await this._fetch(`${MEMORY_URL}/${evalId}/comments`);
    return await res.json();
  },

  async addComment(evalId, content, criterionId = null, parentId = null) {
    return this._fetch(`${MEMORY_URL}/${evalId}/comments`, {
      method: 'POST',
      body: JSON.stringify({ content, criterion_id: criterionId, parent_comment_id: parentId })
    });
  },

  // === NEW: Chat (streaming) ===
  async chatStream(message, sessionId, onChunk) {
    const res = await fetch(`${ASSISTANT_URL}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + Auth.getToken() },
      body: JSON.stringify({ message, session_id: sessionId, stream: true })
    });
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      onChunk(decoder.decode(value));
    }
  },

  // === NEW: Policy Analysis ===
  async getPolicyStatus(tenantId) {
    const res = await this._fetch(`${MEMORY_URL}/policies/${tenantId}/status`);
    return await res.json();
  },

  async triggerPolicyAnalysis(documentKey, framework) {
    return this._fetch(`${ASSISTANT_URL}/analyze-policy`, {
      method: 'POST',
      body: JSON.stringify({ document_key: documentKey, framework, tenant_id: Auth.getTenantId() })
    });
  },
};
```

---

## Tasks

### Phase 1: API Rewiring (Foundation)

| # | Task | File(s) | Effort |
|---|------|---------|--------|
| 1.1 | Update `DATA.settings` to include new service URLs | `js/data.js` | S |
| 1.2 | Rewrite `API.startEval()` and `API.pollEval()` to call agent-eval | `js/api.js` | S |
| 1.3 | Rewrite `AiChat._callAgent()` to call compliance-assistant | `js/ai-chat.js` | M |
| 1.4 | Add streaming support to AI chat (SSE/chunked) | `js/ai-chat.js` | M |
| 1.5 | Add new API methods: `acceptEval`, `overrideEval`, `addComment`, `getComments` | `js/api.js` | S |
| 1.6 | Add reverse proxy config (nginx) to route `/api/*` to correct backend | `nginx.conf` or ALB rules | S |
| 1.7 | Verify JWT auth works with new services (same Cognito token) | Integration test | S |

### Phase 2: Evaluation Justification Display

| # | Task | File(s) | Effort |
|---|------|---------|--------|
| 2.1 | Create `evaluation-panel.js` — main justification container | NEW: `js/evaluation-panel.js` | L |
| 2.2 | Create `tribunal-display.js` — collapsible prosecution/defense/judge | NEW: `js/tribunal-display.js` | L |
| 2.3 | Add Layer 1 rules table (compact, non-collapsible) | `js/evaluation-panel.js` | M |
| 2.4 | Add Layer 3 scoring display (formula, weights, floors) | `js/evaluation-panel.js` | S |
| 2.5 | Add evaluation header (score, status badge, decision status) | `js/evaluation-panel.js` | S |
| 2.6 | Add policy source badges with links | `js/tribunal-display.js` | S |
| 2.7 | Mount evaluation panel in control detail page | `js/detail.js` | M |
| 2.8 | Add "Evaluate" and "Re-evaluate" buttons to control detail | `js/detail.js` | S |
| 2.9 | Add polling UX (loading spinner, progress indicator) | `js/detail.js` | S |
| 2.10 | Create `css/evaluation.css` — all evaluation panel styles | NEW: `css/evaluation.css` | M |

### Phase 3: Accept/Override/Comments

| # | Task | File(s) | Effort |
|---|------|---------|--------|
| 3.1 | Create `override-dialog.js` — modal with verdict + reason form | NEW: `js/override-dialog.js` | M |
| 3.2 | Create `comments.js` — threaded comment component | NEW: `js/comments.js` | L |
| 3.3 | Add Accept/Override buttons (role-gated via `Perm.canOverride()`) | `js/tribunal-display.js` | S |
| 3.4 | Add "Accept All" button to evaluation header | `js/evaluation-panel.js` | S |
| 3.5 | Implement override submission (API call + UI update) | `js/override-dialog.js` | M |
| 3.6 | Display AI verdict vs user verdict side-by-side after override | `js/tribunal-display.js` | M |
| 3.7 | Implement comment posting (with reply threading) | `js/comments.js` | M |
| 3.8 | Add comment count badges per criterion | `js/tribunal-display.js` | S |
| 3.9 | Add comment delete (soft delete, author only) | `js/comments.js` | S |
| 3.10 | Add role check: `Perm.canOverride()` returns true for auditor/cm/admin | `js/auth.js` | S |

### Phase 4: Shadow AI Chat Enhancement

| # | Task | File(s) | Effort |
|---|------|---------|--------|
| 4.1 | Connect chat to compliance-assistant streaming endpoint | `js/ai-chat.js` | M |
| 4.2 | Add pending notifications display on chat open | `js/ai-chat.js` | M |
| 4.3 | Add action buttons that navigate to pages (e.g., "View CC6.1") | `js/ai-chat.js` | S |
| 4.4 | Add confirmation dialog for destructive actions | `js/ai-chat.js` | S (exists) |
| 4.5 | Persist session_id in sessionStorage (survives navigation) | `js/ai-chat.js` | S |
| 4.6 | Show role-appropriate greeting based on JWT role | `js/ai-chat.js` | S |

### Phase 5: Policy Analysis Integration

| # | Task | File(s) | Effort |
|---|------|---------|--------|
| 5.1 | Create `policy-analysis.js` — policy status cards | NEW: `js/policy-analysis.js` | L |
| 5.2 | Add analysis status to policy list (not analyzed/in progress/done) | `js/policies.js` | M |
| 5.3 | Add "Analyze" button for uploaded policies | `js/policies.js` | S |
| 5.4 | Add conflict resolution UI (choose between conflicting values) | `js/policy-analysis.js` | L |
| 5.5 | Add policy → control mapping view (which sections map where) | `js/policy-analysis.js` | M |
| 5.6 | Add "Re-analyze" trigger for updated policies | `js/policies.js` | S |

### Phase 6: Auditor Workspace Enhancement

| # | Task | File(s) | Effort |
|---|------|---------|--------|
| 6.1 | Add AI evaluation reference panel in control testing view | `js/auditor.js` | M |
| 6.2 | Show tribunal justification alongside auditor's test workflow | `js/auditor.js` | M |
| 6.3 | Display AI vs auditor verdict comparison when they differ | `js/auditor.js` | M |
| 6.4 | Allow auditor findings to reference tribunal criteria | `js/auditor.js` | S |
| 6.5 | Add audit trail view (AI said → User decided → because) | `js/auditor.js` | M |

### Phase 7: Cleanup

| # | Task | File(s) | Effort |
|---|------|---------|--------|
| 7.1 | Remove old Lambda-based `startEval`/`pollEval` code paths | `js/api.js` | S |
| 7.2 | Remove `src/agent/`, `src/agent_chat/`, `src/observer/`, `src/preprocessor/`, `src/rag/` | `/compliance/src/` | M |
| 7.3 | Remove CDK infrastructure (Lambda, DynamoDB) | `/compliance/infra/` | M |
| 7.4 | Update `DATA.settings` defaults for production endpoints | `js/data.js` | S |
| 7.5 | Update frontend `README.md` with new architecture | `frontend/README.md` | S |

---

## Effort Legend

- **S** = Small (< 2 hours)
- **M** = Medium (2-4 hours)
- **L** = Large (4-8 hours)

**Total estimated effort:** ~60-80 hours across all phases

**Recommended order:** Phase 1 → 2 → 3 → 4 → 5 → 6 → 7

Phase 1 is a prerequisite for everything else. Phases 2-6 can partially overlap once the API layer is in place.
