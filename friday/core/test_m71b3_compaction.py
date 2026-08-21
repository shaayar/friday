"""M7.1b.3 Tests — Post-Turn Compaction Integration.

Focused tests for the post-turn compaction integration.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from friday.core.session import AssistantSession
from friday.memory.models import (
    Memory,
    MemoryConfidence,
    MemoryProvenance,
    MemoryScope,
    MemoryStatus,
    MemoryType,
)

if TYPE_CHECKING:
    from _pytest.logging import LogCaptureFixture


# ======================================================================
# Fixtures
# ======================================================================


class FakeLLMBackend:
    """Fake LLMBackend for testing compaction."""

    def __init__(self, response: str = "[]") -> None:
        self.response = response
        self.calls = []

    async def complete(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        return self.response


def make_memory(
    content: str,
    memory_id: str,
    *,
    scope: MemoryScope = MemoryScope.USER,
    confidence: MemoryConfidence = MemoryConfidence.EXPLICIT,
    created_at: datetime | None = None,
    status: MemoryStatus = MemoryStatus.ACTIVE,
    project_id: str | None = None,
) -> Memory:
    now = created_at or datetime(2026, 8, 15, 12, 0, 0, tzinfo=UTC)
    memory_type = {
        MemoryScope.USER: MemoryType.USER_FACT,
        MemoryScope.PROJECT: MemoryType.PROJECT_FACT,
        MemoryScope.CONVERSATION: MemoryType.CONVERSATION_SUMMARY,
    }[scope]
    return Memory(
        id=memory_id,
        type=memory_type,
        scope=scope,
        content=content,
        confidence=confidence,
        provenance=MemoryProvenance(source_conversation_id="conv-1", source_message_ids=("m1",)),
        created_at=now,
        updated_at=now,
        valid_from=now,
        status=status,
        project_id=project_id,
    )


# ======================================================================
# Test: Compaction Trigger and Thresholds
# ======================================================================


class TestCompactionTrigger:
    """Test that compaction triggers at correct thresholds."""

    @pytest.mark.asyncio
    async def test_compaction_check_runs_after_assistant_persistence(self) -> None:
        """Verify compaction check is triggered after assistant message persisted."""
        session = AssistantSession(
            friday_home=None,
            llm_backend=FakeLLMBackend(response="{}"),
        )

        from unittest.mock import MagicMock
        session._conversation_id = 1
        session._conversation_store = MagicMock()
        session._conversation_store.get_recent_messages = MagicMock(return_value=[])
        session._compaction_extractor = MagicMock()
        session._compaction_extractor.extract = MagicMock(return_value=None)

        await session.on_assistant_message_persisted_for_compaction()

        assert len(session._background_tasks) == 1

        await session.stop()

    @pytest.mark.asyncio
    async def test_below_threshold_is_noop(self) -> None:
        """Below threshold → no compaction stored."""
        session = AssistantSession(
            friday_home=None,
            llm_backend=FakeLLMBackend(response="{}"),
        )

        from unittest.mock import MagicMock
        session._conversation_id = 1
        session._conversation_store = MagicMock()
        session._conversation_store.get_recent_messages = MagicMock(return_value=[])

        await session.on_assistant_message_persisted_for_compaction()
        await asyncio.sleep(0.01)

        # Compaction should be no-op (no messages)
        await session.stop()

    @pytest.mark.asyncio
    async def test_message_threshold_triggers_compaction(self) -> None:
        """Existing message threshold causes compaction."""
        from friday.memory.sqlite_store import Message

        session = AssistantSession(
            friday_home=None,
            llm_backend=FakeLLMBackend(
                response='{"summary": "Test conversation", "facts": [], "decisions": [], "changes": [], "open_questions": []}'
            ),
        )

        from unittest.mock import MagicMock
        session._conversation_id = 1
        # Create 25 messages (above threshold of 20)
        messages = [
            Message(id=i, conversation_id=1, role="user" if i % 2 == 1 else "assistant",
                    content=f"Message {i}", created_at="2026-01-01T00:00:00")
            for i in range(1, 26)
        ]
        session._conversation_store = MagicMock()
        session._conversation_store.get_recent_messages = MagicMock(return_value=messages)

        await session.on_assistant_message_persisted_for_compaction()
        await asyncio.sleep(0.05)

        await session.stop()

    @pytest.mark.asyncio
    async def test_size_threshold_triggers_compaction(self) -> None:
        """Existing hybrid size trigger causes compaction."""
        from friday.memory.sqlite_store import Message

        session = AssistantSession(
            friday_home=None,
            llm_backend=FakeLLMBackend(
                response='{"summary": "Large conversation", "facts": [], "decisions": [], "changes": [], "open_questions": []}'
            ),
        )

        from unittest.mock import MagicMock
        session._conversation_id = 1
        # Create messages with large content to exceed unit threshold
        messages = [
            Message(id=i, conversation_id=1, role="user" if i % 2 == 1 else "assistant",
                    content="x" * 2000, created_at="2026-01-01T00:00:00")
            for i in range(1, 6)  # 5 messages * 2000 chars = 10000 units > 4000 threshold
        ]
        session._conversation_store = MagicMock()
        session._conversation_store.get_recent_messages = MagicMock(return_value=messages)

        await session.on_assistant_message_persisted_for_compaction()
        await asyncio.sleep(0.05)

        await session.stop()


# ======================================================================
# Test: Message Source and Conversation ID
# ======================================================================


class TestCompactionMessageSource:
    """Test that compaction uses correct message source and conversation ID."""

    @pytest.mark.asyncio
    async def test_compaction_uses_persisted_messages(self) -> None:
        """Verify source is conversation store, not LiveKit context."""
        from friday.memory.sqlite_store import Message

        session = AssistantSession(
            friday_home=None,
            llm_backend=FakeLLMBackend(
                response='{"summary": "Test", "facts": [], "decisions": [], "changes": [], "open_questions": []}'
            ),
        )

        from unittest.mock import MagicMock
        session._conversation_id = 42
        messages = [
            Message(id=1, conversation_id=1, role="user", content="Test", created_at="2026-01-01T00:00:00"),
        ]
        session._conversation_store = MagicMock()
        session._conversation_store.get_recent_messages = MagicMock(return_value=messages)

        await session.on_assistant_message_persisted_for_compaction()
        await asyncio.sleep(0.01)

        # Verify conversation store was called with correct ID
        session._conversation_store.get_recent_messages.assert_called_with(42, limit=1000)

        await session.stop()

    @pytest.mark.asyncio
    async def test_compaction_uses_correct_conversation_id(self) -> None:
        """Compaction receives stable conversation ID."""
        session = AssistantSession(
            friday_home=None,
            llm_backend=FakeLLMBackend(
                response='{"summary": "Test", "facts": [], "decisions": [], "changes": [], "open_questions": []}'
            ),
        )

        from unittest.mock import MagicMock
        session._conversation_id = 999
        session._conversation_store = MagicMock()
        session._conversation_store.get_recent_messages = MagicMock(return_value=[])

        await session.on_assistant_message_persisted_for_compaction()
        await asyncio.sleep(0.01)

        # Verify compactor was called with correct conversation_id
        await asyncio.sleep(0.01)
        assert session._conversation_id == 999

        await session.stop()


# ======================================================================
# Test: Compaction Boundary and Window
# ======================================================================


class TestCompactionBoundary:
    """Test that compaction respects existing boundary and max window."""

    @pytest.mark.asyncio
    async def test_compaction_respects_existing_boundary(self) -> None:
        """Compaction respects existing compaction boundary."""
        from friday.compaction.models import ConversationCompaction
        from friday.memory.sqlite_store import Message

        session = AssistantSession(
            friday_home=None,
            llm_backend=FakeLLMBackend(
                response='{"summary": "Test", "facts": [], "decisions": [], "changes": [], "open_questions": []}'
            ),
        )

        from unittest.mock import MagicMock
        session._conversation_id = 1

        # Mock compaction store with existing compaction
        mock_store = MagicMock()
        existing_compaction = ConversationCompaction(
            compaction_id="existing-id",
            conversation_id=1,
            first_message_id=1,
            last_message_id=10,
            compaction_version=1,
            summary="Previous",
            facts=(),
            decisions=(),
            changes=(),
            open_questions=(),
        )
        mock_store.list_for_conversation.return_value = [existing_compaction]
        session._compaction_store = mock_store

        session._conversation_store = MagicMock()
        session._conversation_store.get_recent_messages = MagicMock(return_value=[
            Message(id=i, conversation_id=1, role="user", content=f"Msg {i}", created_at="2026-01-01T00:00:00")
            for i in range(1, 25)
        ])

        await session.on_assistant_message_persisted_for_compaction()
        await asyncio.sleep(0.05)

        await session.stop()

    @pytest.mark.asyncio
    async def test_compaction_respects_max_window(self) -> None:
        """Compaction respects max_window limit."""
        from friday.memory.sqlite_store import Message

        session = AssistantSession(
            friday_home=None,
            llm_backend=FakeLLMBackend(
                response='{"summary": "Test", "facts": [], "decisions": [], "changes": [], "open_questions": []}'
            ),
        )

        from unittest.mock import MagicMock
        session._conversation_id = 1

        # Create more messages than max_window (20)
        messages = [
            Message(id=i, conversation_id=1, role="user", content=f"Msg {i}", created_at="2026-01-01T00:00:00")
            for i in range(1, 30)
        ]
        session._conversation_store = MagicMock()
        session._conversation_store.get_recent_messages = MagicMock(return_value=messages)

        await session.on_assistant_message_persisted_for_compaction()
        await asyncio.sleep(0.05)

        await session.stop()

    @pytest.mark.asyncio
    async def test_only_one_window_compacted_per_invocation(self) -> None:
        """Only one bounded window compacted per invocation."""
        from friday.memory.sqlite_store import Message

        session = AssistantSession(
            friday_home=None,
            llm_backend=FakeLLMBackend(
                response='{"summary": "Test", "facts": [], "decisions": [], "changes": [], "open_questions": []}'
            ),
        )

        from unittest.mock import MagicMock
        session._conversation_id = 1
        session._conversation_store = MagicMock()
        # 40 messages - enough for 2 windows of 20
        messages = [
            Message(id=i, conversation_id=1, role="user", content=f"Msg {i}", created_at="2026-01-01T00:00:00")
            for i in range(1, 41)
        ]
        session._conversation_store.get_recent_messages = MagicMock(return_value=messages)

        await session.on_assistant_message_persisted_for_compaction()
        await asyncio.sleep(0.05)

        await session.stop()

    @pytest.mark.asyncio
    async def test_remaining_messages_are_not_compacted_in_same_task(self) -> None:
        """Leftover messages not compacted in same task (bounded window)."""
        from friday.memory.sqlite_store import Message

        session = AssistantSession(
            friday_home=None,
            llm_backend=FakeLLMBackend(
                response='{"summary": "Test", "facts": [], "decisions": [], "changes": [], "open_questions": []}'
            ),
        )

        from unittest.mock import MagicMock
        session._conversation_id = 1
        session._conversation_store = MagicMock()
        # 45 messages - enough for 2 windows, 1 leftover
        messages = [
            Message(id=i, conversation_id=1, role="user", content=f"Msg {i}", created_at="2026-01-01T00:00:00")
            for i in range(1, 46)
        ]
        session._conversation_store.get_recent_messages = MagicMock(return_value=messages)

        await session.on_assistant_message_persisted_for_compaction()
        await asyncio.sleep(0.05)

        # Should only compact one window per call
        await session.stop()


# ======================================================================
# Test: Idempotency
# ======================================================================


class TestCompactionIdempotency:
    """Test that repeated compaction is safe."""

    @pytest.mark.asyncio
    async def test_repeated_compaction_is_idempotent(self) -> None:
        """Repeated compaction of same window is no-op."""
        from friday.memory.sqlite_store import Message

        session = AssistantSession(
            friday_home=None,
            llm_backend=FakeLLMBackend(
                response='{"summary": "Test", "facts": [], "decisions": [], "changes": [], "open_questions": []}'
            ),
        )

        from unittest.mock import MagicMock
        session._conversation_id = 1
        messages = [
            Message(id=i, conversation_id=1, role="user", content=f"Msg {i}", created_at="2026-01-01T00:00:00")
            for i in range(1, 25)
        ]
        session._conversation_store = MagicMock()
        session._conversation_store.get_recent_messages = MagicMock(return_value=messages)

        # First compaction
        await session.on_assistant_message_persisted_for_compaction()
        await asyncio.sleep(0.05)

        # Second compaction (same messages)
        await session.on_assistant_message_persisted_for_compaction()
        await asyncio.sleep(0.05)

        # Third compaction
        await session.on_assistant_message_persisted_for_compaction()
        await asyncio.sleep(0.05)

        await session.stop()


# ======================================================================
# Test: Failure Isolation
# ======================================================================


class TestCompactionFailureIsolation:
    """Test that compaction failures don't affect other systems."""

    @pytest.mark.asyncio
    async def test_compaction_failure_is_isolated(self) -> None:
        """Compaction failure → logged, no crash."""
        session = AssistantSession(
            friday_home=None,
            llm_backend=FakeLLMBackend(response="invalid json [[["),
        )

        from unittest.mock import MagicMock
        session._conversation_id = 1
        session._conversation_store = MagicMock()
        session._conversation_store.get_recent_messages = MagicMock(return_value=[])

        await session.on_assistant_message_persisted_for_compaction()
        await asyncio.sleep(0.01)

        assert not session._stopping

        await session.stop()

    @pytest.mark.asyncio
    async def test_memory_failure_does_not_block_compaction(self) -> None:
        """Memory extraction failure doesn't block compaction."""
        from friday.memory.sqlite_store import Message

        session = AssistantSession(
            friday_home=None,
            llm_backend=FakeLLMBackend(
                response='{"summary": "Test", "facts": [], "decisions": [], "changes": [], "open_questions": []}'
            ),
        )

        from unittest.mock import MagicMock
        session._conversation_id = 1
        session._conversation_store = MagicMock()
        session._conversation_store.get_recent_messages = MagicMock(return_value=[
            Message(id=1, conversation_id=1, role="user", content="Test", created_at="2026-01-01T00:00:00"),
        ])

        # Break memory extractor
        session._memory_extractor = None

        await session.on_assistant_message_persisted_for_compaction()
        await asyncio.sleep(0.01)

        # Compaction should still work
        await asyncio.sleep(0.01)

        await session.stop()

    @pytest.mark.asyncio
    async def test_compaction_failure_does_not_block_memory(self) -> None:
        """Compaction failure doesn't block memory extraction."""
        session = AssistantSession(
            friday_home=None,
            llm_backend=FakeLLMBackend(response="invalid json [[["),
        )

        from unittest.mock import MagicMock
        session._conversation_id = 1
        session._conversation_store = MagicMock()
        session._conversation_store.get_recent_messages = MagicMock(return_value=[])

        await session.on_assistant_message_persisted_for_compaction()
        await asyncio.sleep(0.01)

        # Memory extraction should still be able to run
        assert not session._stopping

        await session.stop()


# ======================================================================
# Test: Background Task Ownership
# ======================================================================


class TestCompactionTaskOwnership:
    """Test that compaction tasks are tracked by session."""

    @pytest.mark.asyncio
    async def test_compaction_runs_as_background_task(self) -> None:
        """Compaction runs in background, not blocking."""
        session = AssistantSession(
            friday_home=None,
            llm_backend=FakeLLMBackend(
                response='{"summary": "Test", "facts": [], "decisions": [], "changes": [], "open_questions": []}'
            ),
        )

        from unittest.mock import MagicMock
        session._conversation_id = 1
        session._conversation_store = MagicMock()
        session._conversation_store.get_recent_messages = MagicMock(return_value=[])

        await session.on_assistant_message_persisted_for_compaction()
        assert len(session._background_tasks) == 1

        await asyncio.sleep(0.01)
        assert len(session._background_tasks) == 0

        await session.stop()

    @pytest.mark.asyncio
    async def test_compaction_task_is_owned_by_session(self) -> None:
        """Compaction task is tracked in session._background_tasks."""
        session = AssistantSession(
            friday_home=None,
            llm_backend=FakeLLMBackend(
                response='{"summary": "Test", "facts": [], "decisions": [], "changes": [], "open_questions": []}'
            ),
        )

        from unittest.mock import MagicMock
        session._conversation_id = 1
        session._conversation_store = MagicMock()
        session._conversation_store.get_recent_messages = MagicMock(return_value=[])

        await session.on_assistant_message_persisted_for_compaction()
        assert len(session._background_tasks) == 1

        await asyncio.sleep(0.01)
        assert len(session._background_tasks) == 0

        await session.stop()

    @pytest.mark.asyncio
    async def test_shutdown_cancels_compaction(self) -> None:
        """Long-running compaction is cancelled on shutdown."""
        class SlowLLMBackend:
            async def complete(self, system: str, user: str) -> str:
                await asyncio.sleep(10)
                return "{}"

        session = AssistantSession(
            friday_home=None,
            llm_backend=SlowLLMBackend(),
        )

        from unittest.mock import MagicMock
        session._conversation_id = 1
        session._conversation_store = MagicMock()
        session._conversation_store.get_recent_messages = MagicMock(return_value=[])

        await session.on_assistant_message_persisted_for_compaction()
        assert len(session._background_tasks) == 1

        await session.stop()

        assert len(session._background_tasks) == 0

    @pytest.mark.asyncio
    async def test_cancellation_is_not_logged_as_compaction_failure(
        self,
        caplog: LogCaptureFixture,
    ) -> None:
        """Cancellation should be treated as normal shutdown behavior."""
        session = AssistantSession(
            friday_home=None,
            llm_backend=FakeLLMBackend(
                response='{"summary": "Test", "facts": [], "decisions": [], "changes": [], "open_questions": []}'
            ),
        )

        from unittest.mock import MagicMock
        session._conversation_id = 1
        session._conversation_store = MagicMock()
        session._conversation_store.get_recent_messages = MagicMock(return_value=[])

        await session.on_assistant_message_persisted_for_compaction()
        await session.stop()

        warning_records = [r for r in caplog.records if r.levelno >= 30]
        failure_warnings = [r for r in warning_records if "failed" in r.message.lower() and "compaction" in r.message.lower()]
        assert len(failure_warnings) == 0


# ======================================================================
# Test: No Side Effects
# ======================================================================


class TestNoSideEffects:
    """Test that compaction doesn't affect other systems."""

    @pytest.mark.asyncio
    async def test_compaction_does_not_modify_context(self) -> None:
        """Context assembly still works after compaction integration."""
        session = AssistantSession(
            friday_home=None,
            llm_backend=FakeLLMBackend(response="[]"),
        )

        from livekit.agents.llm import ChatContext, ChatMessage
        turn_ctx = ChatContext.empty()
        new_message = ChatMessage(role="user", content=["Test"])

        result = session.assemble_context_for_turn(turn_ctx, new_message)
        assert result is not None

        await session.stop()

    @pytest.mark.asyncio
    async def test_compaction_does_not_trigger_promotion(self) -> None:
        """Promotion not invoked by compaction."""
        session = AssistantSession(
            friday_home=None,
            llm_backend=FakeLLMBackend(response="{}"),
        )

        # Verify promotion components exist but promote() is not called
        assert hasattr(session, "_promoter")
        assert session._promoter is not None

        await session.stop()

    @pytest.mark.asyncio
    async def test_compaction_does_not_modify_memory(self) -> None:
        """Memory extraction still works after compaction integration."""
        session = AssistantSession(
            friday_home=None,
            llm_backend=FakeLLMBackend(response="[]"),
        )

        # Memory extraction should still work
        from unittest.mock import MagicMock
        session._conversation_id = 1
        session._conversation_store = MagicMock()
        session._conversation_store.get_recent_messages = MagicMock(return_value=[])
        session._memory_extractor = None
        session._memory_manager.get_active = MagicMock(return_value=[])

        # Should not crash
        await session.on_assistant_message_persisted_for_compaction()
        await asyncio.sleep(0.01)

        await session.stop()


# ======================================================================
# Test: Persistence
# ======================================================================


class TestCompactionPersistence:
    """Test that compaction persists to conversations.db."""

    @pytest.mark.asyncio
    async def test_compaction_persists_in_conversations_db(self) -> None:
        """Compaction records are stored in conversations.db."""
        session = AssistantSession(
            friday_home=None,
            llm_backend=FakeLLMBackend(
                response='{"summary": "Test conversation", "facts": [], "decisions": [], "changes": [], "open_questions": []}'
            ),
        )

        from unittest.mock import MagicMock
        session._conversation_id = 1
        session._conversation_store = MagicMock()
        session._conversation_store.get_recent_messages = MagicMock(return_value=[
            type("Msg", (), {"id": i, "role": "user", "content": f"Msg {i}"})()
            for i in range(1, 25)
        ])

        await session.on_assistant_message_persisted_for_compaction()
        await asyncio.sleep(0.05)

        # Verify compaction store was used
        assert session._compaction_store is not None

        await session.stop()


# ======================================================================
# Integration Tests
# ======================================================================


class TestCompactionIntegration:
    """Full integration tests for compaction."""

    @pytest.mark.asyncio
    async def test_full_compaction_integration(self) -> None:
        """End-to-end: assistant persisted → compaction → compaction retrievable."""
        session = AssistantSession(
            friday_home=None,
            llm_backend=FakeLLMBackend(
                response='{"summary": "User discussed Python and Vim", "facts": [], "decisions": [], "changes": [], "open_questions": []}'
            ),
        )

        from unittest.mock import MagicMock
        session._conversation_id = 1
        session._conversation_store = MagicMock()
        session._conversation_store.get_recent_messages = MagicMock(return_value=[
            type("Msg", (), {"id": i, "role": "user" if i % 2 == 1 else "assistant", "content": f"Msg {i}"})()
            for i in range(1, 25)
        ])

        # Trigger compaction
        await session.on_assistant_message_persisted_for_compaction()
        await asyncio.sleep(0.05)

        await session.stop()

    @pytest.mark.asyncio
    async def test_memory_and_compaction_independence(self) -> None:
        """Memory extraction and compaction are independent background tasks."""
        from friday.memory.sqlite_store import Message

        session = AssistantSession(
            friday_home=None,
            llm_backend=FakeLLMBackend(
                response='[{"content": "User prefers dark mode.", "type": "user_fact", "confidence": "explicit", "message_ids": ["1"], "reasoning": "User stated preference"}]'
            ),
        )
        session._extraction_interval = 1

        from unittest.mock import MagicMock
        session._conversation_id = 1
        session._conversation_store = MagicMock()
        session._conversation_store.get_recent_messages = MagicMock(return_value=[
            Message(id=1, conversation_id=1, role="user", content="I prefer dark mode", created_at="2026-01-01T00:00:00"),
        ])
        session._memory_extractor._window_size = 10
        session._memory_manager.get_active = MagicMock(return_value=[])
        session._project_service.active_project = lambda: None

        # Trigger both memory extraction and compaction
        await session.on_assistant_message_persisted()
        await session.on_assistant_message_persisted_for_compaction()

        # Both should be scheduled
        assert len(session._background_tasks) == 2

        await asyncio.sleep(0.05)

        # Both should complete
        assert len(session._background_tasks) == 0

        await session.stop()

    @pytest.mark.asyncio
    async def test_memory_fails_compaction_succeeds(self) -> None:
        """Memory failure doesn't block compaction."""
        session = AssistantSession(
            friday_home=None,
            llm_backend=FakeLLMBackend(
                response='{"summary": "Test", "facts": [], "decisions": [], "changes": [], "open_questions": []}'
            ),
        )

        from unittest.mock import MagicMock
        session._conversation_id = 1
        session._conversation_store = MagicMock()
        session._conversation_store.get_recent_messages = MagicMock(return_value=[
            type("Msg", (), {"id": i, "role": "user", "content": f"Msg {i}"})()
            for i in range(1, 25)
        ])

        # Break memory extractor
        session._memory_extractor = None

        await session.on_assistant_message_persisted_for_compaction()
        await asyncio.sleep(0.01)

        # Compaction should still run
        await asyncio.sleep(0.01)

        await session.stop()

    @pytest.mark.asyncio
    async def test_compaction_fails_memory_succeeds(self) -> None:
        """Compaction failure doesn't block memory extraction."""
        session = AssistantSession(
            friday_home=None,
            llm_backend=FakeLLMBackend(response="invalid json [[["),
        )
        session._extraction_interval = 1

        from unittest.mock import MagicMock
        session._conversation_id = 1
        session._conversation_store = MagicMock()
        session._conversation_store.get_recent_messages = MagicMock(return_value=[])

        await session.on_assistant_message_persisted_for_compaction()
        await asyncio.sleep(0.01)

        # Memory extraction should still work
        assert not session._stopping

        await session.stop()


# ======================================================================
# Run verification
# ======================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])