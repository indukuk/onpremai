"""Unit tests for the UserStateManager class.

Covers:
- load returns None when memory is empty or unavailable
- load parses valid data into UserStateDoc
- save persists serialized doc via memory.user_state_put
- set_agent_name creates a new doc when none exists
- set_agent_name updates existing doc's agent_name
- merge_reflection updates last_session, appends pending_actions, deduplicates preferences
- merge_reflection caps preferences at max_preferences
- _compact evicts oldest pending_actions when doc exceeds max size
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.agent.user_state import PendingAction, UserStateDoc, UserStateManager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def state_manager(mock_memory_client: AsyncMock) -> UserStateManager:
    """UserStateManager with a mocked memory client."""
    return UserStateManager(memory=mock_memory_client)


@pytest.fixture
def valid_state_data() -> dict[str, Any]:
    """Valid serialized user state document."""
    return {
        "user_id": "user-001",
        "tenant_id": "tenant-001",
        "updated_at": "2026-06-28",
        "agent_name": "Atlas",
        "current_focus": "SOC2 audit prep",
        "last_session": {"date": "2026-06-28", "summary": "Reviewed controls."},
        "pending_actions": [
            {
                "action": "Follow up on CC6.1",
                "created": "2026-06-28",
                "source": "agent_committed",
                "due_date": None,
            }
        ],
        "preferences": ["Prefers concise answers"],
        "working_patterns": {
            "avg_session_length": 8,
            "typical_session_time": "",
            "skills_most_used": ["shared/status"],
        },
    }


@pytest.fixture
def existing_doc() -> UserStateDoc:
    """An existing UserStateDoc for merge tests."""
    return UserStateDoc(
        user_id="user-001",
        tenant_id="tenant-001",
        agent_name="Atlas",
        current_focus="SOC2 audit",
        pending_actions=[
            PendingAction(
                action="Fix control A1.2",
                created="2026-06-27",
                source="user_deferred",
            ),
        ],
        preferences=["Prefers concise answers", "Likes bullet points"],
    )


# ---------------------------------------------------------------------------
# Test: load returns None when memory is empty
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_returns_none_when_empty(
    state_manager: UserStateManager,
    mock_memory_client: AsyncMock,
) -> None:
    """When memory returns empty dict/None, load returns None."""
    mock_memory_client.user_state_get.return_value = {}

    result = await state_manager.load("user-001", "tenant-001")
    assert result is None


@pytest.mark.asyncio
async def test_load_returns_none_when_none(
    state_manager: UserStateManager,
    mock_memory_client: AsyncMock,
) -> None:
    """When memory returns None, load returns None."""
    mock_memory_client.user_state_get.return_value = None

    result = await state_manager.load("user-001", "tenant-001")
    assert result is None


# ---------------------------------------------------------------------------
# Test: load parses valid data
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_parses_valid_doc(
    state_manager: UserStateManager,
    mock_memory_client: AsyncMock,
    valid_state_data: dict[str, Any],
) -> None:
    """When memory returns valid data, load returns a UserStateDoc."""
    mock_memory_client.user_state_get.return_value = valid_state_data

    result = await state_manager.load("user-001", "tenant-001")

    assert result is not None
    assert result.user_id == "user-001"
    assert result.tenant_id == "tenant-001"
    assert result.agent_name == "Atlas"
    assert result.current_focus == "SOC2 audit prep"
    assert len(result.pending_actions) == 1
    assert result.pending_actions[0].action == "Follow up on CC6.1"
    assert result.preferences == ["Prefers concise answers"]


# ---------------------------------------------------------------------------
# Test: save persists doc
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_persists_doc(
    state_manager: UserStateManager,
    mock_memory_client: AsyncMock,
) -> None:
    """Verify memory.user_state_put is called with serialized data."""
    mock_memory_client.user_state_put.return_value = True

    doc = UserStateDoc(
        user_id="user-001",
        tenant_id="tenant-001",
        agent_name="Atlas",
    )

    result = await state_manager.save(doc)

    assert result is True
    mock_memory_client.user_state_put.assert_called_once()
    call_kwargs = mock_memory_client.user_state_put.call_args.kwargs
    assert call_kwargs["user_id"] == "user-001"
    assert call_kwargs["tenant_id"] == "tenant-001"
    assert "agent_name" in call_kwargs["data"]
    assert call_kwargs["data"]["agent_name"] == "Atlas"


# ---------------------------------------------------------------------------
# Test: set_agent_name creates new doc when none exists
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_agent_name_creates_doc(
    state_manager: UserStateManager,
    mock_memory_client: AsyncMock,
) -> None:
    """When no doc exists, set_agent_name creates a new one with the name."""
    mock_memory_client.user_state_get.return_value = None
    mock_memory_client.user_state_put.return_value = True

    result = await state_manager.set_agent_name("user-001", "tenant-001", "Scout")

    assert result is True
    call_kwargs = mock_memory_client.user_state_put.call_args.kwargs
    assert call_kwargs["data"]["agent_name"] == "Scout"
    assert call_kwargs["data"]["user_id"] == "user-001"


# ---------------------------------------------------------------------------
# Test: set_agent_name updates existing doc
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_agent_name_updates_existing(
    state_manager: UserStateManager,
    mock_memory_client: AsyncMock,
    valid_state_data: dict[str, Any],
) -> None:
    """When doc exists, set_agent_name updates only the agent_name field."""
    mock_memory_client.user_state_get.return_value = valid_state_data
    mock_memory_client.user_state_put.return_value = True

    result = await state_manager.set_agent_name("user-001", "tenant-001", "NewName")

    assert result is True
    call_kwargs = mock_memory_client.user_state_put.call_args.kwargs
    assert call_kwargs["data"]["agent_name"] == "NewName"
    # Existing data preserved
    assert len(call_kwargs["data"]["pending_actions"]) == 1


# ---------------------------------------------------------------------------
# Test: merge_reflection updates last_session
# ---------------------------------------------------------------------------


def test_merge_reflection_updates_last_session(
    state_manager: UserStateManager,
    existing_doc: UserStateDoc,
) -> None:
    """Reflection summary becomes last_session."""
    reflection = {
        "accomplished": ["Completed vendor review"],
        "pending": [],
        "commitments": [],
        "preferences": [],
    }

    updated = state_manager.merge_reflection(existing_doc, reflection)

    assert updated.last_session is not None
    assert "Completed vendor review" in updated.last_session.summary


# ---------------------------------------------------------------------------
# Test: merge_reflection appends pending_actions
# ---------------------------------------------------------------------------


def test_merge_reflection_appends_pending_actions(
    state_manager: UserStateManager,
    existing_doc: UserStateDoc,
) -> None:
    """Pending items added with correct source tags."""
    reflection = {
        "accomplished": [],
        "pending": ["Review ISO controls"],
        "commitments": ["Send report by Friday"],
        "preferences": [],
    }

    updated = state_manager.merge_reflection(existing_doc, reflection)

    # Original pending action + 1 user_deferred + 1 agent_committed
    user_deferred = [
        pa for pa in updated.pending_actions if pa.source == "user_deferred"
    ]
    agent_committed = [
        pa for pa in updated.pending_actions if pa.source == "agent_committed"
    ]

    assert any(pa.action == "Review ISO controls" for pa in user_deferred)
    assert any(pa.action == "Send report by Friday" for pa in agent_committed)


# ---------------------------------------------------------------------------
# Test: merge_reflection deduplicates preferences
# ---------------------------------------------------------------------------


def test_merge_reflection_deduplicates_preferences(
    state_manager: UserStateManager,
    existing_doc: UserStateDoc,
) -> None:
    """Same preference (case-insensitive) is not added twice."""
    reflection = {
        "accomplished": [],
        "pending": [],
        "commitments": [],
        "preferences": ["prefers concise answers", "Likes tables"],
    }

    updated = state_manager.merge_reflection(existing_doc, reflection)

    # "prefers concise answers" already exists (case-insensitive match)
    lowercase_prefs = [p.lower() for p in updated.preferences]
    assert lowercase_prefs.count("prefers concise answers") == 1
    assert "likes tables" in lowercase_prefs


# ---------------------------------------------------------------------------
# Test: merge_reflection caps preferences at max
# ---------------------------------------------------------------------------


def test_merge_reflection_caps_preferences(
    state_manager: UserStateManager,
) -> None:
    """Preferences list never exceeds settings.max_preferences (10)."""
    doc = UserStateDoc(
        user_id="user-001",
        tenant_id="tenant-001",
        preferences=[f"pref-{i}" for i in range(9)],
    )

    reflection = {
        "accomplished": [],
        "pending": [],
        "commitments": [],
        "preferences": ["new-pref-a", "new-pref-b", "new-pref-c"],
    }

    updated = state_manager.merge_reflection(doc, reflection)

    # max_preferences is 10 (from settings)
    assert len(updated.preferences) <= 10


# ---------------------------------------------------------------------------
# Test: _compact evicts oldest pending_actions
# ---------------------------------------------------------------------------


def test_compact_evicts_oldest_pending(
    state_manager: UserStateManager,
) -> None:
    """When doc too large, oldest pending_actions are removed first."""
    # Create a doc with many long pending actions to exceed max_chars
    large_actions = [
        PendingAction(
            action=f"Very long action description number {i} " * 10,
            created="2026-06-01",
            source="user_deferred",
        )
        for i in range(50)
    ]

    doc = UserStateDoc(
        user_id="user-001",
        tenant_id="tenant-001",
        pending_actions=large_actions,
    )

    # Patch settings to a very small max_chars to trigger compaction
    with patch("src.agent.user_state.settings") as mock_settings:
        mock_settings.user_state_max_chars = 500
        mock_settings.max_preferences = 10
        compacted = state_manager._compact(doc)

    # Some actions should have been evicted
    assert len(compacted.pending_actions) < 50
    # The oldest (index 0) should be removed first; remaining should be later ones
    if compacted.pending_actions:
        # The last item from original should still be there (or close to it)
        remaining_actions = [pa.action for pa in compacted.pending_actions]
        assert large_actions[-1].action in remaining_actions
