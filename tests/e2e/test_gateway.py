"""
E2E tests for llm-gateway service.

Tests:
- Task-based routing to correct model tier
- Budget tracking per tenant
- Embedding endpoint
- Health check
"""

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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.timeout(10)
async def test_complete_routing(gateway_client, seed_data):
    """
    POST /v1/complete with task='evaluate_control' routes to correct model tier.

    The gateway resolves: task -> tier (mid for evaluate_control) -> model.
    """
    payload = {
        "messages": [
            {"role": "system", "content": "You are a compliance evaluator."},
            {"role": "user", "content": "Is this control compliant? Evidence: all checks pass."},
        ],
        "task": "evaluate_control",
        "tenant_id": "tenant-acme-corp",
        "trace_id": "e2e-gateway-routing-001",
        "max_tokens": 100,
        "temperature": 0.0,
    }

    resp = await gateway_client.post(
        "/v1/complete",
        headers=S2S_HEADERS,
        json=payload,
    )
    assert resp.status_code == 200, f"Complete failed: {resp.status_code} {resp.text}"
    data = resp.json()

    # Verify response structure
    assert "content" in data
    assert "model_used" in data
    assert "tier_used" in data
    assert "usage" in data
    assert "latency_ms" in data

    # evaluate_control should route to 'mid' tier by default
    assert data["tier_used"] in ("mid", "strong"), \
        f"Expected mid/strong tier for evaluate_control, got: {data['tier_used']}"

    # Usage should have token counts
    assert data["usage"]["input_tokens"] > 0
    assert data["usage"]["output_tokens"] > 0


@pytest.mark.timeout(10)
async def test_budget_tracking(gateway_client, seed_data):
    """
    Multiple completions for same tenant accumulate budget usage.

    After N calls, the budget used_usd should increase.
    """
    tenant_id = "tenant-acme-corp"

    # Get current budget state
    budget_resp = await gateway_client.get(
        f"/v1/budget/{tenant_id}",
        headers=S2S_HEADERS,
    )
    # Budget endpoint might be on admin port, but try agent port first
    if budget_resp.status_code == 404:
        pytest.skip("Budget endpoint not available on agent port")

    initial_budget = budget_resp.json()
    initial_used = initial_budget.get("used_usd", 0.0)

    # Make a completion request
    payload = {
        "messages": [
            {"role": "user", "content": "Hello, brief response please."},
        ],
        "task": "chat_response",
        "tenant_id": tenant_id,
        "trace_id": "e2e-gateway-budget-001",
        "max_tokens": 50,
        "temperature": 0.0,
    }

    resp = await gateway_client.post(
        "/v1/complete",
        headers=S2S_HEADERS,
        json=payload,
    )
    assert resp.status_code == 200

    # Check budget increased
    budget_resp2 = await gateway_client.get(
        f"/v1/budget/{tenant_id}",
        headers=S2S_HEADERS,
    )
    assert budget_resp2.status_code == 200
    updated_used = budget_resp2.json().get("used_usd", 0.0)

    assert updated_used > initial_used, \
        f"Budget did not increase: {initial_used} -> {updated_used}"


@pytest.mark.timeout(10)
async def test_embed(gateway_client, seed_data):
    """
    POST /v1/embed returns embeddings for input texts.
    """
    payload = {
        "texts": [
            "Access control policy requires MFA for all admin accounts.",
            "Monthly access reviews are performed and documented.",
        ],
    }

    resp = await gateway_client.post(
        "/v1/embed",
        headers=S2S_HEADERS,
        json=payload,
    )
    assert resp.status_code == 200, f"Embed failed: {resp.status_code} {resp.text}"
    data = resp.json()

    # Verify embeddings structure
    assert "embeddings" in data
    assert len(data["embeddings"]) == 2

    # Each embedding should be a list of floats
    for embedding in data["embeddings"]:
        assert isinstance(embedding, list)
        assert len(embedding) > 0
        assert all(isinstance(v, (int, float)) for v in embedding)

    # Verify model info
    assert "model_used" in data


@pytest.mark.timeout(10)
async def test_health(gateway_client):
    """
    GET /health returns ok status.
    """
    resp = await gateway_client.get("/health")
    assert resp.status_code == 200
    data = resp.json()

    assert data.get("status") in ("ok", "healthy", "up")
