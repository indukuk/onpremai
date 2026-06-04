---
name: deploy
description: Deploy services using Docker Compose for this compliance AI system. Use this skill when the user says "deploy", "start services", "docker compose up", "bring up", "launch", "ship it", or needs to update a running service. Also use for rollbacks, troubleshooting stuck containers, or post-deploy validation including Playwright smoke tests.
---

# Deploy

Deploy services using Docker Compose. Handles single-service updates, full stack deployment, rollbacks, and post-deploy validation with Playwright smoke testing.

## Pre-Deploy Checklist

Run all of these — skipping one causes mysterious failures:

```bash
# 1. Validate compose config
docker compose config --quiet

# 2. Check .env exists
test -f .env && echo "OK" || echo "MISSING .env"

# 3. Check images exist
docker compose images

# 4. Check what's running
docker compose ps

# 5. Check port conflicts
lsof -i :8080 -i :4000 -i :5000 -i :9000 -i :5432 -i :6379 2>/dev/null
```

## Deploy Commands

```bash
# Full stack
docker compose up -d

# Single service (no-downtime update)
docker compose up -d --no-deps {service-name}

# With local LLM
docker compose --profile local-llm up -d
```

## Post-Deploy Validation

After every deploy, verify the service actually works — a container running is not the same as a service healthy:

```bash
# 1. Wait for health
docker compose ps {service}  # should show "healthy"

# 2. Check endpoints
curl -sf http://localhost:{port}/health | jq .
curl -sf http://localhost:{port}/ready | jq .

# 3. Check logs for errors
docker compose logs --tail 30 {service} | grep -i "error\|exception\|traceback"

# 4. Verify inter-service connectivity
docker compose exec {service} curl -sf http://llm-gateway:4000/health
docker compose exec {service} curl -sf http://memory-service:5000/health
```

## Playwright Smoke Tests

For services with web dashboards or complex API flows, use Playwright MCP to validate end-to-end after deploy:

**Browser-based validation:**
- Navigate to service dashboard, verify it renders
- Submit a test request through the UI, verify response
- Check WebSocket connections establish
- Take a screenshot as evidence of working state

**API smoke test pattern:**
```bash
# Quick smoke: submit a minimal request and verify 200
curl -sf -X POST http://localhost:8080/evaluate \
  -H "Content-Type: application/json" \
  -d '{"control_id":"CC6.1","framework":"SOC2","evidence":[]}' \
  | jq '.score'
```

## Rollback

```bash
# Single service — use previous version tag
EVAL_VERSION=1.4.9 docker compose up -d --no-deps agent-eval

# Full stack — revert to known-good
docker compose down
git checkout {previous-tag} -- docker-compose.yml .env
docker compose up -d
```

## Troubleshooting

| Symptom | Diagnosis | Fix |
|---------|-----------|-----|
| Restart loop | `docker compose logs {service}` | Fix startup error in code/config |
| Port conflict | `lsof -i :{port}` | Stop conflicting process or change port |
| Volume permissions | Check Dockerfile USER vs mount ownership | Fix UID in Dockerfile |
| Out of disk | `docker system df` | `docker system prune -f` (removes unused) |
| Unhealthy after 60s | Health check failing | Check health endpoint manually |

## Destructive Operations — Confirm Before Running

These lose data and cannot be undone:
- `docker compose down -v` — deletes all volumes including database data
- `docker system prune -a` — removes all images
- Modifying .env secrets
- Deploying to anything that isn't local development
