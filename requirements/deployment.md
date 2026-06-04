# Deployment: Docker Compose Architecture

## Purpose

Define how all services are packaged, deployed, versioned, and upgraded as a single system using Docker Compose. No Kubernetes. Simple enough for a single `docker compose up -d`.

## Platform Strategy: AWS-First with Adapter Decoupling

The system is **built first for AWS** (Bedrock, S3, RDS, ElastiCache) but decoupled via adapters so it can run on-prem or on other clouds without code changes.

| Layer | AWS (V1 default) | On-Prem (future) | What Decouples |
|-------|------------------|-------------------|----------------|
| LLM inference | Bedrock (Converse API) | Ollama / vLLM | Gateway provider adapters |
| Object storage | S3 | MinIO | StorageClient adapter |
| Database | RDS PostgreSQL + pgvector | Local PostgreSQL | Connection string (same engine) |
| Cache | ElastiCache Redis | Local Redis | Connection string (same engine) |
| Embeddings | Titan Embed v2 via Bedrock | nomic-embed-text via Ollama | Gateway embed endpoint |
| OCR | Textract | Tesseract | Preprocessor extraction backend |
| Compute | ECS Fargate / EC2 | Docker Compose | Container orchestration |
| Auth | Cognito / custom JWT | Any JWT issuer | MCP module validates tokens |

**Switching from AWS to on-prem** requires:
1. Change `config/routing.yaml` (point tiers at local models)
2. Change `.env` (set `STORAGE_BACKEND=minio`, local DB connection strings)
3. Bring up local infrastructure containers (postgres, redis, minio, ollama)

Zero code changes. Zero image rebuilds.

## System Requirements Covered

| System Requirement | This document's role | Section |
|---|---|---|
| AWS-First w/ Adapters | Profiles switch between AWS cloud and local infrastructure | §Platform Strategy, §Deployment Profiles |
| Per-Tenant Budget | Budget limits configured in routing.yaml, PII_HMAC_KEY in secrets | §Secrets Management |
| Observability | Health checks for all services, log retention config | §Health Checks, §Log Retention |
| Independent Deploy | Per-service version tags, `--no-deps` upgrade, rollback | §Version Management, §Upgrade Commands |
| Hot-Reload Config | routing.yaml mounted as volume, editable without restart | §Directory Structure |
| PII-Aware Logging | PII_HMAC_KEY in secrets config | §Secrets Management |

## Principles

1. Each service is ONE container, ONE image, ONE version
2. Upgrade any service independently without touching others
3. Swap LLMs by editing a YAML file, not code
4. Works air-gapped (no internet) with local LLMs
5. Works hybrid (local + cloud) with LLM gateway routing
6. Works cloud-only (all inference via API) — **this is the default**
7. Customer deploys with a single command
8. Per-tenant budget tracking — one customer's exhaustion never affects another

## Service Map

| Service | Image | Port | Depends On | GPU |
|---------|-------|:----:|------------|:---:|
| agent-eval | `yourorg/compliance-agent-eval` | 8081 | llm-gateway, memory, storage, sandbox | No |
| compliance-assistant | `yourorg/compliance-compliance-assistant` | 8082 | llm-gateway, memory, backend | No |
| backend | `yourorg/compliance-backend` | 8080 | postgres, storage | No |
| preprocessor | `yourorg/compliance-preprocessor` | 7000 | storage, memory | No |
| sandbox-service | `yourorg/compliance-sandbox-service` | 9000 | storage, docker socket | No |
| llm-gateway | `yourorg/compliance-llm-gateway` | 4000, 4001 | models | No |
| memory-service | `yourorg/compliance-memory` | 5000 | postgres, redis, llm-gateway | No |
| observer | `yourorg/compliance-observer` | 6000 | llm-gateway, memory | No |
| api-gateway | `yourorg/compliance-api-gateway` | 8080 | agent-eval, compliance-assistant | No |
| postgres | `pgvector/pgvector:pg16` | 5432 | — | No |
| redis | `redis:7-alpine` | 6379 | — | No |
| minio | `minio/minio` | 9000, 9001 | — | No |
| ollama | `ollama/ollama` | 11434 | — | Optional |
| vllm | `vllm/vllm-openai` | 8000 | — | Yes |

## Version Management

```bash
# .env — each service versioned independently
EVAL_VERSION=1.5.0
ASSISTANT_VERSION=2.1.0
PREPROC_VERSION=1.0.3
SANDBOX_VERSION=1.0.0
BACKEND_VERSION=1.0.0
LLM_GW_VERSION=1.2.0
MEMORY_VERSION=1.0.0
OBSERVER_VERSION=1.0.0
GATEWAY_VERSION=1.1.0
```

## Upgrade Commands

```bash
# Upgrade single agent (zero-downtime for other services)
EVAL_VERSION=1.5.1 docker compose up -d --no-deps agent-eval

# Upgrade chat agent
ASSISTANT_VERSION=2.2.0 docker compose up -d --no-deps compliance-assistant

# Swap LLM model (no container rebuild)
vim config/routing.yaml
docker compose restart llm-gateway

# Upgrade everything
docker compose pull
docker compose up -d

# Rollback single service
EVAL_VERSION=1.4.9 docker compose up -d --no-deps agent-eval
```

## Deployment Profiles

```yaml
# Base: AWS cloud mode (Bedrock for LLM, S3 for storage, RDS for DB)
# This is the default — services connect to AWS infrastructure via IAM
docker compose up -d

# Local development (adds local postgres, redis, minio)
docker compose --profile local-infra up -d

# With local LLM (Ollama — for dev/testing without Bedrock costs)
docker compose --profile local-infra --profile local-llm up -d

# With production local LLM (vLLM — multi-GPU, high throughput)
docker compose --profile local-infra --profile local-llm-prod up -d

# Air-gapped (no cloud, all local — full on-prem deployment)
docker compose --profile local-infra --profile local-llm --profile air-gapped up -d
```

## Directory Structure (customer deployment)

```
/opt/compliance/
├── docker-compose.yml              # service definitions
├── docker-compose.override.yml     # customer-specific (ports, resources)
├── .env                            # versions + secrets
├── config/
│   ├── routing.yaml                # LLM routing (hot-reloadable)
│   ├── observer_policy.yaml        # observer behavior
│   └── approvals.yaml              # tool approval rules
├── data/                           # persistent volumes (auto-created)
│   ├── postgres/
│   ├── redis/
│   ├── minio/
│   └── ollama_models/
└── logs/                           # gateway logs (observer reads)
```

## Air-Gapped Deployment

For customers with no internet:

```bash
# Build offline package (on build machine with internet)
./scripts/package-offline.sh v1.5.0

# Output: compliance-v1.5.0-offline.tar.gz containing:
#   - All Docker images as tar
#   - LLM model weights (e.g., Llama 3.1 70B GGUF)
#   - Config templates
#   - Install script

# On customer machine (no internet)
tar xzf compliance-v1.5.0-offline.tar.gz
cd compliance-v1.5.0
./install.sh

# install.sh does:
#   docker load < images/*.tar
#   cp config/* /opt/compliance/config/
#   ollama import model.gguf  (if local LLM profile)
#   docker compose up -d
```

## Health Checks

```yaml
# All services expose health/readiness
healthcheck:
  test: ["CMD", "curl", "-f", "http://localhost:PORT/health"]
  interval: 30s
  timeout: 5s
  retries: 3
  start_period: 30s
```

## Resource Limits (configurable per customer)

```yaml
# docker-compose.override.yml (customer-specific)
services:
  agent-eval:
    deploy:
      resources:
        limits:
          memory: 2G
          cpus: "2.0"

  llm-gateway:
    deploy:
      resources:
        limits:
          memory: 512M
          cpus: "1.0"

  memory-service:
    deploy:
      resources:
        limits:
          memory: 1G

  ollama:
    deploy:
      resources:
        limits:
          memory: 32G        # for 70B model
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
```

## Networking

```yaml
networks:
  internal:
    driver: bridge
    # All services on internal network
    # Only api-gateway exposed externally

  # api-gateway is the only service with external port mapping
  # Everything else communicates via Docker DNS (service names)
```

## Secrets Management

```bash
# .env file — AWS-first defaults
DB_HOST=compliance-db.cluster-xyz.us-east-1.rds.amazonaws.com
DB_PASSWORD=changeme
AWS_REGION=us-east-1
STORAGE_BACKEND=s3
STORAGE_BUCKET=compliance-artifacts
# Bedrock auth: uses IAM role (no API keys needed on ECS/EC2)
# Anthropic direct API (fallback): only if using direct API as Bedrock fallback
ANTHROPIC_API_KEY=sk-ant-...

# For local development:
# STORAGE_BACKEND=minio
# STORAGE_ENDPOINT=http://minio:9000
# STORAGE_ACCESS_KEY=minioadmin
# STORAGE_SECRET_KEY=minioadmin
# DB_HOST=postgres
# STATE_DSN=postgresql://compliance:pass@postgres:5432/compliance

# For production: AWS Secrets Manager or Parameter Store
# Services read secrets via IAM role — no keys in .env
```

## Monitoring (optional add-on)

```yaml
# docker-compose.monitoring.yml (opt-in)
services:
  prometheus:
    image: prom/prometheus
    profiles: ["monitoring"]
    volumes: ["./config/prometheus.yml:/etc/prometheus/prometheus.yml"]

  grafana:
    image: grafana/grafana
    profiles: ["monitoring"]
    ports: ["3000:3000"]
```

## Backup

```bash
# Automated backup script
./scripts/backup.sh

# Backs up:
#   - PostgreSQL (pg_dump)
#   - MinIO data (mc mirror)
#   - Config files
#   - .env (minus secrets)
# To: /opt/compliance/backups/YYYY-MM-DD/

# Restore
./scripts/restore.sh /opt/compliance/backups/2026-05-10/
```

## Minimum Hardware Requirements

| Deployment Type | CPU | RAM | GPU | Disk |
|----------------|:---:|:---:|:---:|:----:|
| Cloud-only (no local LLM) | 4 cores | 8 GB | None | 50 GB |
| Local LLM (8B model) | 8 cores | 32 GB | 1x RTX 4090 or A100 | 100 GB |
| Local LLM (70B model) | 16 cores | 64 GB | 2x A100 80GB | 200 GB |
| Production (70B + redundancy) | 32 cores | 128 GB | 4x A100 80GB | 500 GB |
