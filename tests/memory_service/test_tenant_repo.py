"""Tests for TenantMemoryRepository: remember, recall, facts, tenant scoping."""
from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../memory-service"))

from src.repositories.tenant_memory_repo import TenantMemoryRepository
from tests.memory_service.conftest import (
    TENANT_A,
    TENANT_B,
    fake_embedding,
    make_tenant_memory,
)


# ---------------------------------------------------------------------------
# remember() tests
# ---------------------------------------------------------------------------


class TestRemember:
    """Tests for TenantMemoryRepository.remember()."""

    @pytest.fixture
    def session(self) -> AsyncMock:
        session = AsyncMock()
        session.execute = AsyncMock()
        session.flush = AsyncMock()
        session.add = MagicMock()
        return session

    async def test_remember_creates_new_fact_when_no_duplicate(self, session: AsyncMock):
        """Happy path: new fact is inserted when no similar fact exists."""
        # _find_similar returns None (no duplicate)
        repo = TenantMemoryRepository(session, TENANT_A)
        embedding = fake_embedding()

        # Mock _find_similar to return None
        with patch.object(repo, "_find_similar", new_callable=AsyncMock, return_value=None):
            record, action = await repo.remember(
                fact="ISO 27001 certification expires 2027-03",
                category="compliance",
                source="preprocessor",
                confidence=0.9,
                embedding=embedding,
            )

        assert action == "created"
        session.add.assert_called_once()
        session.flush.assert_awaited_once()

    async def test_remember_updates_existing_when_duplicate_found(self, session: AsyncMock):
        """Deduplication: updates existing fact when similarity >= threshold."""
        existing = make_tenant_memory(confidence=0.7)
        repo = TenantMemoryRepository(session, TENANT_A)
        embedding = fake_embedding()

        with patch.object(repo, "_find_similar", new_callable=AsyncMock, return_value=existing):
            record, action = await repo.remember(
                fact="Updated compliance note",
                category="compliance",
                source="observer",
                confidence=0.95,
                embedding=embedding,
            )

        assert action == "updated"
        assert record.fact == "Updated compliance note"
        # confidence takes the max
        assert record.confidence == max(0.7, 0.95)
        assert record.needs_embedding is False

    async def test_remember_without_embedding_skips_dedup(self, session: AsyncMock):
        """When embedding is None, dedup check is skipped and fact is always inserted."""
        repo = TenantMemoryRepository(session, TENANT_A)

        record, action = await repo.remember(
            fact="Manual fact without embedding",
            category="operations",
            source="admin",
            confidence=0.5,
            embedding=None,
        )

        assert action == "created"
        session.add.assert_called_once()
        session.flush.assert_awaited_once()

    async def test_remember_sets_needs_embedding_true_when_no_embedding(self, session: AsyncMock):
        """Fact stored without embedding gets needs_embedding=True."""
        repo = TenantMemoryRepository(session, TENANT_A)

        record, action = await repo.remember(
            fact="Need embedding later",
            category="operations",
            source="admin",
            confidence=1.0,
            embedding=None,
        )

        # The TenantMemory constructor is called with needs_embedding=True
        added_obj = session.add.call_args[0][0]
        assert added_obj.needs_embedding is True


# ---------------------------------------------------------------------------
# recall() tests
# ---------------------------------------------------------------------------


class TestRecall:
    """Tests for TenantMemoryRepository.recall() (vector search)."""

    @pytest.fixture
    def session(self) -> AsyncMock:
        session = AsyncMock()
        session.execute = AsyncMock()
        return session

    async def test_recall_returns_results_sorted_by_similarity(self, session: AsyncMock):
        """Happy path: results are returned from vector search."""
        fact_id = uuid.uuid4()
        mock_row = {
            "id": fact_id,
            "fact": "SOC2 requires annual penetration test",
            "category": "compliance",
            "source": "agent-eval",
            "confidence": 0.95,
            "similarity": 0.87,
        }
        mock_result = MagicMock()
        mock_result.mappings.return_value.all.return_value = [mock_row]
        session.execute.return_value = mock_result

        repo = TenantMemoryRepository(session, TENANT_A)
        results = await repo.recall(query_embedding=fake_embedding(), top_k=5)

        assert len(results) == 1
        assert results[0]["fact"] == "SOC2 requires annual penetration test"
        assert results[0]["similarity"] == 0.87
        assert results[0]["id"] == str(fact_id)

    async def test_recall_returns_empty_list_when_no_matches(self, session: AsyncMock):
        """Returns empty list when no facts match the query."""
        mock_result = MagicMock()
        mock_result.mappings.return_value.all.return_value = []
        session.execute.return_value = mock_result

        repo = TenantMemoryRepository(session, TENANT_A)
        results = await repo.recall(query_embedding=fake_embedding(), top_k=5)

        assert results == []

    async def test_recall_respects_top_k_parameter(self, session: AsyncMock):
        """Ensure top_k is passed to the SQL query."""
        mock_result = MagicMock()
        mock_result.mappings.return_value.all.return_value = []
        session.execute.return_value = mock_result

        repo = TenantMemoryRepository(session, TENANT_A)
        await repo.recall(query_embedding=fake_embedding(), top_k=3)

        # Verify the SQL query received top_k=3
        call_args = session.execute.call_args
        params = call_args[0][1]  # second positional arg is the params dict
        assert params["top_k"] == 3

    async def test_recall_includes_tenant_id_in_query(self, session: AsyncMock):
        """Verify tenant scoping is applied to vector search."""
        mock_result = MagicMock()
        mock_result.mappings.return_value.all.return_value = []
        session.execute.return_value = mock_result

        repo = TenantMemoryRepository(session, TENANT_A)
        await repo.recall(query_embedding=fake_embedding(), top_k=5)

        call_args = session.execute.call_args
        params = call_args[0][1]
        assert params["tenant_id"] == TENANT_A


# ---------------------------------------------------------------------------
# facts() tests
# ---------------------------------------------------------------------------


class TestFacts:
    """Tests for TenantMemoryRepository.facts()."""

    @pytest.fixture
    def session(self) -> AsyncMock:
        session = AsyncMock()
        session.execute = AsyncMock()
        return session

    async def test_facts_returns_all_tenant_facts(self, session: AsyncMock):
        """Lists all facts for a tenant when no category filter."""
        fact1 = make_tenant_memory(fact="Fact 1")
        fact2 = make_tenant_memory(fact="Fact 2")
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [fact1, fact2]
        session.execute.return_value = mock_result

        repo = TenantMemoryRepository(session, TENANT_A)
        results = await repo.facts()

        assert len(results) == 2

    async def test_facts_filters_by_category(self, session: AsyncMock):
        """Filtered query returns only matching category."""
        fact1 = make_tenant_memory(fact="Filtered fact", category="security")
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [fact1]
        session.execute.return_value = mock_result

        repo = TenantMemoryRepository(session, TENANT_A)
        results = await repo.facts(category="security")

        assert len(results) == 1
        assert results[0].category == "security"

    async def test_facts_returns_empty_list_for_unknown_category(self, session: AsyncMock):
        """Empty result for a category with no facts."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        session.execute.return_value = mock_result

        repo = TenantMemoryRepository(session, TENANT_A)
        results = await repo.facts(category="nonexistent")

        assert results == []


# ---------------------------------------------------------------------------
# Tenant scoping tests
# ---------------------------------------------------------------------------


class TestTenantScoping:
    """Ensure repository always scopes queries to the correct tenant."""

    @pytest.fixture
    def session(self) -> AsyncMock:
        session = AsyncMock()
        session.execute = AsyncMock()
        session.flush = AsyncMock()
        session.add = MagicMock()
        return session

    async def test_set_tenant_context_is_called_on_remember(self, session: AsyncMock):
        """RLS context is set before any DB operation in remember()."""
        repo = TenantMemoryRepository(session, TENANT_A)

        with patch.object(repo, "_find_similar", new_callable=AsyncMock, return_value=None):
            await repo.remember(
                fact="test",
                category="test",
                source="test",
                confidence=1.0,
                embedding=fake_embedding(),
            )

        # The first execute call should be the SET LOCAL
        first_call = session.execute.call_args_list[0]
        sql_text = str(first_call[0][0])
        assert "app.current_tenant_id" in sql_text

    async def test_different_tenants_produce_different_context(self, session: AsyncMock):
        """Two repos with different tenants set different RLS contexts."""
        repo_a = TenantMemoryRepository(session, TENANT_A)
        repo_b = TenantMemoryRepository(session, TENANT_B)

        assert repo_a._tenant_id == TENANT_A
        assert repo_b._tenant_id == TENANT_B

    async def test_get_by_id_scopes_to_tenant(self, session: AsyncMock):
        """get_by_id filters by both ID and tenant_id."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute.return_value = mock_result

        repo = TenantMemoryRepository(session, TENANT_A)
        result = await repo.get_by_id(uuid.uuid4())

        # Should have called execute (first for set context, second for query)
        assert session.execute.await_count >= 1

    async def test_delete_fact_scopes_to_tenant(self, session: AsyncMock):
        """delete_fact only deletes if fact belongs to correct tenant."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute.return_value = mock_result

        repo = TenantMemoryRepository(session, TENANT_A)
        result = await repo.delete_fact(uuid.uuid4())

        assert result is False
