---
name: implement
description: Implement code for services in this compliance AI system. Use this skill whenever the user asks to implement a feature, write code, add an endpoint, create a module, refactor, fix a bug, or build any part of a service. Also triggers when user mentions coding patterns, conventions, or asks "how should I structure this code."
---

# Implement

Write production code for services in this on-prem compliance AI system. Every service follows identical patterns — this skill encodes those patterns so implementations stay consistent across the 8 services.

## Project Structure Per Service

```
{service}/
├── Dockerfile
├── requirements.txt
├── src/
│   ├── __init__.py
│   ├── main.py              # FastAPI app, routes, startup/shutdown
│   ├── config.py            # Environment-based configuration
│   ├── models.py            # Pydantic models (request/response)
│   └── {domain}/            # Business logic modules
├── tests/
│   ├── unit/
│   ├── integration/
│   └── conftest.py
└── common/                  # Copied shared libraries
    ├── llm_client.py
    ├── memory_client.py
    ├── storage_client.py
    ├── sandbox_client.py
    └── logger.py
```

## Implementation Order

When building from scratch, implement in this exact sequence — each step depends on the previous:

1. `src/config.py` — all env vars with defaults (other modules import this)
2. `src/models.py` — Pydantic request/response models (routes and logic reference these)
3. `src/main.py` — FastAPI skeleton with lifespan, health/ready
4. `src/{domain}/` — core business logic (the hard part)
5. Wire common/ clients into the domain layer
6. Connect routes to domain logic
7. Write tests alongside (unit first, integration after)
8. `Dockerfile` + `requirements.txt`
9. Update `docker-compose.yml` if new service

## Conventions

**FastAPI app structure:**
```python
from fastapi import FastAPI, HTTPException, Depends
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    await startup()
    yield
    await shutdown()

app = FastAPI(title="{service-name}", lifespan=lifespan)

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.get("/ready")
async def ready():
    return {"status": "ready", "dependencies": {...}}
```

**Configuration — always from environment:**
```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    llm_gateway_url: str = "http://llm-gateway:4000"
    memory_url: str = "http://memory-service:5000"
    storage_endpoint: str = "http://minio:9000"
    log_level: str = "info"

    class Config:
        env_file = ".env"

settings = Settings()
```

**Async-first everywhere:**
- All HTTP handlers are `async def`
- All external calls use `httpx.AsyncClient` (never `requests`)
- Use `asyncio.gather()` for parallel independent calls
- Use `asyncio.create_task()` for fire-and-forget post-processing

**Structured logging:**
```python
from common.logger import AgentLogger
logger = AgentLogger(agent_name="compliance-assistant")
logger.info("Request processed", control="CC6.1", duration_ms=4200)
```

**Type hints on everything** — parameters, returns, class attributes.

## What Never to Do

- No global mutable state (use dependency injection)
- No `import *`
- No bare `except:` (catch specific exceptions)
- No `print()` (use structured logger)
- No synchronous blocking in async context
- No secrets in source, comments, or variable names
- No business logic in route handlers (keep thin, delegate to service layer)
- No hardcoded URLs, model names, or provider IDs
- No direct `boto3` or provider SDK imports (use common/ abstractions)

## Validation Checklist

After writing each file, verify:
```bash
python -c "import ast; ast.parse(open('{file}').read())"
```

Before considering implementation complete:
- All files pass syntax check
- All imports resolve (no circular deps)
- Config has defaults for all env vars
- Health/ready endpoints exist and return correct schema
- Structured logging on startup with service identity
- Graceful degradation if optional deps are down
