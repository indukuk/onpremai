# Skill: Test

## Purpose
Run tests for all services. Unit tests, integration tests, and end-to-end validation. Ensure code quality before build/deploy.

## Tech Stack
- pytest (test runner)
- pytest-asyncio (async test support)
- pytest-cov (coverage)
- httpx (async HTTP client for testing FastAPI)
- testcontainers (PostgreSQL, Redis for integration tests)
- Docker Compose (for E2E tests)

## When to use
- User says "test", "run tests", "pytest", "check if it works"
- Before committing code changes
- After implementing a new feature
- Before deploy (gate)

## Instructions

### Run unit tests for a single service
```bash
cd /Users/indukuk/onpremai/{service-name}
python -m pytest tests/unit/ -v
```

### Run integration tests (requires Docker for test DBs)
```bash
cd /Users/indukuk/onpremai/{service-name}
python -m pytest tests/integration/ -v
```

### Run all tests for a service with coverage
```bash
cd /Users/indukuk/onpremai/{service-name}
python -m pytest tests/ -v --cov=src --cov-report=term-missing
```

### Run E2E tests (full stack must be running)
```bash
# Ensure stack is up
docker compose up -d

# Run E2E
python -m pytest tests/e2e/ -v
```

### Test structure per service
```
{service}/
├── tests/
│   ├── unit/           # No external deps, fast, mocked
│   │   ├── test_*.py
│   │   └── conftest.py
│   ├── integration/    # Real DB/Redis via testcontainers
│   │   ├── test_*.py
│   │   └── conftest.py
│   └── e2e/            # Full stack running
│       ├── test_*.py
│       └── conftest.py
```

### What to test per service

**common/**
- LLMClient: mock gateway responses, verify retry logic, timeout handling
- MemoryClient: mock memory-service responses, verify graceful degradation
- StorageClient: mock S3/MinIO, verify get/put/list operations
- SandboxClient: mock sandbox responses, verify timeout/error handling

**compliance-assistant**
- Context builder: given user role + memory, verify correct prompt composition
- Skill matcher: given message + skills, verify correct skill activation
- Playbook engine: given step + user input, verify state transitions
- Agent loop: mock LLM + MCP, verify tool call processing

**agent-eval**
- Rule engine: given evidence + criteria, verify deterministic PASS/FAIL
- Scoring formula: given criterion results + weights, verify correct score
- Evidence prep: given file types, verify correct VLM routing
- Graph routing: given state, verify correct next node

**llm-gateway**
- Routing resolution: given agent+task+tenant, verify correct model
- Escalation: given low confidence response, verify retry at higher tier
- Provider adapters: given request, verify correct format per provider
- Tool translation: given OpenAI format tools, verify Anthropic/Bedrock translation

**memory-service**
- Deduplication: given similar facts, verify update (not insert)
- Task transitions: given overdue date, verify status change
- Semantic search: given query + embedded facts, verify ranking
- Skill versioning: given update, verify version increment + history

**sandbox-service**
- Execution: given code + files, verify stdout capture
- Security: given blocked import, verify rejection
- Timeout: given long-running code, verify kill after limit
- Concurrency: given N concurrent requests, verify queue behavior

### Quick validation commands
```bash
# Lint (all services)
ruff check .

# Type check (if using mypy)
mypy src/ --ignore-missing-imports

# Format check
ruff format --check .
```

### Test fixtures for compliance domain
- Sample evidence files (CSV, PDF, Excel) in `tests/fixtures/`
- Sample testing criteria (JSON) in `tests/fixtures/criteria/`
- Mock LLM responses (JSON) in `tests/fixtures/llm_responses/`
- Sample tenant/user memory in `tests/fixtures/memory/`

### CI test gate (before merge/deploy)
1. `ruff check .` — must pass (no lint errors)
2. `pytest tests/unit/` — must pass (100%)
3. `pytest tests/integration/` — must pass (100%)
4. Coverage must be > 80% for new code
5. No new security findings (see security skill)

### Common test issues
- Async test not running → add `@pytest.mark.asyncio` and `pytest-asyncio` in conftest
- Import error → check PYTHONPATH includes src/
- Testcontainers failing → Docker must be running
- Flaky test → likely timing issue, use `asyncio.wait_for` with timeout
