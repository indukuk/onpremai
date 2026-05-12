# Skill: Implement

## Purpose
Implement code for services in this project. Knows the architecture, conventions, and patterns to follow.

## Tech Stack
- Python 3.11+
- FastAPI (HTTP services)
- Pydantic (data models, validation)
- httpx (async HTTP client)
- asyncio (async operations)
- PostgreSQL + pgvector (via asyncpg or psycopg2)
- Redis (via redis-py async)
- Docker (containerization)
- pytest (testing)

## When to use
- User asks to implement a feature, service, endpoint, or module
- User asks to refactor existing code
- User asks to fix a bug

## Instructions

### Project structure per service
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

### Conventions

**FastAPI patterns:**
```python
# main.py structure
from fastapi import FastAPI, HTTPException, Depends
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: connect to services, log startup sequence
    await startup()
    yield
    # Shutdown: close connections gracefully
    await shutdown()

app = FastAPI(title="{service-name}", lifespan=lifespan)

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.get("/ready")
async def ready():
    # Check all dependencies
    return {"status": "ready", "dependencies": {...}}
```

**Configuration:**
```python
# config.py — always from environment with defaults
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

**Async-first:**
- All HTTP handlers are `async def`
- All external calls use `httpx.AsyncClient` (not `requests`)
- Use `asyncio.gather()` for parallel independent calls
- Use `asyncio.create_task()` for fire-and-forget (post-processing)

**Error handling:**
- Raise `HTTPException` for API errors (with appropriate status codes)
- Use structured logging for internal errors (never crash silently)
- Graceful degradation: if optional service is down, continue with reduced functionality

**Logging:**
```python
from common.logger import AgentLogger

logger = AgentLogger(agent_name="compliance-assistant")
logger.info("Request processed", control="CC6.1", duration_ms=4200)
```

**No hardcoded values:**
- No URLs, no model names, no secrets in source code
- All external references via config/environment
- All prompts loaded from memory service (with hardcoded fallback)

**Type hints everywhere:**
```python
async def evaluate_control(
    control_id: str,
    framework: str,
    evidence: list[Evidence],
) -> EvaluationResult:
```

### What NOT to do
- No global mutable state (use dependency injection)
- No `import *`
- No bare `except:` (always catch specific exceptions)
- No `print()` (use structured logger)
- No synchronous blocking calls in async context
- No secrets in source code, comments, or variable names
- No business logic in route handlers (keep them thin, delegate to service layer)

### When implementing a new service from scratch
1. Read REQUIREMENTS.md and DESIGN.md for that service
2. Create directory structure (as above)
3. Implement config.py first (all env vars with defaults)
4. Implement main.py with health/ready endpoints
5. Implement common/ client usage
6. Implement core business logic
7. Write unit tests alongside implementation
8. Create Dockerfile
9. Add to docker-compose.yml
10. Test locally: `docker compose up -d {service} && docker compose logs -f {service}`
