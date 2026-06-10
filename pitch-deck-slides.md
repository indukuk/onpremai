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

## Every User gets an AI agent that does their compliance work for them

Agents talk to each other. The system gets smarter daily.
Deploys anywhere — including air-gapped.

---

# The Problem

### Compliance is a $45B+ market built on human Powered Work

- **$3-5M/year** per mid-size company — still 80% manual labor
- **Control owners** lose 5-10 hrs/month on tasks they don't understand
- **Compliance managers** spend days chasing people, not managing compliance
- **Most regulated industries** (defense, finance, healthcare) are locked out of modern tooling — data can't leave their network

---

<!-- _backgroundColor: #0f3460 -->

# Our Solution

## An autonomous AI workforce that runs your compliance program

We don't give companies a better dashboard.

We give every person an **AI agent that does their compliance work for them** — sends messages, collects evidence, evaluates controls, escalates issues, and coordinates with other agents.

**The Users never needs to understand how our platform works**

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
   here's how."

Mike: pulls the export → Agent uploads → evaluates → done.
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
  [CISO Agent] ◄──► [CompMgr Agent] ◄──► [Owner Agents (Sarah, John)]
                           │                         │
                    [Auditor Agent]          [IT/HR/Dev Agents]
```

Every arrow = **agent-to-agent communication**
Humans just approve and answer the occasional question.

- **5 agents**: basic coordination, some automated evidence flow
- **20 agents**: compliance program runs semi-autonomously
- **50+ agents**: full autonomous workforce, humans manage by exception

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
| All LLMs deployed on AWS | Local eval, cloud for complex | Everything on-prem |
| Fastest to start | Best of both | Total data control |

<br>

**Same code. Same Docker images. Different `routing.yaml`.**

```bash
# Air-gapped deployment:
tar xzf compliance-v1.5.0-offline.tar.gz && ./install.sh
# Zero data leaves the building.
```

---

# On-Premises Infrastructure Requirements

### Application Tier (CPU-only VMs)

| VM | Spec | Role | Est. Cost/mo |
|---|---|---|:---:|
| **App VM 1** | 8 vCPU, 32 GB RAM, 200 GB SSD | All 8 services (Docker Compose) | ~$300 |
| **App VM 2** | 8 vCPU, 32 GB RAM, 200 GB SSD | HA replica / horizontal scale | ~$300 |
| **DB VM** | 8 vCPU, 64 GB RAM, 1 TB NVMe | PostgreSQL + pgvector, Redis, MinIO | ~$500 |

### LLM Tier (GPU VMs) — separate from app tier

| VM | Spec | Models Hosted | Est. Cost/mo |
|---|---|---|:---:|
| **LLM Strong** | 4× A100 80GB (or 2× H100) | DeepSeek-V3 / Qwen-72B (1M context) | ~$8,000-12,000 |
| **LLM Mid** | 1× A100 80GB (or 2× A6000) | Mistral-22B / Qwen-32B | ~$2,500-4,000 |
| **LLM Fast** | 1× A10 24GB (or RTX 4090) | Phi-3 / Qwen-7B / Llama-8B | ~$500-1,000 |

<br>

### Why multiple LLMs?

- **Strong (1M context):** Complex policy analysis, long document reasoning, multi-evidence synthesis
- **Mid:** Standard evaluations, evidence review, agent coordination
- **Fast:** Classification, routing, simple checks (60-70% of all calls) — rules handle the rest free

**Total on-prem footprint: 5-6 VMs, ~$12K-18K/mo** (vs. $50K-100K/yr SaaS + data sovereignty risk)

---

# Architecture: AWS Deployment

```
  EXTERNAL INTEGRATIONS                     AWS CLOUD
 ┌────────────────────┐   ┌──────────────────────────────────────────────┐
 │                    │   │                                              │
 │ ┌──────────────┐  │   │  ┌─────────────────────────────────────┐    │
 │ │ IDENTITY     │  │   │  │  ECS Fargate (private subnets)       │    │
 │ │              │  │   │  │                                      │    │
 │ │ Azure AD ────┼──┼──►│  │  llm-gateway ─► Bedrock (LLMs)      │    │
 │ │ Okta    ────┼──┼──►│  │  agent-eval    compliance-assistant  │    │
 │ │ SAML/OIDC   │  │   │  │  memory-svc    observer              │    │
 │ └──────────────┘  │   │  │  preprocessor  sandbox-svc           │    │
 │                    │   │  └──────────┬──────────────────────────┘    │
 │ ┌──────────────┐  │   │             │                               │
 │ │ COMMS        │  │   │  ┌──────────▼──────────────────────────┐    │
 │ │              │  │   │  │  MANAGED SERVICES                    │    │
 │ │ Slack   ◄───┼──┼───│  │  Cognito (federated IdP)             │    │
 │ │ Teams   ◄───┼──┼───│  │  RDS Postgres + pgvector             │    │
 │ │ Email/SES   │  │   │  │  S3 (evidence artifacts)             │    │
 │ └──────────────┘  │   │  │  ElastiCache Redis                   │    │
 │                    │   │  │  Secrets Manager (HMAC, API keys)    │    │
 │ ┌──────────────┐  │   │  │  Cloud Map (service discovery)       │    │
 │ │ CUSTOMER APPS│  │   │  │  VPC + ALB + PrivateLink + VPN       │    │
 │ │              │  │   │  │  Bedrock LLM and Agents              │    │
 │ │ Jira     ◄──┼──┼───│  └──────────────────────────────────────┘    │
 │ │ ServiceNow◄─┼──┼───│                                              │
 │ │ Splunk   ◄──┼──┼───│                                              │
 │ │ Workday  ◄──┼──┼───│                                              │
 │ └──────────────┘  │   │                                              │
 │                    │   │                                              │
 │ ┌──────────────┐  │   │                                              │
 │ │ FILE STORAGE │  │   │                                              │
 │ │              │  │   │                                              │
 │ │ SharePoint◄──┼──┼───│                                              │
 │ │ Google Drv◄──┼──┼───│                                              │
 │ │ Box/Dropbox  │  │   │                                              │
 │ │ Confluence◄──┼──┼───│                                              │
 │ └──────────────┘  │   │                                              │
 └────────────────────┘   └──────────────────────────────────────────────┘
```

---

# Architecture: Fully On-Premises (Air-Gapped)

```
 ┌─────────────────────────────────────────────────────────────────────────┐
 │  CUSTOMER DATA CENTER — nothing leaves this boundary                     │
 │                                                                          │
 │  ┌──────────────────┐   ┌──────────────────────────────────────────┐    │
 │  │ IDENTITY         │   │  Docker Compose / K8s (app tier)          │    │
 │  │                  │   │                                           │    │
 │  │ Active Directory─┼──►│  llm-gateway ──► Ollama / vLLM (GPU)     │    │
 │  │ LDAP            ─┼──►│  agent-eval     compliance-assistant     │    │
 │  │ Keycloak (OIDC) ─┼──►│  memory-svc     observer                 │    │
 │  │                  │   │  preprocessor   sandbox-svc               │    │
 │  └──────────────────┘   └──────────┬───────────────────────────────┘    │
 │                                     │                                    │
 │  ┌──────────────────┐   ┌──────────▼───────────────────────────────┐    │
 │  │ COMMS (internal) │   │  SELF-HOSTED INFRA                        │    │
 │  │                  │   │                                           │    │
 │  │ Teams (on-prem)◄─┼───│  PostgreSQL + pgvector                    │    │
 │  │ SMTP relay    ◄──┼───│  MinIO (S3-compatible)                    │    │
 │  │ Mattermost   ◄───┼───│  Redis                                    │    │
 │  │ Cisco Webex  ◄───┼───│  Tesseract (OCR)                          │    │
 │  └──────────────────┘   │  HashiCorp Vault (secrets)                │    │
 │                          │  Internal DNS (service discovery)         │    │
 │  ┌──────────────────┐   └──────────────────────────────────────────┘    │
 │  │ CUSTOMER APPS    │                                                    │
 │  │                  │   ┌──────────────────────────────────────────┐    │
 │  │ Jira Server   ◄──┼───│  NETWORK                                  │    │
 │  │ ServiceNow   ◄───┼───│                                           │    │
 │  │ Archer/RSA   ◄───┼───│  Reverse proxy (nginx/HAProxy)            │    │
 │  │ SAP GRC      ◄───┼───│  Internal firewall (no egress)            │    │
 │  │ Workday HCM  ◄───┼───│  mTLS between services                    │    │
 │  └──────────────────┘   │  Air-gap: no internet, no cloud calls     │    │
 │                          └──────────────────────────────────────────┘    │
 │  ┌──────────────────┐                                                    │
 │  │ FILE STORAGE     │   Install: tar xzf release.tar.gz && ./install.sh │
 │  │                  │   Update:  sneakernet USB or internal mirror       │
 │  │ NFS / CIFS    ◄──┼───────────────────────────────────────────────     │
 │  │ SharePoint   ◄───┼───────────────────────────────────────────────     │
 │  │ Documentum   ◄───┼───────────────────────────────────────────────     │
 │  │ Network drives   │                                                    │
 │  └──────────────────┘                                                    │
 └─────────────────────────────────────────────────────────────────────────┘
```

**Same 8 services. Same code. Zero data exfiltration risk.**

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
