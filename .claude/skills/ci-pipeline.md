# Skill: CI Pipeline (Orchestrator)

## Purpose
Orchestrate the full build → test → security → deploy pipeline. This is the meta-skill that chains the other skills together.

## When to use
- User says "run pipeline", "CI", "build and deploy", "ship it"
- After completing a feature implementation
- Before a release

## Instructions

### Full Pipeline (in order)

```
Step 1: LINT & FORMAT
  → ruff check . && ruff format --check .
  → GATE: must pass (zero errors)

Step 2: UNIT TESTS
  → pytest tests/unit/ -v --cov=src
  → GATE: must pass, coverage > 80%

Step 3: BUILD
  → docker compose build {service}
  → GATE: build succeeds, image < 2GB

Step 4: SECURITY REVIEW
  → Run automated security checks
  → Review changed files manually
  → GATE: no Critical/High findings

Step 5: INTEGRATION TESTS
  → docker compose up -d (test stack)
  → pytest tests/integration/ -v
  → GATE: must pass

Step 6: DEPLOY
  → docker compose up -d --no-deps {service}
  → Verify health checks pass
  → Run smoke test

Step 7: POST-DEPLOY VALIDATION
  → Hit /health and /ready on all services
  → Run diagnostics
  → Check logs for errors (first 30s)
```

### Quick Pipeline (for small changes)
```
lint → unit tests → build → deploy
```
Skip security review and integration tests for trivial changes (typos, config, docs).

### Which services to build/test/deploy
- Determine from changed files:
  - `common/` changed → rebuild ALL services (shared library)
  - `compliance-assistant/` changed → rebuild only compliance-assistant
  - `agent-eval/` changed → rebuild only agent-eval
  - `docker-compose.yml` changed → redeploy all
  - `config/routing.yaml` changed → restart llm-gateway only (no rebuild)

### Pipeline failure handling
- Lint fails → show errors, suggest fixes, do NOT continue
- Tests fail → show failures, do NOT build/deploy
- Build fails → show error output, suggest fix
- Security fails → show findings, block deploy, suggest remediations
- Integration fails → show test output, rollback if already deployed
- Deploy fails → show logs, suggest rollback

### Output format
```
╔═══════════════════════════════════════╗
║        CI PIPELINE RESULTS            ║
╠═══════════════════════════════════════╣
║ Step          │ Status │ Duration     ║
╠═══════════════════════════════════════╣
║ Lint          │ ✅ PASS│ 2.1s         ║
║ Unit Tests    │ ✅ PASS│ 8.4s (92%)   ║
║ Build         │ ✅ PASS│ 45s (312MB)  ║
║ Security      │ ✅ PASS│ 3.2s         ║
║ Integration   │ ✅ PASS│ 22s          ║
║ Deploy        │ ✅ PASS│ 5.1s         ║
║ Validation    │ ✅ PASS│ 4.0s         ║
╠═══════════════════════════════════════╣
║ RESULT: DEPLOYED ✅                   ║
╚═══════════════════════════════════════╝
```
