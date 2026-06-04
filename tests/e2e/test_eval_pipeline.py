"""
E2E tests for agent-eval service.

Tests the 3-layer compliance evaluation pipeline:
- Rules layer (deterministic checks)
- LLM judgment layer
- Scoring layer
- Evidence caching
- Budget exhaustion degradation
"""

import asyncio
import time

import httpx
import pytest
import pytest_asyncio

from .conftest import auth_headers, SERVICE_URLS

pytestmark = [pytest.mark.e2e, pytest.mark.asyncio]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

EVAL_URL = SERVICE_URLS["agent_eval"]
S2S_HEADERS = {
    "X-Service-Id": "test-harness",
    "X-Service-Key": "test-harness-key-dev",
    "Content-Type": "application/json",
}


async def poll_eval_status(
    client: httpx.AsyncClient,
    eval_id: str,
    timeout: float = 30.0,
    poll_interval: float = 1.0,
) -> dict:
    """Poll evaluation status until complete or timeout."""
    start = time.time()
    while time.time() - start < timeout:
        resp = await client.get(
            f"/api/v1/evaluations/{eval_id}/status",
            headers=S2S_HEADERS,
        )
        assert resp.status_code == 200, f"Status check failed: {resp.status_code} {resp.text}"
        data = resp.json()
        if data.get("status") in ("completed", "failed", "partial"):
            return data
        await asyncio.sleep(poll_interval)

    pytest.fail(f"Evaluation {eval_id} did not complete within {timeout}s")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.timeout(30)
async def test_evaluate_compliant_control(eval_client, seed_data):
    """
    POST /evaluate for CC8.1 (Acme Corp) should result in 'compliant'.

    CC8.1 has complete monitoring evidence (alert_summary, incident_log, uptime_report).
    """
    payload = {
        "tenant_id": "tenant-acme-corp",
        "framework": "SOC2",
        "control_id": "CC8.1",
        "evidence_prefix": "acme-corp/CC8.1/",
        "trace_id": "e2e-test-compliant-001",
    }

    resp = await eval_client.post(
        "/api/v1/evaluations",
        headers=S2S_HEADERS,
        json=payload,
    )
    assert resp.status_code in (200, 201, 202), f"POST /evaluations failed: {resp.status_code} {resp.text}"
    data = resp.json()
    eval_id = data["evaluation_id"]

    # Poll until complete
    result = await poll_eval_status(eval_client, eval_id, timeout=30.0)

    assert result["status"] == "completed"
    assert result["result"]["compliance_status"] == "compliant"
    assert result["result"]["score"] >= 0.90
    assert "findings" in result["result"]


@pytest.mark.timeout(30)
async def test_evaluate_with_findings(eval_client, seed_data):
    """
    POST /evaluate for CC6.1 (Acme Corp) should result in 'partially_compliant'.

    CC6.1 evidence has a terminated employee still in access list + MFA gap.
    """
    payload = {
        "tenant_id": "tenant-acme-corp",
        "framework": "SOC2",
        "control_id": "CC6.1",
        "evidence_prefix": "acme-corp/CC6.1/",
        "trace_id": "e2e-test-partial-001",
    }

    resp = await eval_client.post(
        "/api/v1/evaluations",
        headers=S2S_HEADERS,
        json=payload,
    )
    assert resp.status_code in (200, 201, 202)
    data = resp.json()
    eval_id = data["evaluation_id"]

    result = await poll_eval_status(eval_client, eval_id, timeout=30.0)

    assert result["status"] == "completed"
    assert result["result"]["compliance_status"] == "partially_compliant"
    assert result["result"]["score"] < 0.90

    # Verify specific findings about terminated employee and MFA
    findings = result["result"]["findings"]
    assert len(findings) > 0
    finding_texts = " ".join(f.get("description", "") + f.get("detail", "") for f in findings).lower()
    assert "terminated" in finding_texts or "access" in finding_texts
    assert "mfa" in finding_texts or "multi-factor" in finding_texts


@pytest.mark.timeout(30)
async def test_evaluate_insufficient(eval_client, seed_data):
    """
    POST /evaluate for CC6.1 (Globex Inc) should result in 'insufficient_evidence'.

    Globex only has 2 CSV files (access_review_log + active_access_list) with minimal data.
    """
    payload = {
        "tenant_id": "tenant-globex-inc",
        "framework": "SOC2",
        "control_id": "CC6.1",
        "evidence_prefix": "globex-inc/CC6.1/",
        "trace_id": "e2e-test-insufficient-001",
    }

    resp = await eval_client.post(
        "/api/v1/evaluations",
        headers=S2S_HEADERS,
        json=payload,
    )
    assert resp.status_code in (200, 201, 202)
    data = resp.json()
    eval_id = data["evaluation_id"]

    result = await poll_eval_status(eval_client, eval_id, timeout=30.0)

    assert result["status"] == "completed"
    assert result["result"]["compliance_status"] == "insufficient_evidence"


@pytest.mark.timeout(30)
async def test_evaluate_cache_hit(eval_client, seed_data):
    """
    POST /evaluate twice for same control with same evidence.

    The second evaluation should return much faster (cached result based on evidence hash).
    """
    payload = {
        "tenant_id": "tenant-acme-corp",
        "framework": "SOC2",
        "control_id": "CC8.1",
        "evidence_prefix": "acme-corp/CC8.1/",
        "trace_id": "e2e-test-cache-001",
    }

    # First evaluation (populates cache)
    resp1 = await eval_client.post(
        "/api/v1/evaluations",
        headers=S2S_HEADERS,
        json=payload,
    )
    assert resp1.status_code in (200, 201, 202)
    eval_id_1 = resp1.json()["evaluation_id"]
    result1 = await poll_eval_status(eval_client, eval_id_1, timeout=30.0)
    assert result1["status"] == "completed"

    # Second evaluation (should hit cache)
    start_time = time.time()
    payload["trace_id"] = "e2e-test-cache-002"
    resp2 = await eval_client.post(
        "/api/v1/evaluations",
        headers=S2S_HEADERS,
        json=payload,
    )
    assert resp2.status_code in (200, 201, 202)
    eval_id_2 = resp2.json()["evaluation_id"]
    result2 = await poll_eval_status(eval_client, eval_id_2, timeout=10.0)
    elapsed = time.time() - start_time

    assert result2["status"] == "completed"
    # Cache hit should be significantly faster (under 3s vs typical 10-20s for full eval)
    assert elapsed < 5.0, f"Cache hit took {elapsed:.1f}s, expected <5s"
    # Results should match
    assert result2["result"]["compliance_status"] == result1["result"]["compliance_status"]
    assert result2["result"]["score"] == result1["result"]["score"]
    # Response should indicate it was cached
    assert result2.get("cached", False) or result2["result"].get("cached", False)


@pytest.mark.timeout(30)
async def test_rules_only_on_budget_exhaustion(eval_client, seed_data):
    """
    POST /evaluate for tenant-initech (budget exhausted) should return partial result.

    When LLM budget is exhausted, the system falls back to rules-only evaluation
    (Layer 1 only — no LLM judgment layer).
    """
    payload = {
        "tenant_id": "tenant-initech",
        "framework": "SOC2",
        "control_id": "CC6.1",
        "evidence_prefix": "acme-corp/CC6.1/",  # Use acme evidence but initech budget
        "trace_id": "e2e-test-budget-001",
    }

    resp = await eval_client.post(
        "/api/v1/evaluations",
        headers=S2S_HEADERS,
        json=payload,
    )
    assert resp.status_code in (200, 201, 202)
    data = resp.json()
    eval_id = data["evaluation_id"]

    result = await poll_eval_status(eval_client, eval_id, timeout=30.0)

    # Should complete but as partial (rules-only)
    assert result["status"] in ("completed", "partial")
    evaluation = result["result"]

    # Should indicate degraded/rules-only mode
    assert evaluation.get("mode") in ("rules_only", "degraded", "partial") or \
        evaluation.get("layers_executed", []) == ["rules"]

    # Rules layer still produces some findings even without LLM
    assert "score" in evaluation or "rule_results" in evaluation
