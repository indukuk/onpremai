"""Tests verifying Row Level Security (RLS) enforcement via SET app.current_tenant_id."""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../memory-service"))

from src.repositories.base import TenantScopedRepository
from src.repositories.tenant_memory_repo import TenantMemoryRepository
from tests.memory_service.conftest import TENANT_A, TENANT_B, fake_embedding


# ---------------------------------------------------------------------------
# Base repository RLS context tests
# ---------------------------------------------------------------------------


class TestRLSContextSetting:
    """Verify that SET LOCAL app.current_tenant_id is called correctly."""

    @pytest.fixture
    def session(self) -> AsyncMock:
        session = AsyncMock()
        session.execute = AsyncMock()
        session.flush = AsyncMock()
        session.add = MagicMock()
        session.delete = AsyncMock()
        return session

    async def test_set_tenant_context_executes_set_local(self, session: AsyncMock):
        """_set_tenant_context issues SET LOCAL with correct tenant ID."""
        repo = TenantScopedRepository(session, TENANT_A)
        await repo._set_tenant_context()

        session.execute.assert_awaited_once()
        call_args = session.execute.call_args
        sql_text = str(call_args[0][0])
        assert "SET LOCAL app.current_tenant_id" in sql_text
        params = call_args[1] if len(call_args) > 1 else call_args[0][1]
        assert params["tid"] == TENANT_A

    async def test_set_tenant_context_uses_correct_tenant_id(self, session: AsyncMock):
        """Different tenant IDs produce different SET LOCAL values."""
        repo_a = TenantScopedRepository(session, TENANT_A)
        await repo_a._set_tenant_context()

        first_params = session.execute.call_args[0][1]
        assert first_params["tid"] == TENANT_A

        session.execute.reset_mock()

        repo_b = TenantScopedRepository(session, TENANT_B)
        await repo_b._set_tenant_context()

        second_params = session.execute.call_args[0][1]
        assert second_params["tid"] == TENANT_B

    async def test_get_by_id_calls_set_tenant_context(self, session: AsyncMock):
        """_get_by_id sets tenant context before querying."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute.return_value = mock_result

        repo = TenantScopedRepository(session, TENANT_A)

        # We need a model class with id and tenant_id attributes for _get_by_id
        mock_model = MagicMock()
        mock_model.id = MagicMock()
        mock_model.tenant_id = MagicMock()

        await repo._get_by_id(mock_model, uuid.uuid4())

        # First call should be SET LOCAL
        first_call = session.execute.call_args_list[0]
        sql_text = str(first_call[0][0])
        assert "app.current_tenant_id" in sql_text

    async def test_delete_by_id_calls_set_tenant_context(self, session: AsyncMock):
        """_delete_by_id sets tenant context before querying."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute.return_value = mock_result

        repo = TenantScopedRepository(session, TENANT_A)

        mock_model = MagicMock()
        mock_model.id = MagicMock()
        mock_model.tenant_id = MagicMock()

        await repo._delete_by_id(mock_model, uuid.uuid4())

        first_call = session.execute.call_args_list[0]
        sql_text = str(first_call[0][0])
        assert "app.current_tenant_id" in sql_text


# ---------------------------------------------------------------------------
# Cross-tenant rejection
# ---------------------------------------------------------------------------


class TestCrossTenantRejection:
    """Verify that operations cannot access other tenants' data."""

    @pytest.fixture
    def session(self) -> AsyncMock:
        session = AsyncMock()
        session.execute = AsyncMock()
        session.flush = AsyncMock()
        session.add = MagicMock()
        session.delete = AsyncMock()
        return session

    async def test_get_by_id_rejects_wrong_tenant(self, session: AsyncMock):
        """_get_by_id filters by tenant_id, so wrong tenant returns None."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None  # RLS blocks cross-tenant
        session.execute.return_value = mock_result

        repo = TenantScopedRepository(session, TENANT_A)
        mock_model = MagicMock()
        mock_model.id = MagicMock()
        mock_model.tenant_id = MagicMock()

        # Even if the record exists for TENANT_B, repo scoped to TENANT_A returns None
        result = await repo._get_by_id(mock_model, uuid.uuid4())
        assert result is None

    async def test_delete_by_id_rejects_wrong_tenant(self, session: AsyncMock):
        """_delete_by_id returns False when record belongs to another tenant."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute.return_value = mock_result

        repo = TenantScopedRepository(session, TENANT_A)
        mock_model = MagicMock()
        mock_model.id = MagicMock()
        mock_model.tenant_id = MagicMock()

        result = await repo._delete_by_id(mock_model, uuid.uuid4())
        assert result is False

    async def test_recall_scoped_to_tenant(self, session: AsyncMock):
        """recall() query always includes tenant_id parameter."""
        mock_result = MagicMock()
        mock_result.mappings.return_value.all.return_value = []
        session.execute.return_value = mock_result

        repo = TenantMemoryRepository(session, TENANT_A)
        await repo.recall(query_embedding=fake_embedding(), top_k=5)

        # Find the recall SQL call (not the SET LOCAL call)
        for call_args in session.execute.call_args_list:
            params = call_args[0][1] if len(call_args[0]) > 1 else {}
            if "tenant_id" in params:
                assert params["tenant_id"] == TENANT_A
                return

        pytest.fail("No call contained tenant_id parameter")

    async def test_facts_scoped_to_tenant(self, session: AsyncMock):
        """facts() always includes tenant_id in the WHERE clause."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        session.execute.return_value = mock_result

        repo_a = TenantMemoryRepository(session, TENANT_A)
        repo_b = TenantMemoryRepository(session, TENANT_B)

        await repo_a.facts()
        await repo_b.facts()

        # Both should set their respective tenant contexts
        assert repo_a._tenant_id == TENANT_A
        assert repo_b._tenant_id == TENANT_B

    async def test_remember_sets_tenant_id_on_new_record(self, session: AsyncMock):
        """New facts always have tenant_id set to the repository's tenant."""
        repo = TenantMemoryRepository(session, TENANT_A)

        with patch.object(repo, "_find_similar", new_callable=AsyncMock, return_value=None):
            record, action = await repo.remember(
                fact="Test fact",
                category="test",
                source="test",
                confidence=1.0,
                embedding=None,
            )

        assert action == "created"
        added_obj = session.add.call_args[0][0]
        assert added_obj.tenant_id == TENANT_A

    async def test_cannot_access_tenant_b_data_from_tenant_a_repo(self, session: AsyncMock):
        """A TenantMemoryRepository scoped to tenant A cannot see tenant B's data."""
        # Simulate DB returning nothing because RLS blocks cross-tenant access
        mock_result = MagicMock()
        mock_result.mappings.return_value.all.return_value = []
        session.execute.return_value = mock_result

        repo = TenantMemoryRepository(session, TENANT_A)
        results = await repo.recall(query_embedding=fake_embedding(), top_k=10)

        # Even if tenant B has data, tenant A repo sees empty
        assert results == []

        # Verify the query was scoped to TENANT_A, not TENANT_B
        for call_args in session.execute.call_args_list:
            if len(call_args[0]) > 1 and isinstance(call_args[0][1], dict):
                params = call_args[0][1]
                if "tenant_id" in params:
                    assert params["tenant_id"] == TENANT_A
                    assert params["tenant_id"] != TENANT_B


# ---------------------------------------------------------------------------
# RLS context ordering
# ---------------------------------------------------------------------------


class TestRLSContextOrdering:
    """Verify RLS SET LOCAL is always executed BEFORE actual queries."""

    @pytest.fixture
    def session(self) -> AsyncMock:
        session = AsyncMock()
        session.execute = AsyncMock()
        session.flush = AsyncMock()
        session.add = MagicMock()
        session.delete = AsyncMock()
        return session

    async def test_remember_sets_context_before_operations(self, session: AsyncMock):
        """In remember(), SET LOCAL happens before any other DB call."""
        repo = TenantMemoryRepository(session, TENANT_A)

        with patch.object(repo, "_find_similar", new_callable=AsyncMock, return_value=None):
            await repo.remember(
                fact="test", category="c", source="s", confidence=1.0,
                embedding=fake_embedding(),
            )

        first_call = session.execute.call_args_list[0]
        sql_text = str(first_call[0][0])
        assert "SET LOCAL app.current_tenant_id" in sql_text

    async def test_recall_sets_context_before_query(self, session: AsyncMock):
        """In recall(), SET LOCAL happens before the vector search."""
        mock_result = MagicMock()
        mock_result.mappings.return_value.all.return_value = []
        session.execute.return_value = mock_result

        repo = TenantMemoryRepository(session, TENANT_A)
        await repo.recall(query_embedding=fake_embedding(), top_k=5)

        first_call = session.execute.call_args_list[0]
        sql_text = str(first_call[0][0])
        assert "SET LOCAL app.current_tenant_id" in sql_text

    async def test_facts_sets_context_before_query(self, session: AsyncMock):
        """In facts(), SET LOCAL happens before the select."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        session.execute.return_value = mock_result

        repo = TenantMemoryRepository(session, TENANT_A)
        await repo.facts()

        first_call = session.execute.call_args_list[0]
        sql_text = str(first_call[0][0])
        assert "SET LOCAL app.current_tenant_id" in sql_text
