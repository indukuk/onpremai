# Investor Pitch Deck

## The Autonomous Compliance Workforce

**Tagline:** Every employee gets an AI agent that does their compliance work for them. Agents talk to each other, the system gets smarter daily, and it deploys anywhere — including air-gapped.

---

## Slide 1: The Problem

### Compliance is a $45B+ market built on human suffering

Every company with sensitive data must prove — repeatedly — that they follow the rules. Today this means:

- **$3-5M/year** per mid-size company on compliance programs that are still 80% manual labor
- **Control owners** (engineers, IT admins, HR) lose 5-10 hours/month doing compliance tasks they don't understand
- **Compliance managers** spend their days chasing people for evidence, not actually managing compliance
- **The most regulated industries** (defense, finance, healthcare, government) — the ones that pay the most — are locked out of modern tooling because their data cannot leave their network

### The "AI compliance" tools of 2025 don't solve this

- **Vanta, Drata, Secureframe**: SaaS dashboards with "AI" stickers. Users still navigate frameworks, still upload evidence, still chase colleagues manually. The AI answers questions — it doesn't do work.
- **IBM OpenPages**: $500K-$2M implementations. 6-10 months to deploy on Red Hat OpenShift. AI is a bolt-on feature (BYOM), not architectural. No one at the company actually *uses* it day-to-day — it's an auditor's database.
- **All of them**: Force the human to understand compliance. Force them to use a platform. Force them to drive the process.

**The fundamental problem isn't the tooling — it's that humans are still doing the work.**

---

## Slide 2: Our Solution

### An autonomous AI workforce that runs your compliance program

We don't give companies a better dashboard. We give every person in the organization an **AI agent that does their compliance work for them** — sends messages, collects evidence, evaluates controls, escalates issues, and coordinates with other agents — without the human ever needing to understand the compliance framework or open a platform.

**The 3 things that make this possible:**

1. **Shadow AI** — Every user gets a personal agent that acts on their behalf
2. **Multi-Agent Coordination** — Agents talk to each other to get work done collaboratively
3. **Self-Improving Evaluation Engine** — 3-layer deterministic + LLM pipeline that gets smarter daily

---

## Slide 3: Shadow AI — The Core Innovation

### Every user gets a personal compliance agent. Zero compliance knowledge required.

**What the user experiences:**

```
Agent → Sarah (Slack):
  "Hey Sarah — I need a Q1 access review export from Okta for your
   CC6.1 control. Want me to ask Mike in IT to pull it, or do you
   have access yourself?"

Sarah → Agent:
  "Ask Mike"

Agent → Mike's Agent:
  [coordinates automatically]

Mike's Agent → Mike (Teams):
  "Sarah needs an Okta access review export. Takes 2 minutes —
   here's exactly how to pull it. Should I walk you through it?"

Mike: pulls the export

Mike's Agent → Sarah's Agent → uploads → evaluates → done.

Sarah never opened the compliance platform.
Mike never heard the word "SOC 2."
Total human effort: 2 messages + 2 minutes.
```

**What the agent does behind the scenes:**
- Translates compliance requirements into plain language actions
- Knows who has the data and how to get it
- Sends messages, emails, and notifications on the user's behalf
- Tracks deadlines and follows up automatically
- Learns each user's communication style, response patterns, and preferences
- Escalates with graduated urgency when things are stuck

---

## Slide 4: Multi-Agent Network

### Agents don't just assist individuals — they form an autonomous workforce

```
┌─────────────────────────────────────────────────────────────────┐
│                    THE AGENT NETWORK                             │
│                                                                 │
│   ┌──────────┐      ┌──────────────┐      ┌──────────────┐    │
│   │CISO Agent│◄────►│CompMgr Agent │◄────►│Owner Agents  │    │
│   │          │      │              │      │(Sarah, John) │    │
│   │Asks:     │      │Orchestrates: │      │              │    │
│   │"Are we   │      │"CC6.1 stuck, │      │Asks other    │    │
│   │ ready?"  │      │ poke Sarah's │      │agents for    │    │
│   │          │      │ agent"       │      │data/evidence │    │
│   └──────────┘      └──────┬───────┘      └───────┬──────┘    │
│                             │                      │            │
│                      ┌──────▼───────┐      ┌──────▼───────┐   │
│                      │Auditor Agent │      │IT/HR/Dev     │   │
│                      │              │      │Agents        │   │
│                      │Requests test │      │              │   │
│                      │evidence from │      │Pull data,    │   │
│                      │all owners'   │      │respond to    │   │
│                      │agents at once│      │requests      │   │
│                      └──────────────┘      └──────────────┘   │
│                                                                 │
│   Every arrow = agent-to-agent communication                    │
│   Humans just approve and answer the occasional question        │
└─────────────────────────────────────────────────────────────────┘
```

**Network effects within each customer:**
- More users onboarded → more agents collaborating → faster compliance
- After 6 months: the compliance program essentially runs itself
- Switching cost is enormous — 20+ personalized agents with learned context aren't portable

---

## Slide 5: How It Actually Works — The Evaluation Engine

### 3-Layer Pipeline: deterministic rules + bounded LLM judgment + deterministic scoring

```
┌─────────────────────────────────────────────────────────────────┐
│ LAYER 1: Deterministic Rules (resolves 60-70% — zero LLM cost) │
│                                                                 │
│   "Do terminated employees still have access?"                  │
│    → Cross-reference terminations.csv with active_users.csv     │
│    → 0 matches? PASS. Matches found? FAIL.                     │
│    → No LLM needed. Instant. Free. 100% reproducible.          │
│                                                                 │
│   8 rule types: file_existence, freshness, schema_presence,     │
│   row_count, null_rate, cross_reference, quantitative,          │
│   keyword_presence                                              │
├─────────────────────────────────────────────────────────────────┤
│ LAYER 2: LLM Judgment (only for ambiguous items)                │
│                                                                 │
│   "Does this policy adequately address data classification?"    │
│    → Bounded question + evidence excerpt + rubric               │
│    → LLM returns: PASS / PARTIAL / FAIL + reason               │
│    → High-weight criteria: 3-sample consensus for reliability   │
│                                                                 │
│   Not "evaluate this entire control" (open-ended, unreliable)   │
│   but "answer this specific question with this rubric" (bounded)│
├─────────────────────────────────────────────────────────────────┤
│ LAYER 3: Deterministic Scoring (always reproducible)            │
│                                                                 │
│   score = sum(weight × value) / assessable_weight               │
│   + Floor rules: policy FAIL caps at 0.84                       │
│   + Floor rules: >25% impl FAIL → force non_compliant          │
│   + Threshold mapping: ≥0.85 compliant, 0.60-0.84 partial      │
│                                                                 │
│   Given same criterion results → always same score. Always.     │
└─────────────────────────────────────────────────────────────────┘
```

**Why this matters:**
- **97-99% reproducible** — auditors can trust it
- **60-70% zero LLM cost** — dramatically cheaper than pure-LLM approaches
- **Fully explainable** — "Rule X passed because Y. LLM judged Z because [reason]."
- **Evidence hash caching** — unchanged evidence = cached result, zero cost re-evaluation

---

## Slide 6: Self-Improving System — The Observer

### The system gets smarter every day without a code deploy

No competitor has this. Our observer agent watches every AI call, detects problems, and fixes them autonomously:

**What it detects:**
| Signal | Meaning | Auto-Fix |
|--------|---------|----------|
| 55% escalation rate on task X | Mid-tier model struggling | Route task to strong tier |
| Confidence trending down over 7 days | Prompt degrading for new patterns | Rewrite prompt via canary test |
| Parse failures > 15% | Model output format drifting | Adjust prompt constraints |
| Cross-tenant score variance > 15% | Potential bias | Alert + investigation |
| Model health check failing | Provider issue | Automatic failover to backup |

**Graduated autonomy — not a loose cannon:**
- **Tier 1 (auto-apply):** Routing changes, threshold adjustments. Confidence ≥ 0.80, min 20 samples.
- **Tier 2 (canary first):** Prompt rewrites, model swaps. Test on 20% traffic, 30+ samples, 4+ hours.
- **Tier 3 (human approval):** Model removal, policy changes. Notifies and waits.
- **Circuit breaker:** 3+ rollbacks in 6 hours → all auto-applies stop, human review required.

**After 6 months in production, our system will be measurably better than on day 1. Every competitor's system will be identical to day 1.**

---

## Slide 7: AI Governance Built In — The System Audits Itself

### For SR 11-7, EU AI Act, and customer trust

Since our system makes compliance assessments that feed audit opinions, it IS an AI model that needs governance. We built that in from day one.

**Automated model governance:**
- Model inventory (every model in routing, automatically tracked)
- Drift detection (KS test on weekly confidence distributions)
- Bias monitoring (cross-tenant score variance flagging)
- Performance trending (per model, per task, over time)
- Decision audit trail (every observer action: what, why, outcome)
- Weekly/monthly governance reports (structured for auditor consumption)

**When the auditor asks "show me your AI governance":**
- Competitors: scramble to write documentation
- **Us: `GET /observer/governance-report` — generated automatically, every week, since deployment**

---

## Slide 8: Deploy Anywhere — First-Class Air-Gapped

### The only AI compliance engine that runs without internet

```
┌──────────────────────────────────────────────────────────┐
│ DEPLOYMENT FLEXIBILITY                                    │
│                                                          │
│  Cloud-Only          Hybrid              Air-Gapped      │
│  ┌──────────┐       ┌──────────┐       ┌──────────┐    │
│  │ All LLMs │       │Local eval│       │Everything│    │
│  │ via API  │       │Cloud for │       │ on-prem  │    │
│  │          │       │ complex  │       │          │    │
│  │ Fastest  │       │ Best of  │       │ Total    │    │
│  │ to start │       │ both     │       │ control  │    │
│  └──────────┘       └──────────┘       └──────────┘    │
│                                                          │
│  All three: same code, same Docker images,               │
│  different config/routing.yaml                           │
│                                                          │
│  Deployment command: docker compose up -d                 │
│  Time to running: < 1 hour (vs. 6-10 months for IBM)     │
└──────────────────────────────────────────────────────────┘
```

**Air-gapped deployment:**
```bash
# On build machine (with internet):
./scripts/package-offline.sh v1.5.0
# → compliance-v1.5.0-offline.tar.gz (images + model weights + config)

# On customer machine (no internet):
tar xzf compliance-v1.5.0-offline.tar.gz && ./install.sh
# Running in under an hour. Zero data leaves the building.
```

**Who needs this (and will pay premium for it):**
- Defense contractors (ITAR, CMMC)
- Government agencies (FedRAMP High, IL4+)
- Critical infrastructure (NERC CIP)
- Banking under EU DORA
- Healthcare with PHI
- Any jurisdiction with data sovereignty laws

---

## Slide 9: Competitive Landscape

### Everyone else is in the bottom-left. We're top-right, alone.

```
                    ↑ AI Sophistication
                    │
                    │  ★ US
                    │  (autonomous multi-agent workforce,
                    │   self-tuning, self-governing,
                    │   deterministic+LLM hybrid)
                    │
                    │         RegScale (on-prem AI, early stage)
                    │
                    │    IBM OpenPages (bolt-on BYOM, massive infra)
                    │
                    │  Vanta/Drata/Scytale
                    │  ("agentic" branding, actually just chatbots)
                    │
                    │  Hyperproof (FedRAMP, rule-based)
                    │
                    │  Eramba (self-hosted, nascent LLM)
                    │
                    └──────────────────────────────────→
                  SaaS-only         Hybrid         Air-gapped
                                              (Deployment Flexibility)
```

**Detailed comparison:**

| Capability | Vanta/Drata | IBM OpenPages | RegScale | **Us** |
|---|---|---|---|---|
| Per-user AI agent | No | No | No | **Yes** |
| Agents talk to each other | No | No | No | **Yes** |
| Agent acts on user's behalf | No | No | No | **Yes** |
| Zero platform knowledge needed | No | No | No | **Yes** |
| Self-tuning AI | No | No | No | **Yes** |
| Self-governing AI | No | No | No | **Yes** |
| Air-gapped deployment | No | Theoretically | Claimed | **Yes, first-class** |
| Deterministic + LLM hybrid | Unknown | No | Unknown | **Yes** |
| 97%+ reproducibility | Unknown | Unknown | Unknown | **Yes** |
| Sub-1-hour deployment | No | No (6-10 months) | Unknown | **Yes** |
| 7 LLM providers supported | No (vendor choice) | No (watsonx only) | Unknown | **Yes** |
| Transparent evaluation logic | No (black box) | No (black box) | No | **Yes** |

---

## Slide 10: How We Win Each Segment

### Three wedges into the market

**Wedge 1: Regulated Mid-Market (Primary Beachhead)**
- 500-5,000 employees in finance, healthcare, defense
- Cannot use SaaS-only tools (data sovereignty)
- Currently: manual processes + spreadsheets + expensive consultants
- Our pitch: "Compliance on autopilot, data never leaves your building"
- Deal size: $100-250K ARR

**Wedge 2: Compliance-Fatigued Tech Companies**
- 200-2,000 employees, already have Vanta/Drata but frustrated
- Control owners ignoring compliance tasks, managers spending all day chasing
- Our pitch: "Your engineers never open the compliance tool again — their agent handles it"
- Deal size: $50-150K ARR (displaces existing tool)

**Wedge 3: Enterprise GRC Modernization**
- 5,000+ employees, currently on IBM/SAP/ServiceNow GRC
- Massive shelfware — bought expensive platform nobody uses
- Our pitch: "Add an AI workforce on top of your existing platform — people actually engage"
- Deal size: $200-500K ARR (complementary layer, not rip-and-replace)

---

## Slide 11: Business Model

### Per-agent SaaS + deployment license for on-prem

| Model | Pricing | Margin |
|---|---|---|
| **Cloud (SaaS)** | $X/user/month (per agent seat) | ~85% gross |
| **Hybrid** | License + per-agent fee | ~75% gross |
| **Air-gapped (on-prem)** | Annual deployment license + support | ~70% gross |

**Revenue expansion within accounts:**
- Start: 5-10 agents (compliance team + key control owners)
- Expand: 50+ agents (all control owners, IT, HR, engineering)
- Full deployment: 200+ agents (whole organization)
- Upsell: additional frameworks (SOC 2 → add ISO 27001 → add HIPAA)
- Upsell: advanced observer features, custom skills, premium support

**Unit economics improve with scale:**
- More agents per tenant = more inter-agent efficiency
- Self-tuning reduces operational cost over time
- Local LLM deployment = zero marginal cost per evaluation after hardware
- Evidence hash caching = repeated evaluations cost nothing

---

## Slide 12: Technology Architecture

### 8 services, independently deployable, one Docker Compose command

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                   │
│  USER LAYER                                                       │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │ Shadow AI Agents (one per user)                              │ │
│  │ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐   │ │
│  │ │ CISO   │ │CompMgr │ │ Sarah  │ │  Mike  │ │Auditor │   │ │
│  │ │ Agent  │◄►│ Agent  │◄►│ Agent  │◄►│ Agent  │ │ Agent  │   │ │
│  │ └────────┘ └────────┘ └────────┘ └────────┘ └────────┘   │ │
│  └────────────────────────────┬────────────────────────────────┘ │
│                               │                                   │
│  AI SERVICES                  │                                   │
│  ┌────────────────────────────▼────────────────────────────────┐ │
│  │ ┌──────────────┐ ┌──────────────┐ ┌─────────────────────┐  │ │
│  │ │  agent-eval  │ │  llm-gateway │ │     observer        │  │ │
│  │ │  (3-layer    │ │  (7 providers│ │  (self-tunes,       │  │ │
│  │ │  evaluation) │ │  routing,    │ │   self-governs)     │  │ │
│  │ │              │ │  escalation) │ │                     │  │ │
│  │ └──────────────┘ └──────────────┘ └─────────────────────┘  │ │
│  │ ┌──────────────┐ ┌──────────────┐ ┌─────────────────────┐  │ │
│  │ │memory-service│ │ preprocessor │ │   sandbox-service   │  │ │
│  │ │(per-user,    │ │ (Excel/PDF/  │ │  (isolated code     │  │ │
│  │ │ per-tenant)  │ │  Word→data)  │ │   execution)        │  │ │
│  │ └──────────────┘ └──────────────┘ └─────────────────────┘  │ │
│  └─────────────────────────────────────────────────────────────┘ │
│                                                                   │
│  INFRASTRUCTURE (customer's environment)                          │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │ PostgreSQL+pgvector │ Redis │ MinIO │ Ollama/vLLM (optional)│ │
│  └─────────────────────────────────────────────────────────────┘ │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
```

**Key architectural decisions:**
- **common/ library**: all agents share the same infrastructure abstraction layer
- **LLM Gateway**: agents declare tasks, not models — swap models in YAML, zero code change
- **Memory service**: per-user context enables personalized agents at scale
- **Observer**: closed-loop optimization, no human in the maintenance loop
- **Docker Compose**: single command deployment, independently versioned services

---

## Slide 13: Defensibility & Moats

### Five layers of competitive advantage

**1. Architectural Moat**
- Multi-agent coordination + self-tuning observer + 3-layer evaluation = 18-24 months to replicate
- Competitors would need to rebuild their architecture from scratch (SaaS dashboards can't become multi-agent systems with a feature release)

**2. Data/Personalization Moat (per customer)**
- After 6 months: 20+ agents with deep user context, learned preferences, interaction patterns
- The system knows "Mike responds faster on Slack, Sarah prefers morning messages, this auditor always asks for 12-month samples"
- Not exportable to a competitor

**3. Self-Improvement Moat (over time)**
- Observer accumulates patterns, optimized prompts, validated routing configurations
- Each month in production = measurable performance improvement vs. competitors that stay static
- Year 1 system dramatically outperforms Day 1 system on same hardware

**4. Regulatory Moat**
- Self-governance feature (model inventory, drift detection, governance reports) becomes table stakes under EU AI Act
- First mover advantage: we ship it from day 1, competitors must retrofit
- The compliance tool that is itself compliant — powerful narrative

**5. Deployment Moat (for air-gapped segment)**
- Once deployed on-prem in a defense contractor or government agency, switching cost is extreme
- Procurement cycles are 12-18 months — once you're in, you're in for 3-5 years minimum
- No competitor can serve these customers today

---

## Slide 14: Market Opportunity

### $12B+ immediately addressable, growing with regulation

**Total Addressable Market (TAM): $45B+**
- Global GRC software market

**Serviceable Addressable Market (SAM): $18B**
- Organizations requiring compliance automation with AI capabilities

**Serviceable Obtainable Market (SOM): $12B**
- Regulated organizations that cannot use SaaS-only tools OR
- Organizations frustrated with current compliance tool engagement rates

**Growth drivers (all tailwinds):**
- **EU AI Act** (2025-2026): mandates AI governance — creates new compliance requirements our system handles natively
- **DORA** (EU finance): data sovereignty requirements pushing banks away from SaaS
- **CMMC 2.0** (US defense): massive compliance burden on defense supply chain (300K+ companies)
- **State privacy laws**: 15+ US states with data protection requirements, growing annually
- **AI proliferation**: more AI in enterprises = more AI governance needed = more demand for our self-governing approach

---

## Slide 15: Go-to-Market

### Land with compliance pain → Expand with agent adoption

**Phase 1 (Months 1-6): Design Partners**
- 3-5 regulated mid-market companies (finance + defense)
- Free/discounted deployment in exchange for feedback and case studies
- Goal: prove the Shadow AI concept reduces compliance effort by 70%+
- Success metric: "control owners never open the platform"

**Phase 2 (Months 6-12): First Revenue**
- Convert design partners to paid
- Launch with SOC 2, ISO 27001, HIPAA frameworks built-in
- Initial sales: warm intros from design partner networks
- Goal: $500K ARR from 5-10 paying customers

**Phase 3 (Months 12-24): Scale**
- Channel partnerships with compliance consultants and auditors
- Enterprise sales team (regulated verticals)
- Framework expansion: CMMC, PCI-DSS, GDPR, SOX, NIST 800-53
- Goal: $3-5M ARR, 30-50 customers

**Sales motion:**
- Pilot: 5-10 agents, single framework, 30-day proof of value
- Expand: roll out to all control owners (agent per person)
- Enterprise: multiple frameworks, full organization deployment

---

## Slide 16: Traction & Current State

### Architecture complete. Implementation starting.

**What's done:**
- Full system architecture designed (8 services, detailed specs)
- 3-layer evaluation pipeline validated in production (existing codebase, AWS-specific)
- LangGraph evaluation engine running (12 nodes, proven on real compliance data)
- Skills/playbooks system designed and partially implemented
- RAG v2 with cross-framework mappings (SOC 2, SOX, NIST, ISO)

**What's needed to reach MVP:**
- Implement the common/ library (infrastructure abstraction layer)
- Build LLM Gateway (model routing, 7 provider adapters)
- Build Memory Service (per-user context, skill storage)
- Refactor existing evaluation engine to use new abstractions
- Build inter-agent communication layer
- Deploy with Docker Compose + first design partner

**Timeline to first deployment: 6 months with current team + funding.**

---

## Slide 17: Team & Ask

### What we need to make this real

**The raise:** $[X]M Seed

**Use of funds:**
| Allocation | Purpose |
|---|---|
| 50% Engineering | 2 ML/AI engineers (observer + evaluation), 2 backend (gateway + memory + inter-agent), 1 frontend (agent communication interfaces) |
| 20% Domain | 1 compliance domain expert (framework library), 1 security/infra (air-gapped deployment hardening) |
| 15% GTM | 1 enterprise sales (regulated verticals), design partner acquisition |
| 15% Ops | Infrastructure, legal, LLM API costs during development |

**Milestones with this raise:**
- Month 3: MVP with Shadow AI + evaluation engine running on Docker Compose
- Month 6: First design partner deployed (regulated mid-market)
- Month 9: Multi-agent coordination live, 3-5 paying customers
- Month 12: Self-tuning observer operational, $500K ARR run rate

---

## Slide 18: The Vision

### Compliance programs that run themselves

**Today (everyone else):** Humans do compliance work, tools help them do it faster.

**Tomorrow (us):** AI agents do compliance work, humans approve and course-correct.

The endgame: a customer deploys our system, onboards their team, and within 30 days the compliance program is running autonomously. Control owners get asked simple questions in plain language on Slack. Evidence flows automatically. Evaluations happen continuously. The CISO gets a daily briefing from their agent. The auditor gets pre-packaged evidence bundles. The compliance manager manages by exception — only stepping in when agents can't resolve something.

**The compliance platform disappears. The agents are the product.**

Nobody needs to learn a tool. Nobody navigates a dashboard. Nobody reads a framework document. The agent handles all of it — and gets better at it every single day.

---

## Appendix A: Technical Differentiation Detail

### Why competitors can't easily replicate this

**The 3-Layer Pipeline Problem:**
- Competitors using pure LLM: non-reproducible results, expensive, unexplainable
- Building deterministic rules requires deep compliance domain expertise (which criteria can be checked programmatically?)
- Our rule engine has 8 specialized rule types tuned for compliance evaluation patterns
- Combining them with bounded LLM judgment (not open-ended) is an architectural choice that's hard to retrofit

**The Observer Problem:**
- Self-tuning requires: structured logs, admin API, canary infrastructure, graduated autonomy policy, circuit breakers, rollback mechanisms
- This is 6+ months of engineering even knowing the design
- It's not a feature you can bolt on — it must be designed into the system from the start

**The Multi-Agent Problem:**
- Requires: per-user memory, inter-agent messaging protocol, skill-based execution, persona system, channel integration (Slack/Teams/email)
- Can't be added to a SaaS dashboard architecture — those are request/response, not agent-based
- The memory model (user/tenant/task/eval/patterns/skills) is designed for this from day 1

**The Air-Gapped Problem:**
- Requires: local LLM support, offline model packaging, zero-cloud-dependency architecture
- SaaS competitors literally cannot serve this market without rebuilding everything
- We can because we designed for it from the start (LLM Gateway abstraction, Docker Compose deployment)

---

## Appendix B: Key Metrics We'll Track

| Metric | What It Proves | Target |
|---|---|---|
| % of compliance tasks completed without human platform access | Shadow AI is working | >80% at 6 months |
| Time from "control assigned" to "evidence submitted" | Multi-agent coordination speeds things up | 70% reduction vs. baseline |
| Evaluation reproducibility | 3-layer pipeline is deterministic | >97% |
| Observer improvements per month | System self-tunes | 5-10 validated changes/month |
| Agent-to-agent messages per compliance cycle | Network effect is real | Growing month-over-month |
| Cost per evaluation (LLM spend) | Deterministic rules save money | 60-70% below pure-LLM approach |
| Control owner NPS | People love not doing compliance manually | >50 (vs. industry ~10) |
| Customer retention (annual) | Personalization moat holds | >95% |

---

## Appendix C: Risk Factors & Mitigations

| Risk | Mitigation |
|---|---|
| LLM quality insufficient for local deployment | 3-layer pipeline means 60-70% doesn't need LLM at all; hybrid mode available for complex tasks |
| Competitors add on-prem deployment | 18-24 month head start; architectural advantage (their SaaS-first code can't easily go on-prem) |
| Regulatory environment changes | Self-governing architecture adapts faster; regulatory monitoring skill detects changes automatically |
| Customer resistance to AI making compliance decisions | Results are always DRAFT until human approves; full audit trail of every decision; transparent evaluation logic |
| Multi-agent coordination complexity | Skills-based architecture keeps agents bounded; agent actions require approval for destructive operations |
| Enterprise sales cycle length | Start with design partners (no procurement); air-gapped segment has fewer vendor options (less competition in deals) |
