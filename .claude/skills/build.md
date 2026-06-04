---
name: build
description: Build Docker images for services in this compliance AI system. Use this skill when the user says "build", "docker build", "rebuild", "build images", or needs to create container images before deploying. Also use when build fails and user needs troubleshooting help.
---

# Build

Build Docker images for all services. Validates Dockerfiles, checks image sizes, and ensures builds succeed before deploy.

## Build a Single Service

```bash
cd /Users/indukuk/onpremai/{service-name}
docker build --platform linux/amd64 --provenance=false -t onpremai/{service-name}:dev .
```

## Build All Services

```bash
docker compose build
```

## Build with No Cache (clean rebuild)

```bash
docker compose build --no-cache {service-name}
```

## Pre-Build Validation

Before building, check these — a missing file means the build will fail and waste time:

1. Dockerfile exists in service directory
2. requirements.txt or pyproject.toml exists
3. No secrets in Dockerfile (no hardcoded keys, passwords, tokens)
4. .dockerignore exists (excludes .env, __pycache__, .git, .venv)

## Post-Build Checks

```bash
# Image size (flag if > 1GB)
docker images onpremai/{service-name}:dev --format "{{.Size}}"

# Quick health check
docker run --rm -d -p 8099:8080 --name build-test onpremai/{service-name}:dev \
  && sleep 3 \
  && curl -sf http://localhost:8099/health \
  && docker stop build-test

# Vulnerability scan (if docker scout available)
docker scout cves onpremai/{service-name}:dev 2>/dev/null
```

## Image Naming

| Context | Tag |
|---------|-----|
| Development | `onpremai/{service}:dev` |
| Versioned | `onpremai/{service}:{version}` |

Services: compliance-assistant, agent-eval, llm-gateway, memory-service, observer, sandbox-service, preprocessor

## Common Build Failures

| Symptom | Cause | Fix |
|---------|-------|-----|
| `pip install` fails | Version conflict or typo in requirements.txt | Check package names, pin compatible versions |
| Image > 1GB | Missing .dockerignore, dev deps included | Add multi-stage build, exclude dev packages |
| Platform mismatch | M1/ARM vs x86 | Always use `--platform linux/amd64` |
| COPY fails | File path wrong or missing | Check paths relative to build context |
| Permission denied at runtime | Running as root, volume ownership | Add `USER 65534` in Dockerfile |
