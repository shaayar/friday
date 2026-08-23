"""M7.1b.4.2 tests — Runtime Compaction → Memory Promotion.

Verifies that successful compaction triggers promotion in the live runtime.
"""

from __future__ import annotations

import asyncio

import pytest
from friday.ai.providers import LiveKitLLMBackend
from friday.compaction.compactor import CompactionResult
from friday.compaction.models import CompactionItem, ConversationCompaction
from friday.compaction.promoter import (
    PromotionItemResult,
    PromotionOutcome,
    PromotionResult,
)
from friday.compaction.promotion import CompactionItemCategory, PromotionResolutionKind
from friday.config import config
from friday.core.session import AssistantSession


@pytest.fixture
def temp_friday_home(tmp_path, monkeypatch):
    """Temporary FRIDAY_HOME; isolates all stores for the session."""
    home = tmp_path / ".friday"
    monkeypatch.setattr(config, "FRIDAY_HOME", home)
    return home


class TestPromotionRuntimeIntegration:
    """Tests for M7.1b.4.2 — Runtime Compaction → Memory Promotion."""

    @pytest.mark.asyncio
    async def test_successful_compaction_triggers_promotion(
        self, temp_friday_home
    ) -> None:
        """Successful compaction triggers promotion background task."""

        class FakeLLM:
            def __init__(self):
                self.calls = 0

            async def complete(self, system: str, user: str) -> str:
                self.calls += 1
                if "persistent compaction" in system:
                    return """{
  "summary": "User prefers Vim for editing.",
  "facts": [{"content": "User uses Vim as editor.", "source_message_ids": [1, 2]}],
  "decisions": [],
  "changes": [],
  "open_questions": []
}"""
                return "[]"

        fake_llm = FakeLLM()
        backend = LiveKitLLMBackend(fake_llm)

        session = AssistantSession(
            friday_home=temp_friday_home,
            llm_backend=backend,
        )
        session._extraction_interval = 1
        if session._compactor is not None:
            session._compactor._message_threshold = 1

        # Mock the compaction extractor to return a valid compaction
        async def mock_compact(messages, *, conversation_id, force=False):
            # Create a valid compaction
            fact_item = CompactionItem(
                item_id="fact-1",
                content="User uses Vim as editor.",
                source_message_ids=(1, 2),
            )
            compaction = ConversationCompaction(
                compaction_id="comp-1",
                conversation_id=conversation_id,
                first_message_id=1,
                last_message_id=10,
                summary="Test compaction",
                facts=(fact_item,),
            )
            return CompactionResult(
                compacted=True, compaction=compaction, remaining_messages=0
            )

        session._compactor.compact = mock_compact

        await session.start()
        session.conversation_store.save_message(
            session.conversation_id, "user", "I use Vim."
        )
        session.conversation_store.save_message(
            session.conversation_id, "assistant", "Noted."
        )

        # Mock the promoter to track calls
        promote_calls = []

        def mock_promote(compaction, *, project_id):
            promote_calls.append((compaction, project_id))
            # Return a promotion result
            return PromotionResult(
                compaction_id=compaction.compaction_id,
                items=(
                    PromotionItemResult(
                        item_id="fact-1",
                        category=CompactionItemCategory.FACTS,
                        outcome=PromotionOutcome.PROMOTED,
                        memory_ids=("mem-1",),
                        resolution_kind=PromotionResolutionKind.CREATE,
                        reason="fake",
                    ),
                ),
            )

        session._promoter.promote = mock_promote

        try:
            session.on_assistant_persisted()

            # Wait for both background tasks to complete
            await asyncio.sleep(0.1)
            while session._background_tasks:
                await asyncio.sleep(0.01)

            # Verify promotion was called with the persisted compaction
            assert len(promote_calls) == 1
            called_compaction, _ = promote_calls[0]
            assert called_compaction.compaction_id == "comp-1"

        finally:
            await session.stop()

    @pytest.mark.asyncio
    async def test_no_compaction_does_not_trigger_promotion(
        self, temp_friday_home
    ) -> None:
        """No compaction means no promotion."""

        class FakeLLM:
            async def complete(self, system: str, user: str) -> str:
                if "persistent compaction" in system:
                    return """{"summary": "No compaction needed", "facts": [], "decisions": [], "changes": [], "open_questions": []}"""
                return "[]"

        fake_llm = FakeLLM()
        backend = LiveKitLLMBackend(fake_llm)

        session = AssistantSession(
            friday_home=temp_friday_home,
            llm_backend=backend,
        )
        session._extraction_interval = 1
        if session._compactor is not None:
            session._compactor._message_threshold = 1

        # Mock compactor to return no compaction
        async def mock_compact_no_op(messages, *, conversation_id, force=False):
            return CompactionResult(
                compacted=False, compaction=None, remaining_messages=0
            )

        session._compactor.compact = mock_compact_no_op

        # Mock promoter to verify it's never called
        promote_called = []
        original_promote = session._promoter.promote

        def mock_promote(compaction, *, project_id):
            promote_called.append(True)
            return original_promote(compaction, project_id=project_id)

        session._promoter.promote = mock_promote

        await session.start()
        session.conversation_store.save_message(
            session.conversation_id, "user", "Hello"
        )

        try:
            session.on_assistant_persisted()
            await asyncio.sleep(0.1)
            while session._background_tasks:
                await asyncio.sleep(0.01)

            assert len(promote_called) == 0, (
                "Promotion should not be called when no compaction"
            )

        finally:
            await session.stop()

    @pytest.mark.asyncio
    async def test_promotion_receives_active_project_id(self, temp_friday_home) -> None:
        """Promotion receives the active project_id from the session."""

        class FakeLLM:
            async def complete(self, system: str, user: str) -> str:
                if "persistent compaction" in system:
                    return """{
  "summary": "Project setup",
  "facts": [{"content": "Project uses Python.", "source_message_ids": [1, 2]}],
  "decisions": [{"content": "Use SQLite.", "source_message_ids": [2, 3]}],
  "changes": [],
  "open_questions": []
}"""
                return "[]"

        fake_llm = FakeLLM()
        backend = LiveKitLLMBackend(fake_llm)

        session = AssistantSession(
            friday_home=temp_friday_home,
            llm_backend=backend,
        )
        session._extraction_interval = 1
        if session._compactor is not None:
            session._compactor._message_threshold = 1

        # Register and set active project
        project_root = temp_friday_home / "test-project"
        project_root.mkdir(parents=True, exist_ok=True)
        project = session._project_service.register(project_root, name="Test Project")
        project_id = project.id
        session._project_service.activate(project_id)

        # Mock compactor
        fact_item = CompactionItem(
            item_id="fact-1",
            content="Project uses Python.",
            source_message_ids=(1, 2),
        )
        decision_item = CompactionItem(
            item_id="decision-1",
            content="Use SQLite.",
            source_message_ids=(2, 3),
        )
        compaction = ConversationCompaction(
            compaction_id="comp-1",
            conversation_id=1,
            first_message_id=1,
            last_message_id=10,
            summary="Test",
            facts=(fact_item,),
            decisions=(decision_item,),
        )

        async def mock_compact(messages, *, conversation_id, force=False):
            return CompactionResult(
                compacted=True, compaction=compaction, remaining_messages=0
            )

        session._compactor.compact = mock_compact

        # Capture project_id passed to promoter
        project_ids = []

        def mock_promote(compaction, *, project_id):
            project_ids.append(project_id)
            return PromotionResult(
                compaction_id=compaction.compaction_id,
                items=(
                    PromotionItemResult(
                        item_id="fact-1",
                        category=CompactionItemCategory.FACTS,
                        outcome=PromotionOutcome.PROMOTED,
                        memory_ids=("mem-1",),
                        resolution_kind=PromotionResolutionKind.CREATE,
                        reason="fake",
                    ),
                    PromotionItemResult(
                        item_id="decision-1",
                        category=CompactionItemCategory.DECISIONS,
                        outcome=PromotionOutcome.PROMOTED,
                        memory_ids=("mem-2",),
                        resolution_kind=PromotionResolutionKind.CREATE,
                        reason="fake",
                    ),
                ),
            )

        session._promoter.promote = mock_promote

        await session.start()
        session.conversation_store.save_message(
            session.conversation_id, "user", "We use Python."
        )

        try:
            session.on_assistant_persisted()
            await asyncio.sleep(0.1)
            while session._background_tasks:
                await asyncio.sleep(0.01)

            # Verify project_id was passed
            assert len(project_ids) == 1
            assert project_ids[0] == project_id

        finally:
            await session.stop()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
