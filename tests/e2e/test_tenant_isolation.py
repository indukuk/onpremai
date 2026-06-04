"""
E2E tests for cross-tenant isolation.

Verifies that multi-tenant boundaries are enforced:
- Memory isolation (tenant A facts not visible to tenant B)
- Storage isolation (tenant A files not accessible via tenant B prefix)
- Eval isolation (tenant A evaluation does not leak tenant B data)
"""

import uuid

import pytest
import pytest_asyncio

from .conftest import SERVICE_URLS

pytestmark = [pytest.mark.e2e, pytest.mark.asyncio]

# ---------------------------------------------------------------------------
# Shared headers
# ---------------------------------------------------------------------------

S2S_HEADERS = {
    "X-Service-Id": "test-harness",
    "X-Service-Key": "test-harness-key-dev",
    "Content-Type": "application/json",
}


def s2s_with_tenant(tenant_id: str) -> dict[str, str]:
    """S2S headers with tenant context."""
    return {
        **S2S_HEADERS,
        "X-Tenant-Id": tenant_id,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.timeout(10)
async def test_memory_isolation(memory_client, seed_data):
    """
    Store a fact for tenant A, query as tenant B -- fact must NOT be returned.
    """
    tenant_a = "tenant-acme-corp"
    tenant_b = "tenant-globex-inc"
    unique_fact = f"e2e-isolation-test-{uuid.uuid4().hex[:8]}"

    # Store a fact for tenant A
    store_resp = await memory_client.post(
        "/api/v1/memory/remember",
        headers=s2s_with_tenant(tenant_a),
        json={
            "tenant_id": tenant_a,
            "namespace": "tenant_facts",
            "content": unique_fact,
            "metadata": {"source": "e2e-test", "control": "CC6.1"},
        },
    )
    assert store_resp.status_code in (200, 201), \
        f"Failed to store fact: {store_resp.status_code} {store_resp.text}"

    # Query as tenant A -- should find it
    recall_a = await memory_client.post(
        "/api/v1/memory/recall",
        headers=s2s_with_tenant(tenant_a),
        json={
            "tenant_id": tenant_a,
            "query": unique_fact,
            "top_k": 5,
        },
    )
    assert recall_a.status_code == 200
    results_a = recall_a.json().get("results", recall_a.json().get("facts", []))
    found_in_a = any(unique_fact in str(r) for r in results_a)
    assert found_in_a, "Fact not found when querying as tenant A (the owner)"

    # Query as tenant B -- must NOT find it
    recall_b = await memory_client.post(
        "/api/v1/memory/recall",
        headers=s2s_with_tenant(tenant_b),
        json={
            "tenant_id": tenant_b,
            "query": unique_fact,
            "top_k": 5,
        },
    )
    assert recall_b.status_code == 200
    results_b = recall_b.json().get("results", recall_b.json().get("facts", []))
    found_in_b = any(unique_fact in str(r) for r in results_b)
    assert not found_in_b, "ISOLATION VIOLATION: Tenant B can see Tenant A's fact!"


@pytest.mark.timeout(10)
async def test_storage_isolation(memory_client, seed_data):
    """
    Upload file for tenant A, try to access with tenant B prefix -- must be denied.

    Uses memory-service storage proxy (which enforces tenant prefix isolation).
    """
    tenant_a = "tenant-acme-corp"
    tenant_b = "tenant-globex-inc"

    # Try to access tenant A's evidence via tenant B context
    resp = await memory_client.get(
        "/api/v1/storage/evidence",
        headers=s2s_with_tenant(tenant_b),
        params={
            "tenant_id": tenant_b,
            "path": "acme-corp/CC8.1/alert_summary.csv",  # Tenant A's file
        },
    )

    # Should be denied -- either 403 (explicit denial) or 404 (path not found under B's prefix)
    assert resp.status_code in (403, 404, 400), \
        f"ISOLATION VIOLATION: Tenant B accessed Tenant A's file! Status: {resp.status_code}"


@pytest.mark.timeout(30)
async def test_eval_isolation(eval_client, seed_data):
    """
    Trigger eval for tenant A -- verify no data from tenant B appears in results.
    """
    import asyncio
    import time

    tenant_a = "tenant-acme-corp"
    tenant_b_markers = ["globex", "tenant-globex-inc", "diana torres", "robert kim"]

    payload = {
        "tenant_id": tenant_a,
        "framework": "SOC2",
        "control_id": "CC8.1",
        "evidence_prefix": "acme-corp/CC8.1/",
        "trace_id": "e2e-isolation-eval-001",
    }

    resp = await eval_client.post(
        "/api/v1/evaluations",
        headers=S2S_HEADERS,
        json=payload,
    )
    assert resp.status_code in (200, 201, 202)
    eval_id = resp.json()["evaluation_id"]

    # Poll for completion
    start = time.time()
    result = None
    while time.time() - start < 30.0:
        status_resp = await eval_client.get(
            f"/api/v1/evaluations/{eval_id}/status",
            headers=S2S_HEADERS,
        )
        assert status_resp.status_code == 200
        data = status_resp.json()
        if data.get("status") in ("completed", "failed", "partial"):
            result = data
            break
        await asyncio.sleep(1.0)

    assert result is not None, "Evaluation did not complete in time"
    assert result["status"] in ("completed", "partial")

    # Serialize entire result to string and check for tenant B markers
    result_text = str(result).lower()
    for marker in tenant_b_markers:
        assert marker not in result_text, \
            f"ISOLATION VIOLATION: Found tenant B marker '{marker}' in tenant A's eval result!"
