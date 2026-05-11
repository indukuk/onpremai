# Deployment: Docker Compose Architecture

## Purpose

Define how all services are packaged, deployed, versioned, and upgraded as a single system using Docker Compose. No Kubernetes. Simple enough for a single `docker compose up -d`.

## Principles

1. Each service is ONE container, ONE image, ONE version
2. Upgrade any service independently without touching others
3. Swap LLMs by editing a YAML file, not code
4. Works air-gapped (no internet) with local LLMs
5. Works hybrid (local + cloud) with LLM gateway routing
6. Works cloud-only (all inference via API)
7. Customer deploys with a single command

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
# Base: always runs (no LLM, cloud-only mode)
docker compose up -d

# With local LLM (Ollama — simple, single GPU)
docker compose --profile local-llm up -d

# With production local LLM (vLLM — multi-GPU, high throughput)
docker compose --profile local-llm-prod up -d

# Air-gapped (no cloud, all local)
docker compose --profile local-llm --profile air-gapped up -d
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
# .env file for simple deployments
DB_PASSWORD=changeme
STORAGE_ACCESS_KEY=minioadmin
STORAGE_SECRET_KEY=minioadmin
ANTHROPIC_API_KEY=sk-ant-...     # only if using cloud models

# For production: Docker secrets or external vault
# docker secret create db_password db_password.txt
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
