# High-Level Diagrams for Slides

## 1. Agent-to-Agent Communication

```mermaid
flowchart LR
    subgraph Users["User Layer"]
        U1["Compliance Manager"]
        U2["Contributor"]
        U3["Auditor"]
    end

    subgraph Agents["Shadow AI Agents"]
        SA1[Shadow Agent<br/>CM's Agent]
        SA2[Shadow Agent<br/>Contributor Agent]
        SA3[Shadow Agent<br/>Auditor Agent]
    end

    subgraph Platform["Platform Services"]
        direction TB
        REG[Agent Registry<br/>Discovery + Health]
        GW[LLM Gateway<br/>Task Routing]
        MEM[Shared Memory<br/>pgvector + Redis]
    end

    subgraph Workers["Specialist Agents"]
        AE[Evaluation Agent<br/>3-Layer Pipeline]
        VR[Vendor Risk Agent]
        OBS[Observer Agent<br/>Self-Improving]
    end

    U1 --> SA1
    U2 --> SA2
    U3 --> SA3

    SA1 <-->|"delegate task"| REG
    SA2 <-->|"delegate task"| REG
    SA3 <-->|"delegate task"| REG

    REG -->|"route to capable agent"| AE
    REG -->|"route to capable agent"| VR
    REG -->|"route to capable agent"| OBS

    SA1 <-.->|"nudge: evidence overdue"| SA2
    SA1 <-.->|"notify: eval complete"| SA3

    AE --> GW
    VR --> GW
    AE --> MEM
    VR --> MEM
    SA1 --> MEM
    SA2 --> MEM
    SA3 --> MEM

    style REG fill:#4f8ff7,color:#fff
    style GW fill:#a371f7,color:#fff
    style MEM fill:#3fb950,color:#fff
```

---

## 2. Agent Communication Protocol (Sequence)

```mermaid
sequenceDiagram
    participant CM as CM's Shadow Agent
    participant REG as Agent Registry
    participant EVAL as Evaluation Agent
    participant GW as LLM Gateway
    participant MEM as Shared Memory

    Note over CM: "Evaluate CC6.1 for SOC 2"

    CM->>REG: discover(task="evaluate_control")
    REG-->>CM: [{agent: eval-01, health: healthy, load: 30%}]

    CM->>EVAL: delegate(control_id="CC6.1", jwt=original_user_jwt)
    Note over EVAL: JWT propagated — tenant isolation enforced

    EVAL->>MEM: recall(tenant_id, "CC6.1 evidence")
    MEM-->>EVAL: evidence_files[], prior_eval

    EVAL->>GW: complete(task="evaluate_control", messages=[...])
    Note over GW: Routes to Bedrock Claude (strong tier)
    GW-->>EVAL: evaluation_result

    EVAL->>MEM: store(eval_result, score=0.92)
    EVAL-->>CM: {status: compliant, score: 92%}

    CM->>MEM: notify(auditor_agent, "CC6.1 eval ready")
    Note over CM: Inter-agent nudge via shared memory
```

---

## 3. Adversarial Tribunal — Reducing Hallucinations

```mermaid
flowchart LR
    EV["Evidence +\nRAG Criteria"] --> PROS

    subgraph Tribunal["Adversarial Tribunal"]
        direction LR
        PROS["Prosecutor\nArgues FAIL"] --> JUDGE["Judge\nWeighs both"]
        DEF["Defender\nArgues PASS"] --> JUDGE
    end

    JUDGE -->|"Confidence >= 70%"| VERDICT["Verdict +\nCited Reasoning"]
    JUDGE -->|"Confidence < 70%"| RETRY["Second Tribunal\nDifferent Framing"]
    RETRY -->|"Still disagree"| HUMAN["Flag for\nHuman Review"]

    EV --> DEF

    style Tribunal fill:#3a2a00,stroke:#d29922,color:#e6edf3
```

**Key anti-hallucination rules:**
- Prosecutor and Defender work **independently** — neither sees the other's arguments
- Judge must **cite specific evidence** for every point accepted or rejected
- Low confidence → automatic retry; persistent disagreement → human escalation, never a guess

---

## 4. RAG Pipeline — Policy Graph Retrieval for Evaluation

```mermaid
flowchart LR
    subgraph Ingestion["Policy Ingestion"]
        PDF["Policy PDF"] --> PP["Preprocessor"]
        PP --> CHUNK["Late Chunking +\nEmbeddings"]
        PP --> GRAPH["Graph Extraction"]
        CHUNK --> STORE[("pgvector")]
        GRAPH --> LEIDEN["Community\nDetection"] --> STORE
    end

    subgraph Retrieval["Evaluation-Time Retrieval"]
        QUERY["Query: CC6.1\nrequirements"] --> VEC["Vector Search"]
        QUERY --> GW["Graph Walk"]
        QUERY --> COM["Community\nContext"]
        VEC --> MERGE["Merge + Rank"]
        GW --> MERGE
        COM --> MERGE
        MERGE --> CRITERIA["Testing Criteria\nwith weights"]
    end

    subgraph Eval["Feeds Evaluation"]
        CRITERIA --> PROS2["Prosecutor"]
        CRITERIA --> DEF2["Defender"]
        CRITERIA --> RULES2["Rule Engine"]
    end

    style Ingestion fill:#1a2a3a,stroke:#4f8ff7,color:#e6edf3
    style Retrieval fill:#1a3a1a,stroke:#3fb950,color:#e6edf3
    style Eval fill:#3a2a00,stroke:#d29922,color:#e6edf3
```

---

## 5. Full Evaluation Flow — RAG + Tribunal Combined

```mermaid
flowchart TD
    START(["Evaluate CC6.1"]) --> RAG

    subgraph RAG["RAG Retrieval"]
        direction LR
        R1["Policy Graph"] --> R3["11 Testing Criteria\nwith weights"]
        R2["Vector Search"] --> R3
    end

    RAG --> RULES

    subgraph RULES["Layer 1: Deterministic Rules"]
        direction LR
        RESOLVED["8 criteria resolved\nPASS/FAIL"] 
        UNRESOLVED["3 criteria\nNEEDS JUDGMENT"]
    end

    RESOLVED --> SCORE
    UNRESOLVED --> TRIBUNAL

    subgraph TRIBUNAL["Layer 2: Adversarial Tribunal"]
        direction LR
        P["Prosecutor"] --> J["Judge"]
        D["Defender"] --> J
    end

    TRIBUNAL --> SCORE

    subgraph SCORE["Layer 3: Deterministic Scoring"]
        CALC["Weighted sum + Floor rules"]
        RESULT["92% — Compliant"]
        CALC --> RESULT
    end

    style RAG fill:#1a3a1a,stroke:#3fb950,color:#e6edf3
    style RULES fill:#1a2a3a,stroke:#4f8ff7,color:#e6edf3
    style TRIBUNAL fill:#3a2a00,stroke:#d29922,color:#e6edf3
    style SCORE fill:#2a1a2a,stroke:#a371f7,color:#e6edf3
```

---

## 6. Why the Tribunal Eliminates Hallucination

```mermaid
flowchart LR
    subgraph Problem["Traditional LLM Eval"]
        SINGLE["Single LLM call:\nIs this compliant?"]
        SINGLE --> RISK1["Confirmation bias"]
        SINGLE --> RISK2["Plausible but wrong"]
        SINGLE --> RISK3["No evidence grounding"]
    end

    subgraph Solution["Our Approach"]
        S1["Rules resolve 60-70%\nZero LLM"] --> S2["Prosecutor argues FAIL"]
        S2 --> S4["Judge cites evidence\nfor each point"]
        S3["Defender argues PASS"] --> S4
        S4 --> S5["Low confidence?\nRetry or escalate"]
    end

    Problem -.->|"replaced by"| Solution

    style Problem fill:#3a1a1a,stroke:#f85149,color:#e6edf3
    style Solution fill:#1a3a1a,stroke:#3fb950,color:#e6edf3
```
