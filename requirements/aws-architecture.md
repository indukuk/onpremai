# AWS Architecture — High-Level Design

## Overview

This document defines how the compliance AI system deploys on AWS. All services run as Docker containers on ECS Fargate with service discovery via Cloud Map. Infrastructure uses RDS PostgreSQL, ElastiCache Redis, S3, and Bedrock for LLM inference.

---

## Infrastructure Topology

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│  AWS Region: us-east-1                                                          │
│                                                                                  │
│  ┌─────────────────────────────────────────────────────────────────────────┐    │
│  │  VPC: 10.0.0.0/16                                                       │    │
│  │                                                                          │    │
│  │  ┌──────────────────────────────────────────────────────────────────┐   │    │
│  │  │  PUBLIC SUBNETS (10.0.1.0/24, 10.0.2.0/24, 10.0.3.0/24)        │   │    │
│  │  │                                                                   │   │    │
│  │  │  ┌─────────────┐    ┌──────────────┐    ┌──────────────────┐    │   │    │
│  │  │  │  ALB (HTTPS) │    │ NAT Gateway  │    │ NAT Gateway (AZ2)│    │   │    │
│  │  │  │  :443 only   │    │    (AZ1)     │    │                  │    │   │    │
│  │  │  └──────┬───────┘    └──────────────┘    └──────────────────┘    │   │    │
│  │  └─────────┼────────────────────────────────────────────────────────┘   │    │
│  │            │                                                             │    │
│  │  ┌─────────▼────────────────────────────────────────────────────────┐   │    │
│  │  │  APP SUBNETS (10.0.11.0/24, 10.0.12.0/24, 10.0.13.0/24)        │   │    │
│  │  │                                                                   │   │    │
│  │  │  ┌─────────────────────────────────────────────────────────┐     │   │    │
│  │  │  │  ECS Cluster: onpremai-cluster                           │     │   │    │
│  │  │  │                                                          │     │   │    │
│  │  │  │  ┌──────────────────┐  ┌────────────────────────────┐  │     │   │    │
│  │  │  │  │ compliance-      │  │ agent-eval                  │  │     │   │    │
│  │  │  │  │ assistant :8080  │  │ :8080                       │  │     │   │    │
│  │  │  │  └──────────────────┘  └────────────────────────────┘  │     │   │    │
│  │  │  │  ┌──────────────────┐  ┌────────────────────────────┐  │     │   │    │
│  │  │  │  │ llm-gateway      │  │ memory-service              │  │     │   │    │
│  │  │  │  │ :4000 / :4001   │  │ :5000                       │  │     │   │    │
│  │  │  │  └──────────────────┘  └────────────────────────────┘  │     │   │    │
│  │  │  │  ┌──────────────────┐  ┌────────────────────────────┐  │     │   │    │
│  │  │  │  │ observer :6000   │  │ preprocessor :7000          │  │     │   │    │
│  │  │  │  └──────────────────┘  └────────────────────────────┘  │     │   │    │
│  │  │  │  ┌──────────────────┐  ┌────────────────────────────┐  │     │   │    │
│  │  │  │  │ sandbox-service  │  │ backend (MCP) :8080         │  │     │   │    │
│  │  │  │  │ :9000            │  │                             │  │     │   │    │
│  │  │  │  └──────────────────┘  └────────────────────────────┘  │     │   │    │
│  │  │  └─────────────────────────────────────────────────────────┘     │   │    │
│  │  │                                                                   │   │    │
│  │  │  Cloud Map Namespace: onpremai.internal                           │   │    │
│  │  │  (DNS: llm-gateway.onpremai.internal, memory-service.onpremai.internal, ...) │
│  │  └───────────────────────────────────────────────────────────────────┘   │    │
│  │                                                                          │    │
│  │  ┌───────────────────────────────────────────────────────────────────┐   │    │
│  │  │  DATA SUBNETS (10.0.21.0/24, 10.0.22.0/24, 10.0.23.0/24)        │   │    │
│  │  │                                                                    │   │    │
│  │  │  ┌────────────────────┐  ┌──────────────────┐                    │   │    │
│  │  │  │ RDS PostgreSQL 16  │  │ ElastiCache Redis │                    │   │    │
│  │  │  │ + pgvector         │  │ (cluster mode)    │                    │   │    │
│  │  │  │ Multi-AZ           │  │                   │                    │   │    │
│  │  │  └────────────────────┘  └──────────────────┘                    │   │    │
│  │  └───────────────────────────────────────────────────────────────────┘   │    │
│  └──────────────────────────────────────────────────────────────────────────┘    │
│                                                                                  │
│  ┌──────────────────────────────────────────────────────────────────────────┐    │
│  │  AWS Managed Services (no VPC placement needed)                           │    │
│  │                                                                           │    │
│  │  ┌───────────┐  ┌────────────┐  ┌──────────────┐  ┌──────────────────┐  │    │
│  │  │ S3        │  │ Bedrock    │  │ Cognito      │  │ Secrets Manager  │  │    │
│  │  │ (evidence)│  │ (LLM/Embed)│  │ (User Pool)  │  │ (API keys, DB)   │  │    │
│  │  └───────────┘  └────────────┘  └──────────────┘  └──────────────────┘  │    │
│  │  ┌───────────┐  ┌────────────┐  ┌──────────────┐                        │    │
│  │  │ ECR       │  │ CloudWatch │  │ KMS          │                        │    │
│  │  │ (images)  │  │ (logs)     │  │ (encryption) │                        │    │
│  │  └───────────┘  └────────────┘  └──────────────┘                        │    │
│  └──────────────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## Compute: ECS Fargate

**Why Fargate (not EC2):**
- No infrastructure management — no patching, no AMIs
- Per-task IAM roles — each service gets least-privilege credentials
- Auto-scaling per service — independent scaling without capacity planning
- Strong isolation — each task runs in its own micro-VM (Firecracker)

### ECS Cluster Configuration

```
Cluster: onpremai-cluster
Namespace: onpremai.internal (Cloud Map)
Capacity: Fargate (serverless)
Container Insights: enabled
```

### Service Definitions

| Service | CPU | Memory | Min Tasks | Max Tasks | Scale Metric |
|---------|-----|--------|:---------:|:---------:|-------------|
| compliance-assistant | 512 | 1024 MB | 2 | 10 | Request count |
| agent-eval | 1024 | 2048 MB | 2 | 20 | Queue depth + CPU |
| llm-gateway | 512 | 1024 MB | 2 | 10 | Request count |
| memory-service | 512 | 1024 MB | 2 | 5 | CPU |
| observer | 256 | 512 MB | 1 | 1 | None (singleton) |
| sandbox-service | 1024 | 2048 MB | 1 | 10 | Active executions |
| preprocessor | 512 | 1024 MB | 1 | 5 | Queue depth |
| backend (MCP) | 512 | 1024 MB | 2 | 5 | Request count |

### Auto-Scaling

- **Target tracking**: CPU utilization target = 65%
- **Cooldown**: Scale-out = 60s, Scale-in = 300s
- **Scheduled**: Scale down 50% at off-peak hours (configurable per tenant timezone)
- **agent-eval**: additional scaling on SQS queue depth (evaluation backlog)

---

## Networking

### VPC Design (3-tier, 3 AZ)

| Tier | Subnets | Contains | Internet Access |
|------|---------|----------|----------------|
| Public | 10.0.1-3.0/24 | ALB, NAT Gateways | Direct |
| App | 10.0.11-13.0/24 | ECS tasks (all services) | Via NAT (outbound only) |
| Data | 10.0.21-23.0/24 | RDS, ElastiCache | None (VPC endpoints for AWS) |

### Security Groups

```
ALB-SG:
  Inbound:  443 from 0.0.0.0/0 (HTTPS only)
  Outbound: 4000-9000 to ECS-SG

ECS-SG (all services):
  Inbound:  4000-9000 from ALB-SG
  Inbound:  4000-9000 from self (service-to-service via Cloud Map)
  Outbound: 443 to 0.0.0.0/0 (Bedrock, Cognito via NAT)
  Outbound: 5432 to DB-SG
  Outbound: 6379 to Redis-SG

DB-SG (RDS):
  Inbound:  5432 from ECS-SG
  Outbound: none

Redis-SG (ElastiCache):
  Inbound:  6379 from ECS-SG
  Outbound: none
```

### VPC Endpoints (avoid NAT costs for AWS services)

| Endpoint | Type | Purpose |
|----------|------|---------|
| com.amazonaws.us-east-1.s3 | Gateway | Evidence file access |
| com.amazonaws.us-east-1.secretsmanager | Interface | Secret injection |
| com.amazonaws.us-east-1.ecr.api | Interface | Image pulls |
| com.amazonaws.us-east-1.ecr.dkr | Interface | Docker layer pulls |
| com.amazonaws.us-east-1.logs | Interface | CloudWatch logs |
| com.amazonaws.us-east-1.bedrock-runtime | Interface | LLM inference |

### Service Discovery (Cloud Map)

All services register in the `onpremai.internal` namespace:

```
llm-gateway.onpremai.internal       → port 4000
memory-service.onpremai.internal    → port 5000
observer.onpremai.internal          → port 6000
preprocessor.onpremai.internal      → port 7000
compliance-assistant.onpremai.internal → port 8080
agent-eval.onpremai.internal        → port 8080
sandbox-service.onpremai.internal   → port 9000
backend.onpremai.internal           → port 8080
```

Services resolve each other by DNS name — no hardcoded IPs, no load balancer for internal traffic.

---

## Data Layer

### RDS PostgreSQL (+ pgvector)

```
Engine:         PostgreSQL 16 with pgvector extension
Instance:       db.r6g.large (2 vCPU, 16 GB) — production
Multi-AZ:       Yes (synchronous standby)
Storage:        100 GB gp3, auto-scaling to 500 GB
Encryption:     AES-256 (KMS customer-managed key)
Backup:         Automated, 7-day retention, point-in-time recovery
```

**Databases:**
- `compliance_memory` — memory-service (user/tenant facts, evals, patterns, skills, audit trail)
- `compliance_state` — agent-eval state, job tracking

### ElastiCache Redis

```
Engine:         Redis 7.x
Node type:      cache.r6g.large
Cluster mode:   Disabled (single shard, Multi-AZ replicas)
Encryption:     In-transit (TLS) + at-rest (KMS)
Auth:           Redis AUTH token (stored in Secrets Manager)
```

**Usage:**
- Session state (memory-service R1: 4-hour TTL)
- Rate limit counters (llm-gateway R12)
- Budget queue persistence (llm-gateway R16)

### S3

```
Bucket:         compliance-artifacts-{account-id}
Versioning:     Enabled
Encryption:     SSE-KMS (customer-managed key)
Lifecycle:      IA after 90 days, Glacier after 365 days
Access:         VPC endpoint only (no public access)
```

**Prefixes:**
- `{tenant_id}/evidence/` — raw evidence files
- `{tenant_id}/evidence/{control_id}/processed/` — preprocessor output + metadata.json
- `rag-kb/v2/` — RAG index (shared, read by agent-eval)
- `config/` — routing.yaml (read by llm-gateway on startup)

---

## Security Architecture

### Authentication & Authorization Flow

```
                    ┌──────────────┐
                    │   Frontend   │
                    │   (SPA)      │
                    └──────┬───────┘
                           │ 1. Login (email + password + MFA)
                           ▼
                    ┌──────────────┐
                    │   Cognito    │
                    │  User Pool   │
                    └──────┬───────┘
                           │ 2. Returns JWT (ID + Access + Refresh tokens)
                           ▼
                    ┌──────────────┐
                    │   Frontend   │ (stores tokens, sends Access token)
                    └──────┬───────┘
                           │ 3. API call with Authorization: Bearer {access_token}
                           ▼
                    ┌──────────────┐
                    │     ALB      │ (TLS termination, forwards to backend)
                    └──────┬───────┘
                           │
                           ▼
              ┌────────────────────────────┐
              │  Backend / MCP Module       │
              │                            │
              │  4. Validate JWT            │
              │     - Verify signature (JWKS from Cognito)
              │     - Check exp, iss, aud   │
              │     - Extract: user_id, tenant_id, role
              │                            │
              │  5. RBAC Check             │
              │     - Role → tool/resource access matrix
              │     - Scope check (own controls only for contributor)
              │                            │
              │  6. Execute request         │
              └────────────────────────────┘
```

### Identity Provider: AWS Cognito

```
User Pool:      onpremai-users
MFA:            Required (TOTP or SMS)
Password:       Min 12 chars, uppercase + lowercase + digit + symbol
Token expiry:   Access = 1 hour, Refresh = 30 days
Custom claims:  custom:tenant_id, custom:role
Groups:         Maps to roles (admin, compliance_manager, contributor, auditor, viewer)
```

### JWT Token Structure (Cognito Access Token)

```json
{
  "sub": "user-uuid-123",
  "iss": "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_XXXXXXX",
  "aud": "app-client-id",
  "exp": 1717200000,
  "iat": 1717196400,
  "cognito:groups": ["compliance_manager"],
  "custom:tenant_id": "tenant-uuid-456",
  "custom:role": "compliance_manager"
}
```

### Service-to-Service Authentication

Internal services do NOT use user JWTs. They authenticate via:

```
┌──────────────────────┐         ┌──────────────────────┐
│ compliance-assistant │         │     llm-gateway       │
│                      │         │                       │
│ Header:              │────────►│ Validates:            │
│   X-Service-Id: ca   │         │   - API key (HMAC)   │
│   X-Service-Key: ... │         │   - Service allowlist │
│   X-Trace-Id: abc    │         │   - Source IP (SG)    │
│   X-Tenant-Id: t123  │         │                       │
└──────────────────────┘         └───────────────────────┘
```

**S2S auth properties:**
- API keys generated per-service, stored in Secrets Manager, rotated every 90 days
- Keys are HMAC-verified (bcrypt hash stored in memory-service, raw key in Secrets Manager)
- Security group already restricts source to ECS-SG — API key is defense in depth
- `X-Tenant-Id` header propagated for per-tenant budget tracking
- `X-Trace-Id` propagated for observability correlation

### IAM Roles (Least Privilege)

Each ECS task gets its own IAM role:

| Service | IAM Permissions |
|---------|----------------|
| **llm-gateway** | `bedrock:InvokeModel`, `bedrock:InvokeModelWithResponseStream` |
| **memory-service** | RDS connect (IAM auth), no S3, no Bedrock |
| **agent-eval** | `s3:GetObject` (evidence bucket), `s3:PutObject` (results) |
| **preprocessor** | `s3:GetObject`, `s3:PutObject`, `textract:AnalyzeDocument` |
| **sandbox-service** | `s3:GetObject` (evidence files for execution) |
| **observer** | `bedrock:InvokeModel` (via gateway, not direct — but needs gateway admin) |
| **compliance-assistant** | None (talks to backend/MCP via HTTP, no direct AWS) |
| **backend** | `s3:*` (evidence), `cognito-idp:*` (user management), RDS connect |

**Task Execution Role (shared):** ECR pull, Secrets Manager read, CloudWatch logs write.

### Encryption

| Data | Encryption | Key |
|------|-----------|-----|
| S3 objects | SSE-KMS | Customer-managed CMK |
| RDS storage | AES-256 | Customer-managed CMK |
| RDS connections | TLS 1.3 | AWS-managed cert |
| ElastiCache in-transit | TLS | AWS-managed cert |
| ElastiCache at-rest | AES-256 | Customer-managed CMK |
| Secrets Manager | AES-256 | AWS-managed key |
| ECS task storage | Fargate ephemeral encryption | AWS-managed |
| ALB → Client | TLS 1.2+ | ACM certificate |

### Network Security

- **No public IPs** on any ECS task or database
- **ALB is the only ingress** — terminates TLS, forwards to private targets
- **NAT gateways** for outbound (Bedrock API calls, Cognito token validation)
- **VPC endpoints** for S3, Secrets Manager, ECR, CloudWatch, Bedrock (avoids traversing internet)
- **Security groups** enforce service-to-service isolation at network level

---

## Observability

### CloudWatch Integration

```
Log Groups:
  /ecs/onpremai/compliance-assistant
  /ecs/onpremai/agent-eval
  /ecs/onpremai/llm-gateway
  /ecs/onpremai/memory-service
  /ecs/onpremai/observer
  /ecs/onpremai/sandbox-service
  /ecs/onpremai/preprocessor
  /ecs/onpremai/backend

Container Insights: enabled (CPU, memory, network per task)
Log retention: 30 days (standard), 90 days (audit trail)
```

### Metrics & Alarms

| Metric | Alarm Threshold | Action |
|--------|----------------|--------|
| ECS task restart count | >3 in 5 min | SNS → PagerDuty |
| ALB 5xx error rate | >5% for 3 min | SNS → PagerDuty |
| RDS CPU utilization | >80% for 5 min | SNS → email |
| RDS free storage | <10 GB | SNS → email |
| ElastiCache evictions | >0 for 5 min | SNS → email |
| Bedrock throttle count | >10 in 1 min | SNS → observer webhook |
| LLM gateway queue depth | >50 requests | SNS → email |

---

## CI/CD Pipeline

```
GitHub → CodePipeline → CodeBuild → ECR → ECS Deploy

Stages:
1. Source:       GitHub push to main (or tagged release)
2. Build:        CodeBuild builds Docker image, runs unit tests
3. Push:         Push image to ECR with semantic version tag
4. Deploy-Stage: ECS rolling update to staging cluster
5. Test:         Integration tests against staging
6. Deploy-Prod:  ECS rolling update to production cluster (blue/green)
```

### Image Registry (ECR)

```
Registry:  {account-id}.dkr.ecr.us-east-1.amazonaws.com
Repos:     onpremai/{service-name} (one per service)
Tags:      v{major}.{minor}.{patch} (immutable), latest (mutable, staging only)
Scanning:  On-push (Amazon Inspector)
Lifecycle: Keep last 10 tagged images, delete untagged after 7 days
```

---

## Cost Estimates (Production — Single Region)

| Component | Sizing | Est. Monthly Cost |
|-----------|--------|:-----------------:|
| ECS Fargate (8 services, avg 2 tasks each) | ~16 tasks × 0.5 vCPU × 1 GB | $200-400 |
| RDS PostgreSQL (Multi-AZ) | db.r6g.large, 100 GB | $300-400 |
| ElastiCache Redis | cache.r6g.large, Multi-AZ | $200-300 |
| ALB | 1 ALB + data processing | $50-100 |
| NAT Gateways (3 AZs) | Data processing | $100-200 |
| S3 | 100 GB + requests | $10-30 |
| Bedrock (LLM inference) | Variable by usage | $500-5000 |
| CloudWatch | Logs + metrics | $50-100 |
| Secrets Manager | ~20 secrets | $10 |
| **Total (excl. Bedrock)** | | **$900-1500** |
| **Total (incl. Bedrock)** | | **$1400-6500** |

---

## Deployment Environments

| Environment | Cluster | Purpose | Scaling |
|-------------|---------|---------|---------|
| **dev** | onpremai-dev | Developer testing | 1 task per service, no Multi-AZ |
| **staging** | onpremai-staging | Integration/QA | 1-2 tasks, full service set |
| **production** | onpremai-prod | Customer-facing | 2+ tasks, Multi-AZ, auto-scaling |

All environments use the same Docker images — only configuration (env vars, secrets) differs.
