# Deployment Architecture — On-Prem & AWS

## Overview

This document provides high-level architecture diagrams for both deployment modes. The same Docker images deploy to both environments — only infrastructure configuration changes via environment variables.

---

## On-Premises Architecture (Docker Compose)

### Network Topology

```mermaid
graph TB
    subgraph Internet["Internet"]
        USER[("👤 Users<br/>(Browser/API)")]
    end

    subgraph Firewall["Enterprise Firewall / Reverse Proxy"]
        FW[["🔥 Firewall<br/>WAF / IDS / IPS<br/>TLS Termination<br/>Rate Limiting"]]
    end

    subgraph DMZ["DMZ (Optional)"]
        RP[["Reverse Proxy<br/>(nginx / Traefik)<br/>:443 HTTPS<br/>mTLS to backend"]]
    end

    subgraph InternalNetwork["Internal Network (Docker Bridge: onpremai)"]
        subgraph AppLayer["Application Layer"]
            CA["compliance-assistant<br/>:8081<br/>Shadow AI + Orchestrator"]
            AE["agent-eval<br/>:8080<br/>LangGraph + Tribunal"]
            GW["llm-gateway<br/>:4000 / :4001<br/>Model Routing"]
            PP["preprocessor<br/>:7000<br/>OCR + Policy Parsing"]
            OBS["observer<br/>:9000<br/>Self-Improvement"]
            SB["sandbox-service<br/>:6000<br/>Code Execution"]
        end

        subgraph DataLayer["Data Layer"]
            PG[("PostgreSQL 16<br/>+ pgvector<br/>:5432<br/>• Policy Graph<br/>• Eval History<br/>• Justifications<br/>• Comments/Decisions")]
            REDIS[("Redis 7<br/>:6379<br/>• Sessions (4h TTL)<br/>• Rate Limits<br/>• Job Queues")]
            MINIO[("MinIO<br/>:9000 / :9001<br/>• Evidence Files<br/>• Policy Documents<br/>• RAG Index")]
        end

        subgraph LLMLayer["LLM Layer (Optional - Local Inference)"]
            OLLAMA["Ollama<br/>:11434<br/>• llama3.1 (mid tier)<br/>• mistral (fast tier)<br/>• nomic-embed (embeddings)"]
        end
    end

    USER --> FW
    FW --> RP
    RP -->|":8081 only"| CA
    RP -->|"WebSocket"| CA

    CA --> AE
    CA --> GW
    CA --> PP
    AE --> GW
    AE --> SB
    AE --> PP
    OBS --> GW

    CA --> PG
    CA --> REDIS
    AE --> PG
    AE --> REDIS
    GW --> REDIS
    PP --> MINIO
    AE --> MINIO
    CA --> MINIO
    OBS --> PG

    GW --> OLLAMA
    GW -.->|"Or external API<br/>(OpenAI/Anthropic)"| Internet

    style Firewall fill:#ff6b6b,stroke:#c0392b,color:#fff
    style DMZ fill:#f39c12,stroke:#d68910,color:#fff
    style InternalNetwork fill:#2c3e50,stroke:#1a252f,color:#fff
    style AppLayer fill:#2980b9,stroke:#1f6dad,color:#fff
    style DataLayer fill:#27ae60,stroke:#1e8449,color:#fff
    style LLMLayer fill:#8e44ad,stroke:#6c3483,color:#fff
```

### Security Zones

```mermaid
graph LR
    subgraph Zone1["ZONE 1: Untrusted<br/>(Internet)"]
        EXT["External Users"]
    end

    subgraph Zone2["ZONE 2: DMZ<br/>(Reverse Proxy)"]
        PROXY["TLS Termination<br/>WAF Rules<br/>Rate Limiting<br/>IP Allowlisting"]
    end

    subgraph Zone3["ZONE 3: Application<br/>(Docker Network)"]
        SERVICES["8 Application Services<br/>Inter-service: HTTP<br/>Auth: HMAC S2S keys<br/>No external access"]
    end

    subgraph Zone4["ZONE 4: Data<br/>(Docker Volumes)"]
        DATA["PostgreSQL<br/>Redis<br/>MinIO<br/>Encrypted at rest"]
    end

    subgraph Zone5["ZONE 5: LLM<br/>(Optional GPU)"]
        LLM_LOCAL["Ollama (local)<br/>OR<br/>External API (egress only)"]
    end

    Zone1 ==>|"HTTPS :443<br/>TLS 1.3"| Zone2
    Zone2 ==>|"HTTP :8081<br/>JWT validated"| Zone3
    Zone3 ==>|"TCP :5432, :6379, :9000<br/>Credentials required"| Zone4
    Zone3 ==>|"HTTP :11434<br/>or HTTPS egress"| Zone5

    style Zone1 fill:#e74c3c,color:#fff
    style Zone2 fill:#f39c12,color:#fff
    style Zone3 fill:#3498db,color:#fff
    style Zone4 fill:#27ae60,color:#fff
    style Zone5 fill:#9b59b6,color:#fff
```

### On-Prem Data Flow

```mermaid
flowchart TD
    subgraph UserInteraction["User Layer"]
        BROWSER["Browser / API Client"]
    end

    subgraph Ingress["Ingress (Firewall + Proxy)"]
        TLS["TLS 1.3 Termination"]
        WAF["WAF Rules<br/>OWASP Top 10"]
        RATE["Rate Limiter<br/>per-tenant"]
        JWT_VAL["JWT Validation<br/>(Cognito RS256 or local)"]
    end

    subgraph Compute["Compute (Docker)"]
        CA_SVC["compliance-assistant"]
        EVAL_SVC["agent-eval"]
        GW_SVC["llm-gateway"]
        PP_SVC["preprocessor"]
    end

    subgraph Storage["Persistent Storage (Docker Volumes)"]
        PG_DB[("PostgreSQL<br/>+ pgvector")]
        REDIS_DB[("Redis")]
        OBJ_STORE[("MinIO")]
    end

    subgraph LLM_Inference["LLM Inference"]
        LOCAL_LLM["Ollama (GPU)"]
        EXTERNAL_LLM["External API<br/>(via HTTPS egress)"]
    end

    BROWSER -->|"HTTPS"| TLS
    TLS --> WAF --> RATE --> JWT_VAL
    JWT_VAL -->|"tenant_id from JWT"| CA_SVC

    CA_SVC -->|"POST /evaluate"| EVAL_SVC
    CA_SVC -->|"Policy pipeline"| PP_SVC
    EVAL_SVC -->|"task=evaluate_prosecute"| GW_SVC
    PP_SVC -->|"task=extract_policy_graph"| GW_SVC

    GW_SVC -->|"routing.yaml"| LOCAL_LLM
    GW_SVC -.->|"fallback"| EXTERNAL_LLM

    CA_SVC --> PG_DB
    EVAL_SVC --> PG_DB
    CA_SVC --> REDIS_DB
    PP_SVC --> OBJ_STORE
    EVAL_SVC --> OBJ_STORE
```

### Hardware Requirements

```mermaid
graph TD
    subgraph Minimum["Minimum (Dev / Small Tenant)"]
        MIN_CPU["8 cores"]
        MIN_RAM["32 GB RAM"]
        MIN_DISK["500 GB SSD"]
        MIN_GPU["No GPU<br/>(uses external API)"]
    end

    subgraph Recommended["Recommended (5-10 Tenants)"]
        REC_CPU["16 cores"]
        REC_RAM["64 GB RAM"]
        REC_DISK["1 TB NVMe SSD"]
        REC_GPU["NVIDIA T4 / RTX 4090<br/>(16 GB VRAM for Ollama)"]
    end

    subgraph Enterprise["Enterprise (10-50 Tenants)"]
        ENT_CPU["32+ cores"]
        ENT_RAM["128 GB RAM"]
        ENT_DISK["2 TB NVMe RAID"]
        ENT_GPU["2x NVIDIA A10G<br/>(24 GB VRAM each)"]
    end
```

---

## AWS Architecture (Production)

### High-Level AWS Architecture

```mermaid
graph TB
    subgraph Internet["Internet"]
        USERS[("👤 Users")]
        ADMIN[("👤 Admin")]
    end

    subgraph AWS["AWS Region (us-east-1)"]
        subgraph Edge["Edge Services"]
            CF["☁️ CloudFront<br/>(optional CDN)"]
            WAF_AWS["🛡️ AWS WAF<br/>• OWASP Rules<br/>• Rate Limiting<br/>• Geo Blocking"]
            SHIELD["🛡️ AWS Shield<br/>(DDoS Protection)"]
        end

        subgraph Auth["Authentication"]
            COGNITO["🔐 Cognito<br/>User Pool<br/>• RS256 JWT<br/>• MFA<br/>• Custom claims:<br/>  tenant_id, role"]
        end

        subgraph VPC["VPC (10.0.0.0/16)"]
            subgraph PublicSubnets["Public Subnets (3 AZs)"]
                ALB["⚖️ Application Load Balancer<br/>• HTTPS :443 (ACM cert)<br/>• Path-based routing<br/>• Health checks"]
                NAT1["🌐 NAT Gateway (AZ1)"]
                NAT2["🌐 NAT Gateway (AZ2)"]
            end

            subgraph PrivateSubnets["Private Subnets (3 AZs) — No Internet Ingress"]
                subgraph ECS["ECS Fargate Cluster"]
                    SVC_CA["📦 compliance-assistant<br/>1024 CPU / 2GB<br/>Auto-scale 1→4"]
                    SVC_AE["📦 agent-eval<br/>2048 CPU / 4GB<br/>Auto-scale 1→4"]
                    SVC_GW["📦 llm-gateway<br/>1024 CPU / 2GB<br/>Auto-scale 1→4"]
                    SVC_MEM["📦 memory-service<br/>512 CPU / 1GB<br/>Auto-scale 1→4"]
                    SVC_PP["📦 preprocessor<br/>1024 CPU / 2GB<br/>Auto-scale 1→2"]
                    SVC_OBS["📦 observer<br/>512 CPU / 1GB<br/>Auto-scale 1→2"]
                    SVC_SB["📦 sandbox-service<br/>2048 CPU / 4GB<br/>Auto-scale 1→2"]
                end

                CMAP["🗺️ Cloud Map<br/>onpremai.internal<br/>(Private DNS)"]
            end

            subgraph DatabaseSubnets["Database Subnets (Isolated — No NAT)"]
                RDS["🗄️ RDS PostgreSQL 16<br/>+ pgvector extension<br/>db.t4g.medium<br/>Multi-AZ (prod)<br/>Encrypted (KMS)"]
                ELASTICACHE["⚡ ElastiCache Redis<br/>cache.t4g.medium<br/>Encryption in-transit<br/>Auth token"]
            end
        end

        subgraph Serverless["Serverless / Managed Services"]
            S3["📁 S3<br/>compliance-artifacts<br/>• SSE-S3 encryption<br/>• Versioning enabled<br/>• Lifecycle policies"]
            BEDROCK["🧠 Bedrock<br/>• Claude (Converse API)<br/>• Titan Embed v2<br/>• No data retention"]
            TEXTRACT["📄 Textract<br/>• Document analysis<br/>• Table extraction"]
            SECRETS["🔑 Secrets Manager<br/>• DB credentials<br/>• API keys<br/>• Auto-rotation"]
            KMS["🔐 KMS<br/>• RDS encryption key<br/>• S3 encryption key<br/>• Secrets encryption"]
            CW["📊 CloudWatch<br/>• Logs (all services)<br/>• Metrics<br/>• Alarms"]
            ECR["📦 ECR<br/>• Image repos<br/>• Vulnerability scan"]
        end
    end

    USERS --> CF
    CF --> WAF_AWS
    WAF_AWS --> ALB
    USERS -->|"Auth flow"| COGNITO
    COGNITO -->|"JWT"| ALB

    ALB --> SVC_CA
    ALB --> SVC_AE

    SVC_CA --> CMAP
    SVC_AE --> CMAP
    SVC_GW --> CMAP
    CMAP --> SVC_MEM
    CMAP --> SVC_PP
    CMAP --> SVC_SB

    SVC_MEM --> RDS
    SVC_AE --> RDS
    SVC_CA --> ELASTICACHE
    SVC_GW --> ELASTICACHE

    SVC_GW --> BEDROCK
    SVC_PP --> TEXTRACT
    SVC_PP --> S3
    SVC_AE --> S3
    SVC_CA --> S3

    SVC_GW --> SECRETS
    SVC_MEM --> SECRETS

    RDS --> KMS
    S3 --> KMS
    SECRETS --> KMS

    ECS --> CW
    ECS --> ECR

    style Edge fill:#ff9f43,stroke:#e17055
    style Auth fill:#6c5ce7,stroke:#5f3dc4,color:#fff
    style PublicSubnets fill:#74b9ff,stroke:#0984e3
    style PrivateSubnets fill:#55efc4,stroke:#00b894
    style DatabaseSubnets fill:#fd79a8,stroke:#e84393
    style Serverless fill:#a29bfe,stroke:#6c5ce7
```

### AWS Security Architecture

```mermaid
graph TB
    subgraph Perimeter["Perimeter Security"]
        direction LR
        SHIELD_P["🛡️ Shield Advanced<br/>DDoS L3/L4/L7"]
        WAF_P["🛡️ WAF v2<br/>• SQL injection<br/>• XSS<br/>• Rate: 2000 req/5min<br/>• Geo-restrict"]
        ACM["🔒 ACM Certificate<br/>TLS 1.2+ only<br/>Auto-renewal"]
    end

    subgraph Network["Network Security"]
        direction LR
        SG_ALB["🔒 SG: ALB<br/>Inbound: 443 from 0.0.0.0/0<br/>Outbound: ECS SG only"]
        SG_ECS["🔒 SG: ECS Services<br/>Inbound: ALB SG only<br/>Outbound: DB SG + NAT"]
        SG_DB["🔒 SG: Database<br/>Inbound: ECS SG only<br/>Outbound: None"]
        NACL["🔒 NACLs<br/>DB subnet: deny all<br/>except ECS CIDR"]
    end

    subgraph Identity["Identity & Access"]
        direction LR
        COGNITO_ID["🔐 Cognito<br/>• MFA enforced<br/>• Password policy<br/>• JWT RS256<br/>• Custom claims"]
        IAM_TASK["🔐 Task IAM Roles<br/>• Least privilege<br/>• Per-service policies<br/>• No * resources"]
        IAM_EXEC["🔐 Execution Roles<br/>• ECR pull only<br/>• Secrets read only<br/>• CloudWatch write"]
    end

    subgraph DataProtection["Data Protection"]
        direction LR
        KMS_KEY["🔐 KMS CMK<br/>• Key rotation enabled<br/>• Key policy restricts<br/>  to service roles"]
        RDS_ENC["🔒 RDS Encryption<br/>• At-rest (AES-256)<br/>• In-transit (TLS)<br/>• IAM DB auth"]
        S3_ENC["🔒 S3 Encryption<br/>• SSE-S3 default<br/>• Bucket policy<br/>• Block public access<br/>• VPC endpoint"]
        REDIS_ENC["🔒 Redis Encryption<br/>• In-transit TLS<br/>• Auth token<br/>• No public access"]
    end

    subgraph Monitoring["Security Monitoring"]
        direction LR
        CT["📋 CloudTrail<br/>• All API calls<br/>• S3 data events<br/>• Multi-region"]
        GD["🔍 GuardDuty<br/>• Anomaly detection<br/>• Threat findings<br/>• Auto-remediation"]
        CONFIG["📋 AWS Config<br/>• Compliance rules<br/>• Drift detection<br/>• Auto-remediate"]
        CW_ALARMS["🚨 CloudWatch Alarms<br/>• Auth failures > 10/min<br/>• 5xx errors > 5%<br/>• Latency P99 > 5s"]
    end

    subgraph TenantIsolation["Tenant Isolation"]
        direction LR
        APP_TENANT["🏢 Application Layer<br/>• tenant_id from JWT<br/>• Query filter on ALL<br/>  data access<br/>• Never from request body"]
        DB_TENANT["🏢 Database Layer<br/>• PostgreSQL RLS<br/>• SET app.current_tenant<br/>• Defense-in-depth"]
        S3_TENANT["🏢 Storage Layer<br/>• Prefix: {tenant_id}/<br/>• IAM conditions:<br/>  s3:prefix = tenant_id"]
    end

    Perimeter --> Network
    Network --> Identity
    Identity --> DataProtection
    DataProtection --> Monitoring
    Monitoring --> TenantIsolation

    style Perimeter fill:#e74c3c,color:#fff
    style Network fill:#f39c12,color:#fff
    style Identity fill:#9b59b6,color:#fff
    style DataProtection fill:#2980b9,color:#fff
    style Monitoring fill:#27ae60,color:#fff
    style TenantIsolation fill:#1abc9c,color:#fff
```

### IAM Roles per Service (Least Privilege)

```mermaid
graph TD
    subgraph IAM["IAM Task Roles — Least Privilege"]
        subgraph GW_Role["llm-gateway-task-role"]
            GW_P1["bedrock:InvokeModel<br/>bedrock:InvokeModelWithResponseStream<br/>→ anthropic.claude-*, amazon.titan-*"]
            GW_P2["secretsmanager:GetSecretValue<br/>→ onpremai/*/api-keys"]
        end

        subgraph AE_Role["agent-eval-task-role"]
            AE_P1["s3:GetObject, s3:ListBucket<br/>→ compliance-artifacts/*"]
            AE_P2["(No Bedrock — uses gateway)"]
        end

        subgraph PP_Role["preprocessor-task-role"]
            PP_P1["s3:GetObject, s3:PutObject<br/>→ compliance-artifacts/*"]
            PP_P2["textract:DetectDocumentText<br/>textract:AnalyzeDocument<br/>→ *"]
        end

        subgraph CA_Role["compliance-assistant-task-role"]
            CA_P1["s3:GetObject, s3:PutObject<br/>→ compliance-artifacts/*"]
            CA_P2["ses:SendEmail<br/>→ verified identities"]
        end

        subgraph MEM_Role["memory-service-task-role"]
            MEM_P1["(No AWS API — DB access<br/>via network only)"]
        end

        subgraph OBS_Role["observer-task-role"]
            OBS_P1["logs:FilterLogEvents<br/>logs:GetLogEvents<br/>→ /ecs/onpremai-*"]
        end

        subgraph SB_Role["sandbox-service-task-role"]
            SB_P1["s3:GetObject<br/>→ compliance-artifacts/*<br/>(read-only evidence)"]
        end
    end

    style GW_Role fill:#3498db,color:#fff
    style AE_Role fill:#e67e22,color:#fff
    style PP_Role fill:#2ecc71,color:#fff
    style CA_Role fill:#9b59b6,color:#fff
    style MEM_Role fill:#1abc9c,color:#fff
    style OBS_Role fill:#f1c40f,color:#000
    style SB_Role fill:#e74c3c,color:#fff
```

### Network Flow (AWS)

```mermaid
flowchart TD
    subgraph External["External (Internet)"]
        CLIENT["Browser / Mobile"]
    end

    subgraph AWSEdge["AWS Edge"]
        CF2["CloudFront"]
        WAF2["WAF v2"]
    end

    subgraph Public["Public Subnets"]
        ALB2["ALB<br/>(:443 HTTPS)"]
        NAT["NAT Gateways<br/>(egress only)"]
    end

    subgraph Private["Private Subnets (ECS)"]
        SERVICES2["ECS Services<br/>(all 8 containers)"]
    end

    subgraph DBSubnet["Database Subnets (Isolated)"]
        RDS2["RDS PostgreSQL"]
        REDIS2["ElastiCache Redis"]
    end

    subgraph VPCE["VPC Endpoints (Private Link)"]
        S3_EP["S3 Gateway Endpoint"]
        BEDROCK_EP["Bedrock Interface Endpoint"]
        SECRETS_EP["Secrets Manager Endpoint"]
        ECR_EP["ECR Endpoints"]
        CW_EP["CloudWatch Endpoint"]
    end

    CLIENT -->|"HTTPS :443"| CF2
    CF2 --> WAF2
    WAF2 -->|"Allowed traffic"| ALB2
    ALB2 -->|"Target groups<br/>per service"| SERVICES2
    SERVICES2 -->|":5432 (TLS)"| RDS2
    SERVICES2 -->|":6379 (TLS)"| REDIS2
    SERVICES2 -->|"Private Link<br/>(no internet)"| S3_EP
    SERVICES2 -->|"Private Link"| BEDROCK_EP
    SERVICES2 -->|"Private Link"| SECRETS_EP
    SERVICES2 -->|"Private Link"| ECR_EP
    SERVICES2 -->|"Private Link"| CW_EP
    SERVICES2 -->|"Egress via NAT<br/>(external APIs only)"| NAT

    style External fill:#e74c3c,color:#fff
    style AWSEdge fill:#f39c12,color:#fff
    style Public fill:#3498db,color:#fff
    style Private fill:#2ecc71,color:#fff
    style DBSubnet fill:#9b59b6,color:#fff
    style VPCE fill:#1abc9c,color:#fff
```

### Data Encryption

```mermaid
graph LR
    subgraph InTransit["Encryption In-Transit"]
        T1["Client → ALB<br/>TLS 1.2+ (ACM cert)"]
        T2["ALB → ECS<br/>HTTP (internal VPC)"]
        T3["ECS → RDS<br/>TLS (rds-ca-2019)"]
        T4["ECS → Redis<br/>TLS (in-transit encryption)"]
        T5["ECS → S3<br/>HTTPS (VPC endpoint)"]
        T6["ECS → Bedrock<br/>TLS (PrivateLink)"]
    end

    subgraph AtRest["Encryption At-Rest"]
        R1["RDS: AES-256<br/>(KMS CMK)"]
        R2["S3: SSE-S3<br/>(AES-256)"]
        R3["Redis: at-rest<br/>(KMS)"]
        R4["EBS: encrypted<br/>(KMS)"]
        R5["Secrets Manager:<br/>KMS envelope encryption"]
        R6["CloudWatch Logs:<br/>KMS encryption"]
    end

    subgraph KeyMgmt["Key Management"]
        KMS_CMK["KMS CMK<br/>• Auto-rotation: annual<br/>• Key policy: service roles only<br/>• Alias: onpremai-{env}-key"]
    end

    InTransit --> KeyMgmt
    AtRest --> KeyMgmt
```

---

## Service Communication Patterns

### Both Environments

```mermaid
sequenceDiagram
    participant U as User (Browser)
    participant LB as Load Balancer<br/>(ALB / nginx)
    participant CA as compliance-assistant
    participant AE as agent-eval
    participant GW as llm-gateway
    participant MEM as memory-service
    participant PG as PostgreSQL
    participant STORE as Storage (S3/MinIO)
    participant LLM as LLM Provider<br/>(Bedrock/Ollama)

    Note over U,LLM: Same flow in both environments - only URLs and auth differ

    U->>LB: HTTPS POST /chat {message, JWT}
    LB->>CA: HTTP + X-Forwarded-For + JWT
    
    CA->>CA: Validate JWT (RS256)<br/>Extract: tenant_id, user_id, role

    CA->>MEM: GET /session/{id} + GET /eval/last
    MEM->>PG: SELECT (parallel queries)
    PG-->>MEM: Context + eval history
    MEM-->>CA: Session + context

    CA->>AE: POST /evaluate<br/>Headers: X-Tenant-Id, X-Trace-Id
    
    AE->>MEM: GET /policy-graph/traverse?root=CC6.1
    MEM->>PG: Recursive CTE (graph traversal)
    PG-->>MEM: Graph subgraph
    MEM-->>AE: Policy context

    AE->>STORE: List evidence files
    STORE-->>AE: File metadata

    Note over AE: Layer 1: Rules (no LLM)

    Note over AE: Layer 2: Tribunal
    AE->>GW: POST /v1/chat {task: "evaluate_prosecute"}
    GW->>LLM: Bedrock InvokeModel / Ollama generate
    LLM-->>GW: Prosecution argument
    GW-->>AE: Response

    AE->>GW: POST /v1/chat {task: "evaluate_defend"}
    GW->>LLM: Model call
    LLM-->>GW: Defense argument
    GW-->>AE: Response

    AE->>GW: POST /v1/chat {task: "evaluate_judge"}
    GW->>LLM: Model call
    LLM-->>GW: Verdict + justification
    GW-->>AE: Response

    Note over AE: Layer 3: Scoring (no LLM)

    AE->>MEM: POST /eval/store + POST /justification
    MEM->>PG: INSERT eval_history + evaluation_justifications
    AE-->>CA: {score, status, justification}

    CA-->>U: "CC6.1 compliant (87%). Here's why..."
```

---

## Adapter Configuration

### Environment Variable Mapping

```mermaid
graph LR
    subgraph Config["Configuration Switch"]
        ENV_VAR["Environment Variables"]
    end

    subgraph OnPrem["On-Prem Values"]
        OP_STORE["STORAGE_BACKEND=minio<br/>STORAGE_ENDPOINT=http://minio:9000"]
        OP_OCR["OCR_BACKEND=tesseract"]
        OP_DB["DATABASE_URL=postgresql://..@postgres:5432/onpremai"]
        OP_REDIS["REDIS_URL=redis://redis:6379/0"]
        OP_LLM["LLM config: provider=ollama<br/>or provider=anthropic (API key)"]
        OP_AUTH["AUTH_PROVIDER=local<br/>(dev JWT signing)"]
    end

    subgraph AWSVals["AWS Values"]
        AWS_STORE["STORAGE_BACKEND=s3<br/>S3_BUCKET=compliance-artifacts"]
        AWS_OCR["OCR_BACKEND=textract"]
        AWS_DB["DATABASE_URL=postgresql://..@rds-endpoint:5432/onpremai"]
        AWS_REDIS["REDIS_URL=redis://elasticache:6379/0"]
        AWS_LLM["LLM config: provider=bedrock<br/>region=us-east-1"]
        AWS_AUTH["AUTH_PROVIDER=cognito<br/>COGNITO_POOL_ID=us-east-1_xxx"]
    end

    ENV_VAR --> OnPrem
    ENV_VAR --> AWSVals
```

---

## Scaling Comparison

```mermaid
graph TD
    subgraph OnPremScale["On-Prem Scaling"]
        OP_V["Vertical Only<br/>(bigger server)"]
        OP_H["Horizontal:<br/>Docker Swarm or K8s<br/>(advanced setup)"]
        OP_LIMIT["Limit: Hardware capacity<br/>Typical: 5-50 tenants"]
    end

    subgraph AWSScale["AWS Scaling"]
        AWS_H["Horizontal (Auto-Scale)<br/>• CPU > 70% → scale out<br/>• Requests > threshold → scale out<br/>• Min 1, Max 4 per service"]
        AWS_DB_S["Database Scaling<br/>• Read replicas (graph queries)<br/>• Storage auto-expand<br/>• Instance upgrade (zero-downtime)"]
        AWS_LIMIT["Limit: Budget<br/>Typical: 50-5000 tenants"]
    end

    OnPremScale --- AWSScale
```

---

## Disaster Recovery

```mermaid
graph TB
    subgraph OnPremDR["On-Prem DR"]
        OP_BACKUP["Daily: pg_dump + MinIO mirror<br/>to secondary server"]
        OP_RTO["RTO: 2-4 hours<br/>(restore from backup)"]
        OP_RPO["RPO: 24 hours<br/>(last backup)"]
    end

    subgraph AWSDR["AWS DR"]
        AWS_BACKUP["Continuous: RDS automated backups<br/>+ S3 cross-region replication"]
        AWS_RTO["RTO: 15-30 minutes<br/>(Multi-AZ failover)"]
        AWS_RPO["RPO: ~5 minutes<br/>(WAL archiving)"]
        AWS_MULTI["Multi-AZ: Automatic failover<br/>for RDS + ElastiCache"]
    end

    style OnPremDR fill:#f39c12,color:#fff
    style AWSDR fill:#27ae60,color:#fff
```

---

## Deployment Pipeline

```mermaid
flowchart LR
    subgraph Dev["Development"]
        CODE["Code Push"]
        TEST["Unit Tests<br/>+ Lint"]
    end

    subgraph OnPremDeploy["On-Prem Deploy"]
        COMPOSE_BUILD["docker compose build"]
        COMPOSE_UP["docker compose up -d"]
        HEALTH["Health check all services"]
    end

    subgraph AWSDeploy["AWS Deploy"]
        ECR_PUSH["Build + Push to ECR"]
        TF_PLAN["terraform plan"]
        TF_APPLY["terraform apply"]
        ECS_DEPLOY["ECS rolling update<br/>(zero-downtime)"]
    end

    CODE --> TEST
    TEST --> OnPremDeploy
    TEST --> AWSDeploy

    COMPOSE_BUILD --> COMPOSE_UP --> HEALTH
    ECR_PUSH --> TF_PLAN --> TF_APPLY --> ECS_DEPLOY
```

---

## Cost Summary

```mermaid
graph TD
    subgraph Costs["Monthly Cost Comparison"]
        subgraph OnPremCost["On-Prem"]
            OP_C1["Hardware: $0/mo<br/>(customer-owned)"]
            OP_C2["LLM (Ollama): $0/mo"]
            OP_C3["LLM (API keys): $50-500/mo<br/>(if using external)"]
            OP_C4["Total: $0 - $500/mo"]
        end

        subgraph AWSCost["AWS (Production)"]
            AWS_C1["ECS Fargate: $200-400/mo"]
            AWS_C2["RDS + Redis: $90-150/mo"]
            AWS_C3["Bedrock LLM: $50-500/mo"]
            AWS_C4["S3 + Transfer: $10-30/mo"]
            AWS_C5["Other (WAF, NAT, etc): $50-100/mo"]
            AWS_C6["Total: $400-1200/mo"]
        end
    end

    style OnPremCost fill:#27ae60,color:#fff
    style AWSCost fill:#3498db,color:#fff
```
