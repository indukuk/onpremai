---
name: security-review
description: Security audit for this compliance AI system before deploy. Use this skill before any deployment, when code changes touch auth/permissions/data handling/APIs, when adding dependencies, when modifying Docker configuration, or when the user asks "is this safe", "check for vulnerabilities", "security review", or "audit". Covers OWASP Top 10, secrets, container security, LLM-specific risks, and sandbox escape.
---

# Security Review

Review code and configuration for security vulnerabilities. This is the deploy gate — nothing ships with Critical or High findings.

## Automated Checks (run first)

```bash
# Hardcoded secrets
grep -rn "password\|secret\|api_key\|token" --include="*.py" --include="*.yaml" --include="*.yml" --include="*.env" . \
  | grep -v "__pycache__" | grep -v ".git/" | grep -v "test"

# .env not committed
git status | grep ".env"

# Dependency vulnerabilities
pip-audit -r requirements.txt 2>/dev/null || echo "pip-audit not installed"

# Dockerfile security (root, latest tags, secrets in args)
grep -n "USER root\|FROM.*:latest\|ARG.*SECRET\|ARG.*PASSWORD\|ARG.*KEY" */Dockerfile

# Unsafe Python patterns
grep -rn "eval(\|exec(\|pickle.loads\|yaml.load(\|subprocess.call(\|os.system(" --include="*.py" . \
  | grep -v "__pycache__" | grep -v "test" | grep -v ".venv"

# SQL injection (raw string formatting)
grep -rn "f\".*SELECT\|f\".*INSERT\|f\".*UPDATE\|f\".*DELETE\|%.*SELECT" --include="*.py" . \
  | grep -v "__pycache__" | grep -v "test"
```

## Manual Review Checklist

### Authentication & Authorization
- All API endpoints require auth (except /health)
- JWT: signature, expiry, issuer, audience validated
- JWT secret from env/secrets manager (never hardcoded)
- Role checks on every operation (not just at route level)
- No privilege escalation paths
- Token never appears in log output

### Input Validation
- All user input validated via Pydantic strict types
- File uploads: type checked, size limited, filename sanitized
- No path traversal (`../../etc/passwd`)
- Control IDs and tenant IDs sanitized

### Data Protection
- Tenant isolation: no query can access another tenant's data
- PII not stored in logs
- Secrets not in Docker image layers
- Database uses parameterized queries (never string formatting)

### Container Security
- Dockerfile: non-root user (`USER 65534`)
- No `--privileged` flag
- Pinned base image versions (not `:latest`)
- Sandbox: network=none, no host filesystem access

### LLM-Specific Security
- System prompts separated from user input (prompt injection defense)
- Tool call results validated before action
- LLM-generated code only runs in sandbox
- No PII in prompts unless necessary
- LLM responses not rendered as raw HTML
- Rate limiting on LLM calls

### Sandbox Security (critical path)
- Runtime container: `--network=none`
- Runtime container: `--read-only` filesystem
- Runtime container: memory limit enforced
- Import blocklist: no os, subprocess, socket, requests
- AST analysis before execution
- SIGKILL on timeout (no grace period)

## Severity Classification

| Severity | Criteria | Action |
|----------|----------|--------|
| Critical | RCE, auth bypass, data breach | Block deploy. Fix immediately. |
| High | SQL injection, privilege escalation, secrets exposed | Block deploy. Fix before merge. |
| Medium | Missing validation, permissive CORS, weak crypto | Fix within sprint. |
| Low | Best-practice improvements | Fix when convenient. |

## Report Format

```
## Security Review: {service-name}

**Date:** {date}
**Scope:** {files changed / full service}

### Findings

#### [{SEVERITY}] {Title}
- **Location:** {file}:{line}
- **Issue:** {description}
- **Impact:** {what could happen}
- **Fix:** {how to fix}

### Summary
- Critical: {n} | High: {n} | Medium: {n} | Low: {n}
- **Deploy gate:** PASS / BLOCKED ({reason})
```

## Playwright Security Testing

When Playwright MCP is available, use it to validate security controls in a real browser:
- Attempt accessing protected endpoints without auth token
- Test CORS by making cross-origin requests
- Verify security headers (X-Frame-Options, CSP, etc.)
- Test rate limiting by rapid-firing requests
- Verify JWT expiry behavior in live session
