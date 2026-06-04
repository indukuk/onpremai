"""
E2E tests for graceful degradation.

Tests system behavior when services are unavailable:
- Memory service down: assistant returns degraded response (not crash)
- LLM gateway down: agent-eval falls back to rules-only
- Sandbox service down: eval continues without code execution

IMPORTANT: These tests stop and restart containers. They should run last
and may require docker socket access.
"""

import asyncio
import subprocess
import time

import httpx
import pytest
import pytest_asyncio

from .conftest import auth_headers, SERVICE_URLS

pytestmark = [pytest.mark.e2e, pytest.mark.asyncio]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

S2S_HEADERS = {
    "X-Service-Id": "test-harness",
    "X-Service-Key": "test-harness-key-dev",
    "Content-Type": "application/json",
}


def docker_stop(container_name: str):
    """Stop a docker container."""
    subprocess.run(
        ["docker", "stop", container_name],
        capture_output=True,
        timeout=30,
    )


def docker_start(container_name: str):
    """Start a docker container."""
    subprocess.run(
        ["docker", "start", container_name],
        capture_output=True,
        timeout=30,
    )


async def wait_for_health(url: str, timeout: float = 30.0):
    """Wait until a service health endpoint responds 200."""
    start = time.time()
    async with httpx.AsyncClient(timeout=3.0) as client:
        while time.time() - start < timeout:
            try:
                resp = await client.get(url)
                if resp.status_code == 200:
                    return
            except (httpx.ConnectError, httpx.TimeoutException):
                pass
            await asyncio.sleep(1.0)
    pytest.fail(f"Service at {url} did not become healthy within {timeout}s")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.timeout(30)
async def test_memory_down(assistant_client, seed_data):
    """
    Stop memory-service container -- assistant should return degraded response, not crash.

    The compliance-assistant should still respond (with reduced quality / empty context)
    rather than returning a 500 error.
    """
    container = "onpremai-memory-service"
    memory_health_url = f"{SERVICE_URLS['memory_service']}/health"

    try:
        # Stop memory service
        docker_stop(container)

        # Give services a moment to detect the failure
        await asyncio.sleep(2)

        # Send request to assistant -- should NOT crash
        headers = auth_headers("user-001")  # Sarah Chen, admin
        resp = await assistant_client.post(
            "/api/v1/chat",
            headers=headers,
            json={
                "session_id": "degraded-test-session",
                "message": "hello",
            },
            timeout=15.0,
        )

        # Should get a response (possibly degraded) but NOT a 500
        assert resp.status_code != 500, \
            f"Assistant crashed when memory is down: {resp.status_code} {resp.text}"
        # Accept 200 (degraded response) or 503 (service unavailable but graceful)
        assert resp.status_code in (200, 503), \
            f"Unexpected status when memory down: {resp.status_code}"

        if resp.status_code == 200:
            data = resp.json()
            content = data.get("content", data.get("message", ""))
            # Should still have some content (even if degraded)
            assert len(content) > 0

    finally:
        # Always restart memory service
        docker_start(container)
        await wait_for_health(memory_health_url, timeout=30.0)


@pytest.mark.timeout(30)
async def test_gateway_down(eval_client, seed_data):
    """
    Stop llm-gateway -- agent-eval should fall back to rules-only evaluation.

    Without LLM access, the eval pipeline skips Layer 2 (LLM judgment)
    and returns a partial result from Layer 1 (rules) only.
    """
    container = "onpremai-llm-gateway"
    gateway_health_url = f"{SERVICE_URLS['llm_gateway']}/health"

    try:
        # Stop gateway
        docker_stop(container)
        await asyncio.sleep(2)

        # Trigger an evaluation -- should fall back to rules-only
        payload = {
            "tenant_id": "tenant-acme-corp",
            "framework": "SOC2",
            "control_id": "CC8.1",
            "evidence_prefix": "acme-corp/CC8.1/",
            "trace_id": "e2e-degradation-gw-001",
        }

        resp = await eval_client.post(
            "/api/v1/evaluations",
            headers=S2S_HEADERS,
            json=payload,
            timeout=15.0,
        )

        # Should accept the request (evaluation is async)
        assert resp.status_code in (200, 201, 202, 503), \
            f"Eval crashed when gateway down: {resp.status_code} {resp.text}"

        if resp.status_code in (200, 201, 202):
            eval_id = resp.json()["evaluation_id"]

            # Poll for result
            start = time.time()
            while time.time() - start < 20.0:
                status_resp = await eval_client.get(
                    f"/api/v1/evaluations/{eval_id}/status",
                    headers=S2S_HEADERS,
                )
                if status_resp.status_code == 200:
                    data = status_resp.json()
                    if data.get("status") in ("completed", "partial", "failed"):
                        # Should be partial (rules-only) or indicate degraded
                        assert data["status"] in ("partial", "completed")
                        if "result" in data:
                            result = data["result"]
                            # Verify it ran in degraded mode
                            mode = result.get("mode", result.get("evaluation_mode", ""))
                            layers = result.get("layers_executed", [])
                            assert mode in ("rules_only", "degraded", "partial") or \
                                layers == ["rules"] or \
                                "rules" in str(result).lower()
                        break
                await asyncio.sleep(1.0)

    finally:
        # Always restart gateway
        docker_start(container)
        await wait_for_health(gateway_health_url, timeout=30.0)


@pytest.mark.timeout(30)
async def test_sandbox_down(eval_client, seed_data):
    """
    Stop sandbox-service -- eval should continue without code execution.

    Sandbox is used for data analysis (code generation + execution).
    When it is down, eval skips the sandbox node and continues with other layers.
    """
    container = "onpremai-sandbox-service"
    sandbox_health_url = f"{SERVICE_URLS['sandbox_service']}/health"

    try:
        # Stop sandbox
        docker_stop(container)
        await asyncio.sleep(2)

        # Trigger evaluation that would normally use sandbox for CSV analysis
        payload = {
            "tenant_id": "tenant-acme-corp",
            "framework": "SOC2",
            "control_id": "CC6.1",
            "evidence_prefix": "acme-corp/CC6.1/",
            "trace_id": "e2e-degradation-sandbox-001",
        }

        resp = await eval_client.post(
            "/api/v1/evaluations",
            headers=S2S_HEADERS,
            json=payload,
            timeout=15.0,
        )

        # Should accept the request
        assert resp.status_code in (200, 201, 202), \
            f"Eval crashed when sandbox down: {resp.status_code} {resp.text}"

        eval_id = resp.json()["evaluation_id"]

        # Poll for completion -- should complete (possibly with reduced quality)
        start = time.time()
        while time.time() - start < 25.0:
            status_resp = await eval_client.get(
                f"/api/v1/evaluations/{eval_id}/status",
                headers=S2S_HEADERS,
            )
            if status_resp.status_code == 200:
                data = status_resp.json()
                if data.get("status") in ("completed", "partial", "failed"):
                    # Should complete (sandbox failure is non-fatal)
                    assert data["status"] in ("completed", "partial"), \
                        f"Eval should not hard-fail when sandbox is down. Status: {data['status']}"
                    break
            await asyncio.sleep(1.0)
        else:
            pytest.fail("Evaluation did not complete within timeout (sandbox down)")

    finally:
        # Always restart sandbox
        docker_start(container)
        await wait_for_health(sandbox_health_url, timeout=30.0)
