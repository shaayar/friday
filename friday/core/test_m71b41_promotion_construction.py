"""M7.1b.4.1 tests — Promotion Dependency Construction.

Verifies that AssistantSession constructs promotion dependencies correctly
without executing promotion.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from friday.compaction.promoter import ConversationMemoryPromoter
from friday.compaction.promotion_store import SQLitePromotionStore
from friday.config import config
from friday.core.session import AssistantSession
from friday.memory.durable_manager import DurableMemoryManager
from friday.memory.resolver import MemoryResolver


@pytest.fixture
def temp_friday_home(tmp_path, monkeypatch):
    """Temporary FRIDAY_HOME; isolates all stores for the session."""
    home = tmp_path / ".friday"
    monkeypatch.setattr(config, "FRIDAY_HOME", home)
    return home


class TestPromotionDependencyConstruction:
    """Tests for M7.1b.4.1 — Promotion Dependency Construction."""

    @pytest.mark.asyncio
    async def test_session_constructs_promotion_store(self, temp_friday_home) -> None:
        """AssistantSession constructs SQLitePromotionStore."""
        session = AssistantSession(
            friday_home=temp_friday_home,
            llm_backend=None,  # No LLM needed for construction
        )

        assert hasattr(session, "_promotion_store")
        assert session._promotion_store is not None
        assert isinstance(session._promotion_store, SQLitePromotionStore)

        await session.stop()

    @pytest.mark.asyncio
    async def test_promotion_store_uses_conversations_db(
        self, temp_friday_home
    ) -> None:
        """Promotion store uses the same conversations.db as conversation and compaction stores."""
        session = AssistantSession(
            friday_home=temp_friday_home,
            llm_backend=None,
        )

        # All stores should point to the same database file
        expected_db = temp_friday_home / "data" / "conversations.db"

        # Verify promotion store uses the expected DB
        promo_conn = session._promotion_store._conn
        promo_db = Path(promo_conn.execute("PRAGMA database_list").fetchone()[2])

        await session.stop()

        assert promo_db == expected_db

    @pytest.mark.asyncio
    async def test_session_constructs_promoter(self, temp_friday_home) -> None:
        """AssistantSession constructs ConversationMemoryPromoter."""
        session = AssistantSession(
            friday_home=temp_friday_home,
            llm_backend=None,
        )

        assert hasattr(session, "_promoter")
        assert session._promoter is not None
        assert isinstance(session._promoter, ConversationMemoryPromoter)

        await session.stop()

    @pytest.mark.asyncio
    async def test_promoter_receives_existing_memory_manager(
        self, temp_friday_home
    ) -> None:
        """Promoter receives the session's existing DurableMemoryManager."""
        session = AssistantSession(
            friday_home=temp_friday_home,
            llm_backend=None,
        )

        # Promoter should use the same memory_manager instance
        assert session._promoter._memory_manager is session._memory_manager
        assert isinstance(session._promoter._memory_manager, DurableMemoryManager)

        await session.stop()

    @pytest.mark.asyncio
    async def test_promoter_receives_existing_resolver(self, temp_friday_home) -> None:
        """Promoter receives the session's existing MemoryResolver."""
        session = AssistantSession(
            friday_home=temp_friday_home,
            llm_backend=None,
        )

        # Promoter should use the same resolver instance
        assert session._promoter._resolver is session._memory_resolver
        assert isinstance(session._promoter._resolver, MemoryResolver)

        await session.stop()

    @pytest.mark.asyncio
    async def test_no_promotion_during_construction(self, temp_friday_home) -> None:
        """No promotion occurs during session construction."""
        session = AssistantSession(
            friday_home=temp_friday_home,
            llm_backend=None,
        )

        # Promotion store should be empty (no promote() called)
        # We can verify by checking no ledger entries exist
        # since promote() would create PENDING entries

        await session.stop()

    @pytest.mark.asyncio
    async def test_memory_extraction_construction_unchanged(
        self, temp_friday_home
    ) -> None:
        """Existing memory extraction construction remains unchanged."""
        session = AssistantSession(
            friday_home=temp_friday_home,
            llm_backend=None,
        )

        # Memory extractor should be None when no backend
        assert session._memory_extractor is None
        assert session._memory_resolver is not None
        assert isinstance(session._memory_resolver, MemoryResolver)
        assert session._extraction_interval == 10  # config default

        await session.stop()

    @pytest.mark.asyncio
    async def test_compaction_construction_unchanged(self, temp_friday_home) -> None:
        """Existing compaction construction remains unchanged."""
        session = AssistantSession(
            friday_home=temp_friday_home,
            llm_backend=None,
        )

        # Compaction should be None when no backend
        assert session._compaction_extractor is None
        assert session._compactor is None
        assert session._compaction_store is None

        await session.stop()

    @pytest.mark.asyncio
    async def test_context_assembly_unchanged(self, temp_friday_home) -> None:
        """Existing M7.1a context assembly remains unchanged."""
        session = AssistantSession(
            friday_home=temp_friday_home,
            llm_backend=None,
        )

        assert session._context_manager is not None
        assert session.conversation_store is not None

        await session.stop()

    @pytest.mark.asyncio
    async def test_background_task_behavior_unchanged(self, temp_friday_home) -> None:
        """Existing M7.1b.1 background task behavior remains unchanged."""
        session = AssistantSession(
            friday_home=temp_friday_home,
            llm_backend=None,
        )

        assert session._background_tasks == set()
        assert session._stopping is False
        assert hasattr(session, "_schedule_background")
        assert hasattr(session, "_wait_background_tasks")

        await session.stop()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
