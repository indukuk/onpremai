---
marp: true
theme: default
paginate: true
backgroundColor: #1a1a2e
color: #eaeaea
style: |
  section {
    font-family: 'Inter', 'Helvetica Neue', sans-serif;
  }
  h1 {
    color: #00d4aa;
    font-size: 2.2em;
  }
  h2 {
    color: #00d4aa;
    font-size: 1.6em;
  }
  h3 {
    color: #ffffff;
    font-size: 1.2em;
  }
  strong {
    color: #00d4aa;
  }
  table {
    font-size: 0.7em;
  }
  th {
    background-color: #16213e;
    color: #00d4aa;
  }
  td {
    background-color: #0f3460;
  }
  code {
    background-color: #16213e;
    color: #00d4aa;
  }
  pre {
    background-color: #16213e;
    border: 1px solid #0f3460;
  }
  a {
    color: #00d4aa;
  }
  blockquote {
    border-left: 4px solid #00d4aa;
    color: #cccccc;
  }
  .columns {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 1em;
  }
---

<!-- _class: lead -->
<!-- _backgroundColor: #0f0f23 -->

# The Autonomous Compliance Workforce

## Every employee gets an AI agent that does their compliance work for them

Agents talk to each other. The system gets smarter daily.
Deploys anywhere — including air-gapped.

---

# The Problem

### Compliance is a $45B+ market built on human suffering

- **$3-5M/year** per mid-size company — still 80% manual labor
- **Control owners** lose 5-10 hrs/month on tasks they don't understand
- **Compliance managers** spend days chasing people, not managing compliance
- **Most regulated industries** (defense, finance, healthcare) are locked out of modern tooling — data can't leave their network

---

# The "AI Compliance" Tools of 2025 Don't Solve This

| Platform | What They Actually Do |
|---|---|
| **Vanta, Drata, Secureframe** | SaaS dashboards with "AI" stickers. Users still navigate frameworks, still upload evidence, still chase colleagues. |
| **IBM OpenPages** | $500K-$2M, 6-10 month deploys on Red Hat OpenShift. AI is bolt-on. Nobody uses it day-to-day. |
| **All of them** | Force humans to understand compliance. Force them to use a platform. Force them to drive the process. |

<br>

> **The fundamental problem isn't the tooling — it's that humans are still doing the work.**

---

<!-- _backgroundColor: #0f3460 -->

# Our Solution

## An autonomous AI workforce that runs your compliance program

We don't give companies a better dashboard.

We give every person an **AI agent that does their compliance work for them** — sends messages, collects evidence, evaluates controls, escalates issues, and coordinates with other agents.

**The human never needs to understand compliance or open a platform.**

---

# What Makes This Possible

### Three innovations, integrated from day one

<br>

| | Innovation | What It Means |
|:---:|---|---|
| **1** | **Shadow AI** | Every user gets a personal agent that acts on their behalf |
| **2** | **Multi-Agent Coordination** | Agents talk to each other to get work done collaboratively |
| **3** | **Self-Improving Engine** | 3-layer deterministic + LLM pipeline that gets smarter daily |

---

# Shadow AI — The Core Innovation

### Every user gets a personal compliance agent. Zero knowledge required.

```
Agent → Sarah (Slack):
  "Hey Sarah — I need a Q1 access review export from Okta.
   Want me to ask Mike in IT, or do you have access?"

Sarah: "Ask Mike"

Agent → Mike's Agent: [coordinates automatically]

Mike's Agent → Mike (Teams):
  "Sarah needs an Okta export. Takes 2 min —
   here's how. Want me to walk you through it?"

Mike: pulls the export

Mike's Agent → Sarah's Agent → uploads → evaluates → done.
```

**Sarah never opened the compliance platform. Mike never heard "SOC 2."**
**Total human effort: 2 messages + 2 minutes.**

---

# What the Agent Does Behind the Scenes

<br>

- Translates compliance requirements into **plain language actions**
- Knows **who has the data** and how to get it
- Sends messages, emails, notifications **on the user's behalf**
- Tracks deadlines and **follows up automatically**
- Learns each user's **communication style and preferences**
- Escalates with **graduated urgency** when things are stuck
- **Gets better over time** — learns what works for each person

<br>

> The agent IS the interface. The platform disappears.

---

# Multi-Agent Network

### Agents don't just assist — they form an autonomous workforce

```
  ┌──────────┐      ┌──────────────┐      ┌──────────────┐
  │CISO Agent│◄────►│CompMgr Agent │◄────►│Owner Agents  │
  │          │      │              │      │(Sarah, John) │
  │"Are we   │      │"CC6.1 stuck, │      │              │
  │ ready?"  │      │ poke Sarah"  │      │Ask others    │
  └──────────┘      └──────┬───────┘      └───────┬──────┘
                           │                      │
                    ┌──────▼───────┐      ┌──────▼───────┐
                    │Auditor Agent │      │IT/HR/Dev     │
                    │              │      │Agents        │
                    │Requests test │      │Pull data,    │
                    │evidence from │      │respond to    │
                    │all at once   │      │requests      │
                    └──────────────┘      └──────────────┘
```

Every arrow = **agent-to-agent communication**
Humans just approve and answer the occasional question.

---

# Network Effects Within Each Customer

<br>

### More agents = faster compliance = higher switching cost

- **5 agents**: basic coordination, some automated evidence flow
- **20 agents**: compliance program runs semi-autonomously
- **50+ agents**: full autonomous workforce, humans manage by exception

<br>

### After 6 months:
- 20+ agents with deep personalized context
- Learned preferences not exportable to a competitor
- The system knows "Mike responds faster on Slack, Sarah prefers morning pings"

---

# The Evaluation Engine

## 3-Layer Pipeline: Rules → LLM Judgment → Deterministic Score

| Layer | What | Cost | Reproducibility |
|:---:|---|:---:|:---:|
| **1** | Deterministic rules (8 types) | $0 | 100% |
| **2** | Bounded LLM judgment (ambiguous items only) | Low | High |
| **3** | Deterministic scoring formula | $0 | 100% |

<br>

**60-70% of criteria resolve in Layer 1 — zero LLM cost**

Layer 2 asks specific questions with rubrics, not "evaluate this entire control"

Layer 3 always produces the same score given same inputs. Always.

---

# Layer 1 Example

### "Do terminated employees still have access?"

```
Rule type: cross_reference

Input:  terminations.csv × active_users.csv
Check:  any terminated employee in active access list?
Result: 0 matches → PASS (instant, free, 100% reproducible)
        matches found → FAIL (with exact names)
```

### No LLM needed. No token cost. No variability.

8 rule types: `file_existence`, `freshness`, `schema_presence`,
`row_count`, `null_rate`, `cross_reference`, `quantitative`, `keyword_presence`

---

# Why This Matters

<br>

| Metric | Pure LLM (competitors) | Our 3-Layer Pipeline |
|---|:---:|:---:|
| Reproducibility | ~70-80% | **97-99%** |
| Cost per evaluation | $$$ (every criteria hits LLM) | **$** (60-70% free) |
| Explainability | "AI said compliant" | **"Rule X passed because Y"** |
| Speed | Seconds per criterion | **Milliseconds** (rules) |
| Audit trail | Black box | **Every step traceable** |

<br>

> Auditors can trust it. CFOs can afford it. Regulators can inspect it.

---

# Self-Improving System — The Observer

### Gets smarter every day. No code deploy needed.

| Signal | Meaning | Auto-Fix |
|---|---|---|
| 55% escalation rate | Model struggling | Route to stronger tier |
| Confidence trending ↓ | Prompt degrading | Rewrite via canary test |
| Parse failures >15% | Output format drift | Adjust constraints |
| Score variance >15% | Potential bias | Alert + investigation |
| Health check failing | Provider issue | Automatic failover |

<br>

**After 6 months: measurably better than day 1.**
**Competitors: identical to day 1.**

---

# Graduated Autonomy — Not a Loose Cannon

<br>

| Tier | What | Safety |
|:---:|---|---|
| **1 — Auto-apply** | Routing changes, thresholds | Confidence ≥ 0.80, 20+ samples |
| **2 — Canary first** | Prompt rewrites, model swaps | 20% traffic, 30+ samples, 4+ hrs |
| **3 — Human approval** | Model removal, policy changes | Notify and wait |

<br>

**Circuit breaker:** 3+ rollbacks in 6 hours → all auto-applies stop

The system improves aggressively but fails safely.

---

# AI Governance Built In

### The system audits itself. For SR 11-7, EU AI Act, and customer trust.

**Automated model governance (no human maintenance):**
- Model inventory — auto-tracked from routing config
- Drift detection — KS test on weekly confidence distributions
- Bias monitoring — cross-tenant score variance flagging
- Performance trending — per model, per task, over time
- Decision audit trail — every observer action: what, why, outcome
- Weekly/monthly governance reports — structured for auditors

<br>

> **Auditor: "Show me your AI governance."**
> **Us:** `GET /observer/governance-report` — generated automatically since deployment.

---

# Deploy Anywhere — First-Class Air-Gapped

<br>

| Cloud-Only | Hybrid | Air-Gapped |
|:---:|:---:|:---:|
| All LLMs via API | Local eval, cloud for complex | Everything on-prem |
| Fastest to start | Best of both | Total data control |

<br>

**Same code. Same Docker images. Different `routing.yaml`.**

```bash
# Air-gapped deployment:
tar xzf compliance-v1.5.0-offline.tar.gz && ./install.sh
# Running in under 1 hour. Zero data leaves the building.
```

vs. IBM OpenPages: 6-10 months on Red Hat OpenShift

---

# Who Needs Air-Gapped (And Will Pay Premium)

<br>

- **Defense contractors** — ITAR, CMMC
- **Government agencies** — FedRAMP High, IL4+
- **Critical infrastructure** — NERC CIP
- **Banking under EU DORA** — data sovereignty mandates
- **Healthcare with PHI** — can't risk cloud exposure
- **Any jurisdiction with data sovereignty laws**

<br>

### These buyers have money AND compliance obligations — but zero options from Vanta, Drata, or Secureframe.

---

<!-- _backgroundColor: #16213e -->

# Competitive Landscape

```
                ↑ AI Sophistication

                │  ★ US (autonomous multi-agent workforce,
                │       self-tuning, self-governing)
                │
                │       RegScale (on-prem AI, early)
                │
                │    IBM OpenPages (bolt-on BYOM, massive infra)
                │
                │  Vanta/Drata/Scytale ("agentic" branding)
                │
                │  Hyperproof (FedRAMP, rule-based)
                │
                │  Eramba (self-hosted, nascent LLM)
                │
                └────────────────────────────────────────→
              SaaS-only        Hybrid        Air-gapped
```

**We're top-right. Alone.**

---

# Head-to-Head Comparison

| Capability | Vanta/Drata | IBM OpenPages | **Us** |
|---|:---:|:---:|:---:|
| Per-user AI agent | No | No | **Yes** |
| Agents talk to each other | No | No | **Yes** |
| Agent acts on user's behalf | No | No | **Yes** |
| Zero platform knowledge needed | No | No | **Yes** |
| Self-tuning AI | No | No | **Yes** |
| Self-governing AI | No | No | **Yes** |
| Air-gapped deployment | No | Theoretically | **Yes** |
| 97%+ reproducibility | Unknown | Unknown | **Yes** |
| Sub-1-hour deployment | No | No (6-10 months) | **Yes** |
| 7 LLM providers | No | No (watsonx) | **Yes** |
| Transparent evaluation | No | No | **Yes** |

---

# Three Market Wedges

### Wedge 1: Regulated Mid-Market (Beachhead)
500-5,000 employees in finance, healthcare, defense
*"Compliance on autopilot, data never leaves your building"*
**$100-250K ARR**

### Wedge 2: Compliance-Fatigued Tech
200-2,000 employees, frustrated with Vanta/Drata engagement
*"Your engineers never open the compliance tool again"*
**$50-150K ARR**

### Wedge 3: Enterprise GRC Modernization
5,000+ on IBM/SAP/ServiceNow — massive shelfware
*"Add an AI workforce on top — people actually engage"*
**$200-500K ARR**

---

# Business Model

### Per-agent pricing + deployment license

| Model | Pricing | Gross Margin |
|---|---|:---:|
| **Cloud (SaaS)** | $/user/month | ~85% |
| **Hybrid** | License + per-agent fee | ~75% |
| **Air-gapped** | Annual license + support | ~70% |

<br>

**Expansion within accounts:**
5 agents → 50 agents → 200+ agents (whole org)
+ Additional frameworks (SOC 2 → ISO 27001 → HIPAA → CMMC)

**Unit economics improve with scale** — self-tuning reduces ops cost, local LLMs = zero marginal cost, hash caching = repeat evals free

---

# Technology Architecture

```
┌─────────────────────────────────────────────────────────┐
│ SHADOW AI AGENTS (one per user)                          │
│ [CISO] ◄► [CompMgr] ◄► [Sarah] ◄► [Mike] ◄► [Auditor] │
├─────────────────────────────────────────────────────────┤
│ AI SERVICES                                              │
│ agent-eval │ llm-gateway │ observer                      │
│ memory-svc │ preprocessor │ sandbox-svc                  │
├─────────────────────────────────────────────────────────┤
│ INFRASTRUCTURE (customer's environment)                  │
│ PostgreSQL+pgvector │ Redis │ MinIO │ Ollama/vLLM        │
└─────────────────────────────────────────────────────────┘
```

8 services. Independently deployable. One `docker compose up -d`.

---

# Five Moats

<br>

| # | Moat | Why It's Hard to Replicate |
|:---:|---|---|
| 1 | **Architecture** | Multi-agent + observer + 3-layer = 18-24mo to build |
| 2 | **Personalization** | 20+ agents with learned context per customer, not exportable |
| 3 | **Self-Improvement** | Year 1 system outperforms Day 1 on same hardware |
| 4 | **Regulatory** | Self-governance = table stakes under EU AI Act (we're first) |
| 5 | **Deployment** | Once in an air-gapped org, you're in for 3-5 years minimum |

---

# Market Opportunity

<br>

| | Size | Description |
|---|:---:|---|
| **TAM** | $45B+ | Global GRC software market |
| **SAM** | $18B | Orgs needing AI compliance automation |
| **SOM** | $12B | Can't use SaaS-only OR frustrated with engagement |

<br>

**Tailwinds:**
- EU AI Act (2025-2026) — mandates AI governance we handle natively
- DORA — pushing EU banks away from SaaS
- CMMC 2.0 — 300K+ defense companies need compliance automation
- 15+ US state privacy laws and growing

---

# Go-to-Market

<br>

### Phase 1 (Mo 1-6): Design Partners
3-5 regulated mid-market. Prove 70%+ effort reduction.
*Success metric: control owners never open the platform.*

### Phase 2 (Mo 6-12): First Revenue
Convert partners. SOC 2 + ISO 27001 + HIPAA built-in.
*Goal: $500K ARR from 5-10 customers.*

### Phase 3 (Mo 12-24): Scale
Channel partnerships. Enterprise sales. Framework expansion.
*Goal: $3-5M ARR, 30-50 customers.*

---

# Traction & Current State

### Architecture complete. Implementation starting.

**Done:**
- Full 8-service architecture designed with detailed specs
- 3-layer evaluation pipeline validated on real compliance data
- LangGraph engine running (12 nodes, production-proven)
- Skills/playbooks system designed
- RAG v2 with cross-framework mappings

**Needed for MVP:**
- common/ library, LLM Gateway, Memory Service
- Refactor existing engine to new abstractions
- Inter-agent communication layer
- Docker Compose deployment + first design partner

**Timeline: 6 months to first deployment.**

---

# The Ask

### $[X]M Seed

| Allocation | Purpose |
|---|---|
| **50% Engineering** | 2 ML/AI + 2 backend + 1 frontend |
| **20% Domain** | 1 compliance expert + 1 security/infra |
| **15% GTM** | 1 enterprise sales + design partner acquisition |
| **15% Ops** | Infrastructure, legal, LLM costs |

**Milestones:**
- Month 3: MVP running on Docker Compose
- Month 6: First design partner deployed
- Month 9: Multi-agent coordination live, 3-5 paying
- Month 12: Observer operational, $500K ARR run rate

---

<!-- _class: lead -->
<!-- _backgroundColor: #0f0f23 -->

# The Vision

<br>

**Today (everyone else):**
Humans do compliance work. Tools help them do it faster.

**Tomorrow (us):**
AI agents do compliance work. Humans approve and course-correct.

<br>

> **The compliance platform disappears.**
> **The agents are the product.**

Nobody learns a tool. Nobody navigates a dashboard.
Nobody reads a framework document. The agent handles all of it —
and gets better at it every single day.

---

<!-- _backgroundColor: #16213e -->

# Appendix A: Why Competitors Can't Replicate This

<br>

**The 3-Layer Pipeline Problem**
Building deterministic rules needs deep compliance domain expertise. Combining with bounded LLM judgment is architectural — hard to retrofit onto pure-LLM systems.

**The Observer Problem**
Self-tuning needs structured logs, admin API, canary infra, graduated autonomy, circuit breakers, rollback. 6+ months even knowing the design. Must be built in from start.

**The Multi-Agent Problem**
Needs per-user memory, inter-agent messaging, skill execution, persona system, channel integration. Can't bolt onto a SaaS dashboard architecture.

**The Air-Gapped Problem**
Needs local LLM support, offline packaging, zero-cloud-dependency. SaaS competitors would rebuild everything.

---

# Appendix B: Key Metrics

| Metric | Target |
|---|---|
| Tasks completed without platform access | >80% at 6 months |
| Time: assigned → evidence submitted | 70% reduction |
| Evaluation reproducibility | >97% |
| Observer improvements/month | 5-10 validated |
| Agent-to-agent messages/cycle | Growing MoM |
| Cost per evaluation vs. pure-LLM | 60-70% lower |
| Control owner NPS | >50 (vs. industry ~10) |
| Annual retention | >95% |

---

# Appendix C: Risk & Mitigation

| Risk | Mitigation |
|---|---|
| Local LLM quality | 60-70% doesn't need LLM; hybrid mode for complex |
| Competitors add on-prem | 18-24mo head start; SaaS-first can't easily go on-prem |
| Regulatory changes | Self-governing adapts; regulatory skill auto-detects |
| AI trust concerns | Always DRAFT until human approves; full audit trail |
| Multi-agent complexity | Skills keep agents bounded; approval for destructive ops |
| Long enterprise sales | Design partners first; air-gapped = fewer vendor options |
