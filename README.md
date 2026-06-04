# OnPremAI

AWS-first AI agent system for compliance SaaS, adapter-decoupled for future on-prem/hybrid deployments.

## Architecture

8 services, each independently deployable via Docker Compose:

| Service | Port | Role |
|---------|------|------|
| `llm-gateway` | 4000/4001 | Model routing, escalation, provider adapters |
| `memory-service` | 5000 | Shared memory with pgvector |
| `sandbox-service` | 6000 | Isolated code execution in ephemeral containers |
| `preprocessor` | 7000 | File ingestion (Excel/PDF/Word to metadata) |
| `agent-eval` | 8080 | 3-layer compliance evaluation pipeline |
| `compliance-assistant` | 8081 | User-facing Shadow AI (persona-based, skills/playbooks) |
| `observer` | 9000 | Autonomous improvement agent |
| `common/` | -- | Shared client libraries (copied into each image) |

All LLM calls route through `llm-gateway` using task-based routing (agents never specify model names). The `common/` library provides adapter-based clients for storage, LLM, memory, and sandbox access.

## Prerequisites

- Python 3.12+
- Docker and Docker Compose
- AWS CLI v2 (for deployment)
- Terraform 1.5+ (for AWS infrastructure)

## Quickstart

```bash
# Start all services locally
docker compose up -d

# Verify services are running
curl http://localhost:4000/health   # llm-gateway
curl http://localhost:5000/health   # memory-service
curl http://localhost:6000/health   # sandbox-service
curl http://localhost:7000/health   # preprocessor
curl http://localhost:8080/health   # agent-eval
curl http://localhost:8081/health   # compliance-assistant
curl http://localhost:9002/health   # observer (host port 9002)
```

Infrastructure services start automatically: PostgreSQL (5432), Redis (6379), MinIO (9000/9001).

## AWS Deployment

```bash
# Deploy full stack to a fresh AWS account
./deploy.sh dev

# Deploy to production
./deploy.sh prod
```

This creates VPC, ECS Fargate services, RDS PostgreSQL + pgvector, ElastiCache Redis, S3, ECR, Cognito, and ALB.

## Running Tests

```bash
# Run all tests
python -m pytest tests/ -v

# Run tests for a single service
python -m pytest tests/agent_eval/ -v

# With coverage
python -m pytest tests/ -v --cov=src --cov-report=term-missing

# Lint and format check
ruff check . && ruff format --check .
```

## Project Structure

```
onpremai/
├── agent-eval/          # 3-layer compliance evaluation engine
├── common/              # Shared client libraries (LLM, memory, storage, auth)
├── compliance-assistant/# User-facing Shadow AI service
├── config/              # Service configuration (routing.yaml)
├── infrastructure/      # Terraform modules for AWS deployment
├── llm-gateway/         # Model routing and provider abstraction
├── memory-service/      # pgvector-backed shared memory
├── observer/            # Autonomous improvement agent
├── preprocessor/        # File ingestion and metadata extraction
├── requirements/        # Design docs and requirements specs
├── sandbox-service/     # Isolated code execution
├── tests/               # Unit tests for all services
├── deploy.sh            # One-command AWS deployment script
└── docker-compose.yml   # Local development stack
```

## Documentation

See [.claude/CLAUDE.md](.claude/CLAUDE.md) for detailed architecture, client APIs, adapter patterns, degradation hierarchy, and development conventions.
