# Skill: Deploy

## Purpose
Deploy services using Docker Compose. Handle single-service updates, full stack deployment, and rollbacks.

## Tech Stack
- Docker Compose (primary orchestration)
- Docker images (pre-built)
- Volumes for persistence (pgdata, redis, minio, ollama)
- Environment-based configuration (.env file)

## When to use
- User says "deploy", "start services", "docker compose up", "bring up"
- After successful build
- When updating a single service version

## Instructions

### Pre-deploy checklist
1. Verify .env file exists with required variables
2. Verify docker-compose.yml is valid: `docker compose config --quiet`
3. Verify required images exist: `docker compose images`
4. Check if any services are already running: `docker compose ps`
5. Verify no port conflicts: `lsof -i :8080 -i :4000 -i :5000 -i :9000 -i :5432 -i :6379`

### Deploy full stack
```bash
docker compose up -d
```

### Deploy single service (no-downtime update)
```bash
# Pull/build new image first
docker compose up -d --no-deps {service-name}
```

### Deploy with local LLM
```bash
docker compose --profile local-llm up -d
```

### Post-deploy verification
1. Wait for health checks: `docker compose ps` (all should show "healthy")
2. Check logs for startup errors: `docker compose logs --tail 20 {service}`
3. Run diagnostics if available: `docker compose exec compliance-assistant python -m diagnostics`
4. Verify connectivity between services:
   - `docker compose exec compliance-assistant curl -sf http://llm-gateway:4000/health`
   - `docker compose exec compliance-assistant curl -sf http://memory-service:5000/health`
   - `docker compose exec agent-eval curl -sf http://sandbox-service:9000/health`

### Rollback single service
```bash
# Set previous version in .env or override
EVAL_VERSION=1.4.9 docker compose up -d --no-deps agent-eval
```

### Rollback entire stack
```bash
# Stop current
docker compose down

# Checkout previous known-good state
git checkout {previous-tag} -- docker-compose.yml .env

# Redeploy
docker compose up -d
```

### Troubleshooting
- Container restart loop → `docker compose logs {service}` (check startup errors)
- Port conflict → `docker compose down` then re-up, or change ports in docker-compose.override.yml
- Volume permission issue → `docker compose down -v {service}` (WARNING: deletes data)
- Out of disk → `docker system prune -f` (removes unused images/containers)

### NEVER do without asking
- `docker compose down -v` (deletes all volumes/data)
- `docker system prune -a` (removes all images)
- Modify .env secrets without confirmation
- Deploy to any environment that isn't local development
