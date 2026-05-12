# Skill: Build

## Purpose
Build Docker images for all services in this project. Validate Dockerfiles, check image sizes, and ensure builds succeed.

## Tech Stack
- Python 3.11 (all services)
- FastAPI (API services)
- Docker multi-stage builds
- Docker Compose for orchestration

## When to use
- User says "build", "docker build", "build images", "rebuild"
- After code changes that need new images
- Before deploy

## Instructions

### Build a single service
```bash
cd /Users/indukuk/onpremai/{service-name}
docker build --platform linux/amd64 --provenance=false -t onpremai/{service-name}:dev .
```

### Build all services
```bash
docker compose build
```

### Build with no cache (clean rebuild)
```bash
docker compose build --no-cache {service-name}
```

### Validate before build
1. Check Dockerfile exists in service directory
2. Check requirements.txt or pyproject.toml exists
3. Verify no secrets in Dockerfile (no hardcoded keys, passwords, tokens)
4. Verify .dockerignore exists (excludes .env, __pycache__, .git, .venv)

### After build
1. Report image size: `docker images onpremai/{service-name}:dev --format "{{.Size}}"`
2. Check for vulnerabilities: `docker scout cves onpremai/{service-name}:dev` (if available)
3. Verify health endpoint works: `docker run --rm -d --name test onpremai/{service-name}:dev && sleep 3 && curl -sf http://localhost:{port}/health && docker stop test`

### Image naming convention
- Dev: `onpremai/{service}:dev`
- Tagged: `onpremai/{service}:{version}`
- Services: compliance-assistant, agent-eval, llm-gateway, memory-service, observer, sandbox-service, preprocessor

### Common build issues
- `pip install` fails → check requirements.txt for typos, version conflicts
- Image too large → check .dockerignore, use multi-stage build, remove dev dependencies
- Platform mismatch → always use `--platform linux/amd64`
