# Skill: Security Review

## Purpose
Review code and configuration for security vulnerabilities before deploy. Check for OWASP Top 10, secrets exposure, container security, dependency vulnerabilities, and compliance-specific risks.

## Tech Stack
- Python (check for injection, unsafe deserialization, path traversal)
- FastAPI (check auth, CORS, input validation)
- Docker (check image security, privilege escalation, secrets in layers)
- PostgreSQL (check SQL injection, connection security)
- JWT auth (check token validation, expiry, algorithm)

## When to use
- Before any deploy
- After code changes to auth, permissions, data handling, or API endpoints
- User says "security review", "check for vulnerabilities", "is this safe"
- When adding new dependencies
- When modifying Docker configuration

## Instructions

### Automated checks (run these first)

```bash
# 1. Check for hardcoded secrets
grep -rn "password\|secret\|api_key\|token" --include="*.py" --include="*.yaml" --include="*.yml" --include="*.env" . | grep -v "__pycache__" | grep -v ".git/" | grep -v "test"

# 2. Check .env not committed
git status | grep ".env"

# 3. Dependency vulnerability scan
pip-audit -r requirements.txt 2>/dev/null || echo "pip-audit not installed"

# 4. Dockerfile security
# Check for: running as root, latest tags, secrets in build args
grep -n "USER root\|FROM.*:latest\|ARG.*SECRET\|ARG.*PASSWORD\|ARG.*KEY" */Dockerfile

# 5. Check for unsafe Python patterns
grep -rn "eval(\|exec(\|pickle.loads\|yaml.load(\|subprocess.call(\|os.system(" --include="*.py" . | grep -v "__pycache__" | grep -v "test" | grep -v ".venv"

# 6. Check for SQL injection (raw string formatting in queries)
grep -rn "f\".*SELECT\|f\".*INSERT\|f\".*UPDATE\|f\".*DELETE\|%.*SELECT" --include="*.py" . | grep -v "__pycache__" | grep -v "test"
```

### Manual review checklist

#### Authentication & Authorization
- [ ] All API endpoints require authentication (no public endpoints except /health)
- [ ] JWT validation checks: signature, expiry, issuer, audience
- [ ] JWT secret is not hardcoded (loaded from env/secrets manager)
- [ ] Role checks on every MCP tool call (not just at tool_list level)
- [ ] No privilege escalation paths (contributor can't call admin tools)
- [ ] Token not logged in any log output

#### Input Validation
- [ ] All user input validated/sanitized before use
- [ ] File uploads: type checked, size limited, filename sanitized
- [ ] API parameters: use Pydantic models with strict types
- [ ] No path traversal in file/key operations (e.g., `../../etc/passwd`)
- [ ] Control IDs, tenant IDs sanitized (no SQL injection via framework/control params)

#### Data Protection
- [ ] Tenant isolation: no query can access another tenant's data
- [ ] PII not stored in logs (trace_id yes, email/name in logs: no)
- [ ] Secrets not in Docker image layers (use runtime env, not build args)
- [ ] Database connections use parameterized queries (never string formatting)
- [ ] Sensitive data encrypted at rest (PostgreSQL with encryption, MinIO with encryption)

#### Container Security
- [ ] Dockerfile: non-root user (`USER 65534` or named user)
- [ ] Dockerfile: no `--privileged` flag
- [ ] Dockerfile: pinned base image versions (not `:latest`)
- [ ] Docker Compose: no `privileged: true` except sandbox (needs Docker socket)
- [ ] Sandbox: network=none enforced, no host filesystem access
- [ ] No secrets in docker-compose.yml (use .env or Docker secrets)

#### Dependency Security
- [ ] All dependencies pinned to specific versions (not `>=` or `*`)
- [ ] No known CVEs in dependencies (check with pip-audit or safety)
- [ ] Minimal dependencies (no unused packages)
- [ ] No dependencies that phone home or collect telemetry without consent

#### LLM-Specific Security
- [ ] Prompt injection defense: system prompts clearly separated from user input
- [ ] Tool call results not blindly trusted (validate before action)
- [ ] LLM-generated code only runs in sandbox (never in agent process)
- [ ] No PII in LLM prompts unless necessary for the task
- [ ] LLM responses not rendered as HTML (XSS via model output)
- [ ] Rate limiting on LLM calls (prevent abuse/cost explosion)

#### Sandbox Security (critical)
- [ ] Runtime container: `--network=none` enforced
- [ ] Runtime container: `--read-only` filesystem
- [ ] Runtime container: memory limit enforced
- [ ] Runtime container: no access to Docker socket
- [ ] Import blocklist enforced (no os, subprocess, socket, requests)
- [ ] AST analysis of code before execution (catch `__import__` tricks)
- [ ] Output size limited (prevent stdout bomb)
- [ ] Timeout kill is SIGKILL (no grace period for malicious code)

#### API Security
- [ ] CORS restricted (not `*` in production)
- [ ] Rate limiting per tenant
- [ ] Request size limits
- [ ] No sensitive data in URL query parameters (use POST body)
- [ ] HTTPS enforced (TLS termination at gateway)
- [ ] Security headers: X-Content-Type-Options, X-Frame-Options, CSP

### Severity classification

| Severity | Criteria | Action |
|----------|----------|--------|
| Critical | RCE, auth bypass, data breach path | Block deploy. Fix immediately. |
| High | SQL injection, privilege escalation, secrets exposed | Block deploy. Fix before merge. |
| Medium | Missing input validation, overly permissive CORS, weak crypto | Fix within sprint. |
| Low | Informational, best-practice improvements | Fix when convenient. |

### Report format

```markdown
## Security Review: {service-name}

**Date:** {date}
**Reviewer:** Claude Security Review
**Scope:** {files changed / full service}

### Findings

#### [CRITICAL/HIGH/MEDIUM/LOW] {Title}
- **Location:** {file}:{line}
- **Issue:** {description}
- **Impact:** {what could happen}
- **Fix:** {how to fix}
- **Code:**
  ```python
  # vulnerable code
  ```

### Summary
- Critical: {n}
- High: {n}
- Medium: {n}
- Low: {n}
- **Deploy gate:** {PASS / BLOCKED (reason)}
```

### NEVER do
- Never run code from untrusted sources to "test" security
- Never expose or log actual secrets, even in security reports
- Never disable security controls to make something work (fix properly)
- Never approve a deploy with Critical or High findings
