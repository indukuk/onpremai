---
name: test
description: Run and write tests for services in this compliance AI system. Use this skill when the user says "test", "run tests", "pytest", "check coverage", "write tests", "add test for", or asks if something works. Also use when tests fail and user needs help debugging, or before any deploy to validate code correctness. Includes Playwright-based E2E testing for API validation and UI flows.
---

# Test

Run and write tests for all services. Unit tests, integration tests, Playwright-based E2E validation. The test gate blocks deploys — nothing ships without passing.

## Quick Commands

```bash
# Unit tests for one service
cd /Users/indukuk/onpremai/{service-name}
python -m pytest tests/unit/ -v

# With coverage
python -m pytest tests/ -v --cov=src --cov-report=term-missing

# Integration tests (needs Docker for test DBs)
python -m pytest tests/integration/ -v

# E2E tests (full stack must be running)
python -m pytest tests/e2e/ -v

# Lint + format check
ruff check src/ tests/ && ruff format --check src/ tests/
```

## Test Structure

```
{service}/tests/
├── unit/           # No external deps, fast, mocked
│   ├── test_*.py
│   └── conftest.py
├── integration/    # Real DB/Redis via testcontainers
│   ├── test_*.py
│   └── conftest.py
├── e2e/            # Full stack via Playwright/httpx
│   ├── test_*.py
│   └── conftest.py
└── fixtures/
    ├── evidence/       # Sample CSV, PDF, Excel files
    ├── criteria/       # Testing criteria JSON
    ├── llm_responses/  # Mock LLM responses
    └── memory/         # Sample tenant/user memory
```

## What to Test Per Service

**common/** — LLMClient retry/timeout, MemoryClient graceful degradation, StorageClient get/put/list, SandboxClient timeout/error handling

**compliance-assistant** — Context builder prompt composition, skill matcher activation, playbook state transitions, agent loop tool call processing

**agent-eval** — Rule engine deterministic PASS/FAIL, scoring formula with weights, evidence prep VLM routing, graph routing state transitions

**llm-gateway** — Routing resolution (agent+task+tenant → model), escalation on low confidence, provider adapter format translation

**memory-service** — Deduplication (similar facts → update not insert), task transitions on overdue, semantic search ranking, skill versioning

**sandbox-service** — Execution stdout capture, blocked import rejection, timeout kill, concurrent request queueing

## Playwright E2E Testing

For services with HTTP APIs, use Playwright to validate the full request/response cycle against a running stack. Playwright MCP is available for browser-based validation.

**API E2E with Playwright (when service has a web UI or dashboard):**
```python
import pytest
from playwright.async_api import async_playwright

@pytest.mark.asyncio
async def test_health_dashboard():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.goto("http://localhost:8080/dashboard")
        await page.wait_for_selector("[data-testid='health-status']")
        status = await page.text_content("[data-testid='health-status']")
        assert status == "healthy"
        await browser.close()
```

**API E2E with httpx (for pure API services):**
```python
import httpx
import pytest

@pytest.mark.asyncio
async def test_evaluation_flow():
    async with httpx.AsyncClient(base_url="http://localhost:8080") as client:
        # Submit evaluation
        resp = await client.post("/evaluate", json={
            "control_id": "CC6.1",
            "framework": "SOC2",
            "evidence": [{"type": "csv", "key": "access-logs.csv"}]
        })
        assert resp.status_code == 200
        result = resp.json()
        assert result["score"] >= 0
        assert result["score"] <= 100
```

**Using Playwright MCP for interactive testing:**

When the Playwright MCP server is connected, use it to:
- Navigate to service dashboards and verify rendered state
- Fill forms and submit to test input validation
- Take screenshots for visual regression
- Test WebSocket connections and live updates
- Validate CORS and auth flows in a real browser

## Writing Good Tests

**Unit tests — fast, isolated, mocked:**
```python
@pytest.mark.asyncio
async def test_scoring_formula():
    criteria = [
        CriterionResult(id="1", passed=True, weight=0.6),
        CriterionResult(id="2", passed=False, weight=0.4),
    ]
    score = calculate_score(criteria)
    assert score == 60.0
```

**Integration tests — real services via testcontainers:**
```python
@pytest.fixture
async def pg():
    container = PostgresContainer("postgres:15")
    container.start()
    yield container.get_connection_url()
    container.stop()
```

## CI Gate (must pass before deploy)

1. `ruff check .` — zero lint errors
2. `pytest tests/unit/` — 100% pass
3. `pytest tests/integration/` — 100% pass
4. Coverage > 80% for new code
5. No new security findings

## Debugging Test Failures

| Symptom | Fix |
|---------|-----|
| Async test not running | Add `@pytest.mark.asyncio`, check pytest-asyncio in conftest |
| Import error | Check PYTHONPATH includes src/ |
| Testcontainers failing | Docker must be running |
| Flaky test | Timing issue — use `asyncio.wait_for` with timeout |
| Playwright timeout | Increase timeout, check service is actually running |
