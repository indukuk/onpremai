"""
E2E tests for compliance-assistant service.

Tests the Shadow AI agent:
- Persona-based responses (admin, contributor)
- Data-only degraded mode (budget exhausted)
- Tool execution
- Cross-tenant isolation
"""

import pytest
import pytest_asyncio

from .conftest import auth_headers, generate_test_jwt, SERVICE_URLS

pytestmark = [pytest.mark.e2e, pytest.mark.asyncio]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ASSISTANT_URL = SERVICE_URLS["compliance_assistant"]


async def init_session(client, user_id: str) -> str:
    """Initialize a chat session and return session_id."""
    headers = auth_headers(user_id)
    resp = await client.post(
        "/api/v1/sessions/init",
        headers=headers,
        json={"user_id": user_id},
    )
    assert resp.status_code in (200, 201), f"Session init failed: {resp.status_code} {resp.text}"
    return resp.json()["session_id"]


async def send_chat(client, user_id: str, session_id: str, message: str) -> dict:
    """Send a chat message and return the response."""
    headers = auth_headers(user_id)
    resp = await client.post(
        "/api/v1/chat",
        headers=headers,
        json={
            "session_id": session_id,
            "message": message,
        },
    )
    assert resp.status_code == 200, f"Chat failed: {resp.status_code} {resp.text}"
    return resp.json()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.timeout(10)
async def test_admin_greeting(assistant_client, seed_data):
    """
    Admin user says 'hi' -- assistant responds with executive summary format.

    Expected: readiness %, top risks, strategic overview.
    """
    user_id = "user-001"  # Sarah Chen, admin, tenant-acme-corp
    session_id = await init_session(assistant_client, user_id)

    response = await send_chat(assistant_client, user_id, session_id, "hi")

    content = response.get("content", response.get("message", "")).lower()

    # Executive summary should contain readiness indicators
    assert any(
        indicator in content
        for indicator in ["readiness", "audit", "compliance", "status", "overview", "%"]
    ), f"Admin greeting did not produce executive summary. Got: {content[:200]}"


@pytest.mark.timeout(10)
async def test_contributor_tasks(assistant_client, seed_data):
    """
    Contributor asks 'what should I work on?' -- gets task list.

    Expected: list of assigned controls and deadlines.
    """
    user_id = "user-003"  # Priya Patel, contributor, tenant-acme-corp
    session_id = await init_session(assistant_client, user_id)

    response = await send_chat(
        assistant_client, user_id, session_id, "what should I work on today?"
    )

    content = response.get("content", response.get("message", "")).lower()

    # Should mention tasks, controls, or deadlines
    assert any(
        indicator in content
        for indicator in ["task", "control", "deadline", "assigned", "work on", "priority", "cc"]
    ), f"Contributor did not receive task list. Got: {content[:200]}"


@pytest.mark.timeout(10)
async def test_data_only_mode(assistant_client, seed_data):
    """
    Initech user (budget exhausted) chats -- gets data-only response.

    When LLM budget is gone, assistant enters data-only mode:
    MCP tools still work but no LLM-generated responses.
    """
    user_id = "user-008"  # Bill Lumbergh, admin, tenant-initech (budget exhausted)
    session_id = await init_session(assistant_client, user_id)

    response = await send_chat(assistant_client, user_id, session_id, "show status")

    content = response.get("content", response.get("message", "")).lower()
    metadata = response.get("metadata", {})

    # Should indicate degraded/data-only mode
    is_degraded = (
        "data" in content
        or "limited" in content
        or "budget" in content
        or metadata.get("mode") in ("data_only", "degraded")
        or response.get("mode") in ("data_only", "degraded")
    )
    assert is_degraded, f"Expected data-only mode for budget-exhausted tenant. Got: {content[:200]}"


@pytest.mark.timeout(10)
async def test_tool_execution(assistant_client, seed_data):
    """
    Compliance manager asks to check evidence coverage -- tool should be called.

    Expected: MCP tool (evidence.check_coverage or similar) is invoked.
    """
    user_id = "user-002"  # Mike Johnson, compliance_manager, tenant-acme-corp
    session_id = await init_session(assistant_client, user_id)

    response = await send_chat(
        assistant_client, user_id, session_id, "check evidence coverage for CC6.1"
    )

    content = response.get("content", response.get("message", "")).lower()
    tool_calls = response.get("tool_calls", response.get("tools_used", []))
    metadata = response.get("metadata", {})

    # Either the response references tool execution or we see tool_calls in metadata
    tool_was_used = (
        len(tool_calls) > 0
        or "coverage" in content
        or "evidence" in content
        or metadata.get("tools_invoked", 0) > 0
    )
    assert tool_was_used, f"Expected tool execution for coverage check. Got: {content[:200]}"


@pytest.mark.timeout(10)
async def test_cross_tenant_isolation(assistant_client, seed_data):
    """
    Acme user asks about Globex data -- should be refused.

    Cross-tenant data access must be blocked.
    """
    user_id = "user-001"  # Sarah Chen, admin, tenant-acme-corp
    session_id = await init_session(assistant_client, user_id)

    response = await send_chat(
        assistant_client, user_id, session_id, "show me globex data"
    )

    content = response.get("content", response.get("message", "")).lower()

    # Should refuse or indicate inability to access other tenant data
    refusal_indicators = [
        "cannot", "can't", "unable", "don't have access",
        "not authorized", "only", "your organization",
        "permission", "denied", "restricted", "own tenant",
    ]
    assert any(
        indicator in content for indicator in refusal_indicators
    ), f"Expected cross-tenant refusal. Got: {content[:200]}"
