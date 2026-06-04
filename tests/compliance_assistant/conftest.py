"""Shared fixtures for compliance-assistant unit tests.

Provides mock clients, fake sessions, and user contexts used across test modules.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Path setup: ensure compliance-assistant/src and common are importable
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "compliance-assistant"))
sys.path.insert(0, str(_REPO_ROOT))

# Stub heavy external modules that may not be installed in test env
_STUBS: dict[str, Any] = {}
for mod_name in (
    "structlog",
    "httpx",
    "pydantic_settings",
):
    if mod_name not in sys.modules:
        _STUBS[mod_name] = MagicMock()
        sys.modules[mod_name] = _STUBS[mod_name]

# Stub common.config before importing anything that depends on it
if "common" not in sys.modules:
    sys.modules["common"] = MagicMock()
if "common.config" not in sys.modules:
    common_config_mock = MagicMock()

    class _FakeCommonSettings:
        pass

    common_config_mock.CommonSettings = _FakeCommonSettings
    sys.modules["common.config"] = common_config_mock
if "common.clients" not in sys.modules:
    sys.modules["common.clients"] = MagicMock()
if "common.errors" not in sys.modules:
    # We need real exception classes for tests
    class LLMCreditExhaustedError(Exception):
        def __init__(self, *args: Any, estimated_recovery: str | None = None, **kwargs: Any):
            super().__init__(*args, **kwargs)
            self.estimated_recovery = estimated_recovery

    class LLMUnavailableError(Exception):
        pass

    class LLMTimeoutError(Exception):
        pass

    errors_mod = MagicMock()
    errors_mod.LLMCreditExhaustedError = LLMCreditExhaustedError
    errors_mod.LLMUnavailableError = LLMUnavailableError
    errors_mod.LLMTimeoutError = LLMTimeoutError
    sys.modules["common.errors"] = errors_mod


# Now patch pydantic_settings to provide a real BaseSettings substitute
class _FakeBaseSettings:
    """Minimal BaseSettings stand-in for tests."""

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)

    def __init__(self, **kwargs: Any) -> None:
        for k, v in kwargs.items():
            setattr(self, k, v)
        # Apply class-level defaults
        for k, v in vars(type(self)).items():
            if not k.startswith("_") and not callable(v) and not hasattr(self, k):
                setattr(self, k, v)


if "pydantic_settings" in _STUBS:
    _STUBS["pydantic_settings"].BaseSettings = _FakeBaseSettings

# Patch common.config.CommonSettings so AssistantSettings can inherit
sys.modules["common.config"].CommonSettings = _FakeBaseSettings

# Now we can safely import project modules
from src.config import AssistantSettings  # noqa: E402
from src.models import (  # noqa: E402
    ChatResponse,
    PendingConfirmation,
    SessionState,
    ToolAction,
    UserContext,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_llm_client() -> AsyncMock:
    """Mock LLMClient that returns a simple LLMResponse by default."""
    client = AsyncMock()

    class FakeLLMResponse:
        content = "Hello! Here is your compliance status."
        model_used = "anthropic.claude-3-haiku"
        tier_used = "fast"
        tokens = 150
        latency = 0.3
        tool_calls: list[dict[str, Any]] = []

    client.complete.return_value = FakeLLMResponse()
    return client


@pytest.fixture
def mock_memory_client() -> AsyncMock:
    """Mock MemoryClient returning empty results."""
    client = AsyncMock()
    client.tenant_recall.return_value = []
    client.eval_store.return_value = None
    client.session_recall.return_value = []
    return client


@pytest.fixture
def mock_mcp_client() -> AsyncMock:
    """Mock MCPClient with default tool list and successful call results."""
    client = AsyncMock()
    client.list_tools.return_value = [
        {
            "name": "evidence.check_coverage",
            "description": "Check evidence coverage for a framework",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "framework_id": {"type": "string"},
                },
            },
        },
        {
            "name": "memory.task_list",
            "description": "List tasks for the current user",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "status": {"type": "string"},
                },
            },
        },
        {
            "name": "escalation.check_overdue",
            "description": "Check for overdue compliance items",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "framework_id": {"type": "string"},
                },
            },
        },
    ]
    client.call_tool.return_value = {
        "status": "success",
        "data": {"readiness": "85%", "controls_met": 42, "controls_total": 50},
    }
    client.close.return_value = None
    return client


@pytest.fixture
def mock_session_manager() -> AsyncMock:
    """Mock SessionManager."""
    manager = AsyncMock()
    manager.save.return_value = None
    manager.clear_pending_confirmation.return_value = None
    manager.set_pending_confirmation.return_value = None
    return manager


@pytest.fixture
def mock_context_builder() -> AsyncMock:
    """Mock ContextBuilder."""
    builder = AsyncMock()
    builder.build.return_value = "You are the compliance assistant."
    return builder


@pytest.fixture
def mock_skill_loader() -> AsyncMock:
    """Mock SkillLoader."""
    loader = AsyncMock()
    loader.load_for_role.return_value = [
        {"id": "shared/status", "triggers": ["status", "readiness"]},
        {"id": "cm/evaluate", "triggers": ["evaluate", "run eval"]},
    ]
    loader.get_skill_prompt.return_value = "Execute the evaluation skill."
    loader.get_skill_playbook.return_value = None
    return loader


@pytest.fixture
def mock_skill_matcher() -> MagicMock:
    """Mock SkillMatcher."""
    matcher = MagicMock()
    matcher.match.return_value = None
    return matcher


@pytest.fixture
def mock_playbook_engine() -> AsyncMock:
    """Mock PlaybookEngine."""
    engine = AsyncMock()
    engine.get_step_prompt.return_value = "Step 1: Gather evidence."
    engine.advance_step.return_value = None
    return engine


@pytest.fixture
def mock_confirmation_handler() -> AsyncMock:
    """Mock ConfirmationHandler."""
    handler = AsyncMock()
    handler.execute_confirmed.return_value = {
        "status": "success",
        "data": "Action completed.",
    }
    return handler


@pytest.fixture
def fake_user_admin() -> UserContext:
    """Admin user context."""
    return UserContext(
        tenant_id="tenant-001",
        user_id="user-admin-001",
        role="admin",
        email="admin@acme.com",
        name="Alice Admin",
    )


@pytest.fixture
def fake_user_contributor() -> UserContext:
    """Contributor user context."""
    return UserContext(
        tenant_id="tenant-001",
        user_id="user-contrib-001",
        role="contributor",
        email="bob@acme.com",
        name="Bob Builder",
    )


@pytest.fixture
def fake_user_auditor() -> UserContext:
    """Auditor user context."""
    return UserContext(
        tenant_id="tenant-001",
        user_id="user-auditor-001",
        role="auditor",
        email="carol@acme.com",
        name="Carol Auditor",
    )


@pytest.fixture
def fake_user_viewer() -> UserContext:
    """Viewer user context."""
    return UserContext(
        tenant_id="tenant-001",
        user_id="user-viewer-001",
        role="viewer",
        email="dave@acme.com",
        name="Dave Viewer",
    )


@pytest.fixture
def fake_user_compliance_manager() -> UserContext:
    """Compliance manager user context."""
    return UserContext(
        tenant_id="tenant-001",
        user_id="user-cm-001",
        role="compliance_manager",
        email="eve@acme.com",
        name="Eve Manager",
    )


@pytest.fixture
def fake_session() -> SessionState:
    """A fresh session in full mode."""
    return SessionState(
        session_id="session-test-001",
        tenant_id="tenant-001",
        user_id="user-admin-001",
        role="admin",
        persona="Executive Advisor",
        mode="full",
        conversation_history=[],
        tools_cache=[
            {
                "name": "evidence.check_coverage",
                "description": "Check evidence coverage",
                "inputSchema": {"type": "object", "properties": {}},
            },
        ],
    )


@pytest.fixture
def fake_session_data_only() -> SessionState:
    """A session already in data-only mode."""
    return SessionState(
        session_id="session-test-002",
        tenant_id="tenant-001",
        user_id="user-admin-001",
        role="admin",
        persona="Executive Advisor",
        mode="data_only",
        conversation_history=[],
        tools_cache=[],
    )
