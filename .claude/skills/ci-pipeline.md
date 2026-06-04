---
name: ci-pipeline
description: Orchestrate the full CI/CD pipeline (lint → test → build → security → deploy) for this compliance AI system. Use this skill when the user says "run pipeline", "CI", "build and deploy", "ship it", "release", or after completing a feature implementation and wanting to push it through all gates. Also triggers for "what's the deploy status" or "is it safe to deploy."
---

# CI Pipeline (Orchestrator)

Chain lint → test → build → security → deploy in sequence. Each step is a gate — failure blocks everything downstream.

## Full Pipeline

```
Step 1: LINT & FORMAT
  → ruff check . && ruff format --check .
  → GATE: zero errors

Step 2: UNIT TESTS
  → pytest tests/unit/ -v --cov=src
  → GATE: 100% pass, coverage > 80%

Step 3: BUILD
  → docker compose build {service}
  → GATE: builds succeed, image < 2GB

Step 4: SECURITY REVIEW
  → Automated checks + manual review
  → GATE: no Critical/High findings

Step 5: INTEGRATION TESTS
  → docker compose up -d (test stack)
  → pytest tests/integration/ -v
  → GATE: 100% pass

Step 6: E2E VALIDATION (Playwright)
  → Playwright smoke tests against running stack
  → GATE: all critical paths pass

Step 7: DEPLOY
  → docker compose up -d --no-deps {service}
  → Verify health checks pass
  → GATE: /health and /ready return OK

Step 8: POST-DEPLOY VALIDATION
  → Hit all endpoints, check logs (30s)
  → Playwright visual regression if applicable
  → GATE: no errors in logs
```

## Quick Pipeline (trivial changes)

For typos, config, docs — skip security and integration:
```
lint → unit tests → build → deploy
```

## Determine What to Build

From changed files:
- `common/` → rebuild ALL services (shared library)
- `{service}/` → rebuild only that service
- `docker-compose.yml` → redeploy all
- `config/routing.yaml` → restart llm-gateway only (no rebuild)

## Playwright E2E Step

After the stack is running, validate critical paths with Playwright:

```python
# tests/e2e/test_smoke.py
async def test_full_evaluation_flow(page):
    """Submit evaluation request and verify result renders."""
    await page.goto("http://localhost:8080")
    await page.fill("[data-testid='control-id']", "CC6.1")
    await page.click("[data-testid='submit-eval']")
    await page.wait_for_selector("[data-testid='score']")
    score = await page.text_content("[data-testid='score']")
    assert int(score) >= 0

async def test_api_health_all_services():
    """Verify every service responds to health check."""
    services = [
        ("compliance-assistant", 8080),
        ("agent-eval", 8081),
        ("llm-gateway", 4000),
        ("memory-service", 5000),
    ]
    async with httpx.AsyncClient() as client:
        for name, port in services:
            resp = await client.get(f"http://localhost:{port}/health")
            assert resp.status_code == 200, f"{name} health failed"
```

## Failure Handling

| Step | Fails | Action |
|------|-------|--------|
| Lint | Show errors, suggest fix | Do NOT continue |
| Tests | Show failures | Do NOT build/deploy |
| Build | Show error output | Fix Dockerfile or code |
| Security | Show findings | Block deploy |
| Integration | Show test output | Rollback if deployed |
| E2E/Playwright | Show screenshots + errors | Block deploy |
| Deploy | Show logs | Suggest rollback |

## Pipeline Results Format

```
╔═══════════════════════════════════════╗
║        CI PIPELINE RESULTS            ║
╠═══════════════════════════════════════╣
║ Step          │ Status │ Duration     ║
╠═══════════════════════════════════════╣
║ Lint          │ PASS   │ 2.1s         ║
║ Unit Tests    │ PASS   │ 8.4s (92%)   ║
║ Build         │ PASS   │ 45s (312MB)  ║
║ Security      │ PASS   │ 3.2s         ║
║ Integration   │ PASS   │ 22s          ║
║ E2E/Playwright│ PASS   │ 12s          ║
║ Deploy        │ PASS   │ 5.1s         ║
║ Validation    │ PASS   │ 4.0s         ║
╠═══════════════════════════════════════╣
║ RESULT: DEPLOYED                      ║
╚═══════════════════════════════════════╝
```
