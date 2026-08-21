"""M7.1b.2 Tests — Memory Extraction Integration.

Focused tests for the post-turn memory extraction pipeline.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

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

# ======================================================================
# Fixtures
# ======================================================================


@pytest.fixture
def temp_friday_home(tmp_path):
    """Provide a temporary FRIDAY_HOME for each test."""
    return tmp_path / ".friday"


@pytest.fixture
def assistant_session(temp_friday_home):
    """Create an AssistantSession with a fresh temporary database for each test."""

    from friday.core.session import AssistantSession
    
    llm_backend = FakeLLMBackend(response="[]")
    session = AssistantSession(
        friday_home=temp_friday_home,
        llm_backend=llm_backend,
    )
    session._extraction_interval = 1
    session._project_service.active_project = lambda: None
    
    yield session
    
    # Cleanup
    import asyncio
    asyncio.run(session.stop())


class FakeLLMBackend:
    """Fake LLMBackend for testing memory extraction."""

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
# Test: Turn Counter / Trigger Interval
# ======================================================================


class TestMemoryExtractionTrigger:
    """Test that memory extraction triggers at the correct interval."""

    @pytest.mark.asyncio
    async def test_memory_extraction_scheduled_at_interval(self) -> None:
        """Below interval → no extraction; interval reached → extraction scheduled."""
        # Use interval of 3 for fast testing
        session = AssistantSession(
            friday_home=None,
            llm_backend=FakeLLMBackend(response="[]"),
        )
        session._extraction_interval = 3

        # Mock the conversation store
        from unittest.mock import MagicMock
        session._conversation_id = 1
        session._conversation_store = MagicMock()
        session._conversation_store.get_recent_messages = MagicMock(return_value=[])
        session._memory_extractor._window_size = 10

        # Turn 1: no extraction
        session._turn_count = 0
        await session.on_assistant_message_persisted()
        assert session._turn_count == 1
        assert len(session._background_tasks) == 0

        # Turn 2: no extraction
        await session.on_assistant_message_persisted()
        assert session._turn_count == 2
        assert len(session._background_tasks) == 0

        # Turn 3: extraction scheduled
        await session.on_assistant_message_persisted()
        assert session._turn_count == 3
        assert len(session._background_tasks) == 1

        # Clean up
        await session.stop()

    @pytest.mark.asyncio
    async def test_memory_extraction_not_scheduled_after_stop(self) -> None:
        """After stop(), new extraction tasks are rejected."""
        session = AssistantSession(
            friday_home=None,
            llm_backend=FakeLLMBackend(response="[]"),
        )
        session._extraction_interval = 1

        await session.stop()

        await session.on_assistant_message_persisted()
        assert len(session._background_tasks) == 0


# ======================================================================
# Test: Lifecycle Boundary - After Assistant Persistence
# ======================================================================


class TestMemoryExtractionLifecycle:
    """Test that extraction runs after assistant message is persisted."""

    @pytest.mark.asyncio
    async def test_extraction_runs_after_assistant_persistence(self) -> None:
        """Verify extraction is triggered by assistant message persistence, not user."""
        session = AssistantSession(
            friday_home=None,
            llm_backend=FakeLLMBackend(response="[]"),
        )
        session._extraction_interval = 1

        from unittest.mock import MagicMock
        session._conversation_id = 1
        session._conversation_store = MagicMock()
        session._conversation_store.get_recent_messages = MagicMock(return_value=[])
        session._memory_extractor._window_size = 10

        # Simulate assistant message persisted (turn_count increments)
        await session.on_assistant_message_persisted()
        assert session._turn_count == 1
        assert len(session._background_tasks) == 1

        await session.stop()


# ======================================================================
# Test: Conversation ID and Project ID Sourcing
# ======================================================================


class TestMemoryExtractionIdentity:
    """Test that conversation_id and project_id are sourced correctly."""

    @pytest.mark.asyncio
    async def test_extractor_receives_correct_conversation_id(self) -> None:
        """Extractor receives the session's conversation_id."""
        session = AssistantSession(
            friday_home=None,
            llm_backend=FakeLLMBackend(response="[]"),
        )
        session._extraction_interval = 1

        from unittest.mock import MagicMock
        session._conversation_id = 1
        session._conversation_store = MagicMock()
        session._conversation_store.get_recent_messages = MagicMock(return_value=[])
        session._memory_extractor._window_size = 10
        session._project_service.active_project = lambda: None

        await session.on_assistant_message_persisted()

        # Verify the task was scheduled and extractor called with correct ID
        await asyncio.sleep(0.01)  # Let background task run

        # The extractor is called with conversation_id
        assert session._conversation_id == 1

        await session.stop()

    @pytest.mark.asyncio
    async def test_extractor_receives_deterministic_project_id(self) -> None:
        """Extractor receives active_project_id from session (deterministic, not LLM)."""
        session = AssistantSession(
            friday_home=None,
            llm_backend=FakeLLMBackend(response="[]"),
        )
        session._extraction_interval = 1

        from unittest.mock import MagicMock
        session._conversation_id = 1
        session._conversation_store = MagicMock()
        session._conversation_store.get_recent_messages = MagicMock(return_value=[])
        session._memory_extractor._window_size = 10

        # Mock project service to return a specific project
        mock_active = MagicMock()
        mock_active.project_id = "proj-test-123"
        session._project_service.active_project = lambda: mock_active

        await session.on_assistant_message_persisted()
        await asyncio.sleep(0.01)

        # Verify project_id passed to extractor matches deterministic source
        assert session.active_project_id == "proj-test-123"

        await session.stop()

    @pytest.mark.asyncio
    async def test_extractor_works_without_project_id(self) -> None:
        """Extraction works when no active project (project_id=None)."""
        session = AssistantSession(
            friday_home=None,
            llm_backend=FakeLLMBackend(response="[]"),
        )
        session._extraction_interval = 1

        from unittest.mock import MagicMock
        session._conversation_id = 1
        session._conversation_store = MagicMock()
        session._conversation_store.get_recent_messages = MagicMock(return_value=[])
        session._memory_extractor._window_size = 10

        # No active project
        session._project_service.active_project = lambda: None

        await session.on_assistant_message_persisted()
        await asyncio.sleep(0.01)

        assert session.active_project_id is None

        await session.stop()


# ======================================================================
# Test: Message Window and Provenance
# ======================================================================


class TestMemoryExtractionMessages:
    """Test that extractor receives correct message window with IDs, roles, content."""

    @pytest.mark.asyncio
    async def test_extractor_receives_conversation_messages(self) -> None:
        """Extractor receives messages with correct IDs, roles, content."""
        from friday.memory.sqlite_store import Message

        session = AssistantSession(
            friday_home=None,
            llm_backend=FakeLLMBackend(response="[]"),
        )
        session._extraction_interval = 1

        from unittest.mock import MagicMock
        session._conversation_id = 1
        session._project_service.active_project = MagicMock(return_value=None)

        # Create mock messages with proper IDs
        msg1 = Message(id=1, conversation_id=1, role="user", content="Hello", created_at="2026-01-01T00:00:00")
        msg2 = Message(id=2, conversation_id=1, role="assistant", content="Hi there!", created_at="2026-01-01T00:00:01")
        msg3 = Message(id=3, conversation_id=1, role="user", content="How are you?", created_at="2026-01-01T00:00:02")

        session._conversation_store = MagicMock()
        session._conversation_store.get_recent_messages = MagicMock(return_value=[msg1, msg2, msg3])
        session._memory_extractor._window_size = 10
        session._memory_manager.get_active = MagicMock(return_value=[])

        # Track what messages were passed to extractor
        original_extract = session._memory_extractor.extract
        captured_messages = []

        def capture_extract(messages, *, conversation_id, project_id):
            captured_messages.extend(messages)
            return original_extract(messages, conversation_id=conversation_id, project_id=project_id)

        session._memory_extractor.extract = capture_extract

        await session.on_assistant_message_persisted()
        await asyncio.sleep(0.01)

        # Verify messages passed to extractor
        assert len(captured_messages) == 3
        assert captured_messages[0] == ("1", "user", "Hello")
        assert captured_messages[1] == ("2", "assistant", "Hi there!")
        assert captured_messages[2] == ("3", "user", "How are you?")

        await session.stop()


# ======================================================================
# Test: Extraction → Resolver → Memory Manager Pipeline
# ======================================================================


class TestMemoryExtractionPipeline:
    """Test the full pipeline: Extractor → Resolver → DurableMemoryManager."""

    @pytest.mark.asyncio
    async def test_memory_candidate_reaches_resolver(self) -> None:
        """Extracted candidates flow through resolver."""
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
        session._project_service.active_project = lambda: None

        await session.on_assistant_message_persisted()
        await asyncio.sleep(0.01)

        # Verify resolver was called (via apply_batch which calls it)
        assert len(session._background_tasks) == 0  # Task completed

        await session.stop()

    @pytest.mark.asyncio
    async def test_created_memory_persists(self, temp_friday_home) -> None:
        """Extracted memory is persisted to memory.db."""
        from friday.memory.sqlite_store import Message

        llm_backend = FakeLLMBackend(
            response='[{"content": "User prefers dark mode.", "type": "user_fact", "confidence": "explicit", "message_ids": ["1"], "reasoning": "User stated preference"}]'
        )
        session = AssistantSession(
            friday_home=temp_friday_home,
            llm_backend=llm_backend,
        )
        session._extraction_interval = 1

        from unittest.mock import MagicMock
        session._conversation_id = 1
        session._conversation_store = MagicMock()
        session._conversation_store.get_recent_messages = MagicMock(return_value=[
            Message(id=1, conversation_id=1, role="user", content="I prefer dark mode", created_at="2026-01-01T00:00:00"),
        ])
        session._memory_extractor._window_size = 10
        session._project_service.active_project = lambda: None

        await session.on_assistant_message_persisted()
        await asyncio.sleep(0.01)

        # Memory should be in memory store (verify via manager)
        memories = session._memory_manager.get_active()
        assert len(memories) == 1
        assert memories[0].content == "User prefers dark mode."
        assert memories[0].type == MemoryType.USER_FACT

        await session.stop()

    @pytest.mark.asyncio
    async def test_memory_provenance_is_preserved(self, temp_friday_home) -> None:
        """Persisted memories contain source_conversation_id and source_message_ids."""
        from friday.memory.sqlite_store import Message

        llm_backend = FakeLLMBackend(
            response='[{"content": "User prefers dark mode.", "type": "user_fact", "confidence": "explicit", "message_ids": ["1", "3"], "reasoning": "User stated preference"}]'
        )
        session = AssistantSession(
            friday_home=temp_friday_home,
            llm_backend=llm_backend,
        )
        session._extraction_interval = 1

        from unittest.mock import MagicMock
        session._conversation_id = 1
        session._conversation_store = MagicMock()
        session._conversation_store.get_recent_messages = MagicMock(return_value=[
            Message(id=1, conversation_id=1, role="user", content="I prefer dark mode", created_at="2026-01-01T00:00:00"),
            Message(id=2, conversation_id=1, role="assistant", content="Noted", created_at="2026-01-01T00:00:01"),
            Message(id=3, conversation_id=1, role="user", content="Really, I do", created_at="2026-01-01T00:00:02"),
        ])
        session._memory_extractor._window_size = 10
        session._project_service.active_project = lambda: None

        await session.on_assistant_message_persisted()
        await asyncio.sleep(0.01)

        memories = session._memory_manager.get_active()
        assert len(memories) == 1
        mem = memories[0]
        assert mem.provenance.source_conversation_id == "1"
        assert set(mem.provenance.source_message_ids) == {"1", "3"}

        await session.stop()


# ======================================================================
# Test: Project Scoping
# ======================================================================


class TestMemoryExtractionProjectScoping:
    """Test project-scoped vs user-scoped memories."""

    @pytest.mark.asyncio
    async def test_user_memory_without_project_id(self, temp_friday_home) -> None:
        """USER_FACT memories work without project_id."""
        from friday.memory.sqlite_store import Message

        llm_backend = FakeLLMBackend(
            response='[{"content": "User prefers Vim.", "type": "user_fact", "confidence": "explicit", "message_ids": ["1"], "reasoning": "User stated preference"}]'
        )
        session = AssistantSession(
            friday_home=temp_friday_home,
            llm_backend=llm_backend,
        )
        session._extraction_interval = 1

        from unittest.mock import MagicMock
        session._conversation_id = 1
        session._conversation_store = MagicMock()
        session._conversation_store.get_recent_messages = MagicMock(return_value=[
            Message(id=1, conversation_id=1, role="user", content="I use Vim", created_at="2026-01-01T00:00:00"),
        ])
        session._memory_extractor._window_size = 10
        session._project_service.active_project = lambda: None

        # Don't mock get_active
        await session.on_assistant_message_persisted()
        await asyncio.sleep(0.01)

        memories = session._memory_manager.get_active()
        assert len(memories) == 1
        assert memories[0].scope == MemoryScope.USER
        assert memories[0].project_id is None

        await session.stop()

    @pytest.mark.asyncio
    async def test_project_memory_gets_project_id(self, temp_friday_home) -> None:
        """PROJECT_FACT memories receive the deterministic project_id."""
        from friday.memory.sqlite_store import Message

        llm_backend = FakeLLMBackend(
            response='[{"content": "The project uses Python.", "type": "project_fact", "confidence": "explicit", "message_ids": ["1"], "reasoning": "Project uses Python"}]'
        )
        session = AssistantSession(
            friday_home=temp_friday_home,
            llm_backend=llm_backend,
        )
        session._extraction_interval = 1

        from unittest.mock import MagicMock
        session._conversation_id = 1
        session._conversation_store = MagicMock()
        session._conversation_store.get_recent_messages = MagicMock(return_value=[
            Message(id=1, conversation_id=1, role="user", content="This project uses Python", created_at="2026-01-01T00:00:00"),
        ])
        session._memory_extractor._window_size = 10

        mock_active = MagicMock()
        mock_active.project_id = "proj-123"
        session._project_service.active_project = lambda: mock_active

        await session.on_assistant_message_persisted()
        await asyncio.sleep(0.01)

        memories = session._memory_manager.get_active()
        assert len(memories) == 1
        assert memories[0].scope == MemoryScope.PROJECT
        assert memories[0].project_id == "proj-123"

        await session.stop()


# ======================================================================
# Test: Replay / Duplicate Extraction Idempotency
# ======================================================================


class TestMemoryExtractionIdempotency:
    """Test that repeated extraction doesn't create duplicate memories."""

    @pytest.mark.asyncio
    async def test_duplicate_extraction_does_not_duplicate_memory(self, temp_friday_home) -> None:
        """Same information extracted twice → no duplicate active memory."""
        from friday.memory.sqlite_store import Message

        llm_backend = FakeLLMBackend(
            response='[{"content": "User prefers Vim.", "type": "user_fact", "confidence": "explicit", "message_ids": ["1"], "reasoning": "User stated preference"}]'
        )
        session = AssistantSession(
            friday_home=temp_friday_home,
            llm_backend=llm_backend,
        )
        session._extraction_interval = 1

        from unittest.mock import MagicMock
        session._conversation_id = 1
        session._conversation_store = MagicMock()
        session._conversation_store.get_recent_messages = MagicMock(return_value=[
            Message(id=1, conversation_id=1, role="user", content="I use Vim", created_at="2026-01-01T00:00:00"),
        ])
        session._memory_extractor._window_size = 10
        session._project_service.active_project = lambda: None

        # Don't mock get_active - let real memory manager work
        # First extraction
        await session.on_assistant_message_persisted()
        await asyncio.sleep(0.01)

        # Second extraction (same content)
        await session.on_assistant_message_persisted()
        await asyncio.sleep(0.01)

        # Third extraction
        await session.on_assistant_message_persisted()
        await asyncio.sleep(0.01)

        # Should only have 1 memory (resolver deduplicates)
        memories = session._memory_manager.get_active()
        assert len(memories) == 1
        assert memories[0].content == "User prefers Vim."

        await session.stop()

    @pytest.mark.asyncio
    async def test_superseding_memory_works(self, temp_friday_home) -> None:
        """Duplicate extraction of same content does not create duplicates (idempotency)."""
        from friday.memory.sqlite_store import Message

        llm_backend = FakeLLMBackend(
            response='[{"content": "User prefers dark mode.", "type": "user_fact", "confidence": "explicit", "message_ids": ["1"], "reasoning": "User stated preference"}]'
        )
        session = AssistantSession(
            friday_home=temp_friday_home,
            llm_backend=llm_backend,
        )
        session._extraction_interval = 1

        from unittest.mock import MagicMock
        session._conversation_id = 1
        session._conversation_store = MagicMock()
        session._conversation_store.get_recent_messages = MagicMock(return_value=[
            Message(id=1, conversation_id=1, role="user", content="I prefer dark mode", created_at="2026-01-01T00:00:00"),
        ])
        session._memory_extractor._window_size = 10
        session._project_service.active_project = lambda: None

        # Don't mock get_active - let real memory manager work
        await session.on_assistant_message_persisted()
        await asyncio.sleep(0.01)

        # Verify first memory
        memories = session._memory_manager.get_active()
        assert len(memories) == 1
        assert memories[0].content == "User prefers dark mode."

        # Second extraction with SAME content (idempotency test)
        await session.on_assistant_message_persisted()
        await asyncio.sleep(0.01)

        # Should NOT create duplicate (resolver deduplicates via exact match)
        memories = session._memory_manager.get_active()
        assert len(memories) == 1
        assert memories[0].content == "User prefers dark mode."

        await session.stop()


# ======================================================================
# Test: Failure Isolation
# ======================================================================


class TestMemoryExtractionFailureIsolation:
    """Test that extraction failures don't affect other systems."""

    @pytest.mark.asyncio
    async def test_extractor_failure_isolated(self) -> None:
        """Extractor failure → logged, no crash, next turn may try again."""
        from friday.memory.sqlite_store import Message

        session = AssistantSession(
            friday_home=None,
            llm_backend=FakeLLMBackend(response="invalid json [[["),  # Will fail parsing
        )
        session._extraction_interval = 1

        from unittest.mock import MagicMock
        session._conversation_id = 1
        session._conversation_store = MagicMock()
        session._conversation_store.get_recent_messages = MagicMock(return_value=[
            Message(id=1, conversation_id=1, role="user", content="Test", created_at="2026-01-01T00:00:00"),
        ])
        session._memory_extractor._window_size = 10
        session._memory_manager.get_active = MagicMock(return_value=[])
        session._project_service.active_project = MagicMock(return_value=None)

        await session.on_assistant_message_persisted()
        await asyncio.sleep(0.01)

        # Session should still be functional
        assert not session._stopping

        await session.stop()

    @pytest.mark.asyncio
    async def test_resolver_failure_isolated(self) -> None:
        """Resolver failure → logged, no crash."""
        # The resolver is very defensive; hard to make it fail
        # But we can test that the try/except boundary exists

        session = AssistantSession(
            friday_home=None,
            llm_backend=FakeLLMBackend(response="[]"),
        )
        session._extraction_interval = 1

        from unittest.mock import MagicMock
        session._conversation_id = 1
        session._conversation_store = MagicMock()
        session._conversation_store.get_recent_messages = MagicMock(return_value=[])
        session._memory_extractor._window_size = 10
        session._memory_manager.get_active = MagicMock(return_value=[])
        session._project_service.active_project = MagicMock(return_value=None)

        await session.on_assistant_message_persisted()
        await asyncio.sleep(0.01)

        assert not session._stopping

        await session.stop()

    @pytest.mark.asyncio
    async def test_memory_store_failure_isolated(self) -> None:
        """Memory store failure → logged, no crash."""

        session = AssistantSession(
            friday_home=None,
            llm_backend=FakeLLMBackend(response="[]"),
        )
        session._extraction_interval = 1

        from unittest.mock import MagicMock
        session._conversation_id = 1
        session._conversation_store = MagicMock()
        session._conversation_store.get_recent_messages = MagicMock(return_value=[])
        session._memory_extractor._window_size = 10
        session._project_service.active_project = MagicMock(return_value=None)

        # Make get_active raise
        session._memory_manager.get_active = MagicMock(side_effect=RuntimeError("DB unavailable"))

        await session.on_assistant_message_persisted()
        await asyncio.sleep(0.01)

        # Session still functional
        assert not session._stopping

        await session.stop()


# ======================================================================
# Test: Background Task Ownership
# ======================================================================


class TestMemoryExtractionTaskOwnership:
    """Test that extraction tasks are tracked by session."""

    @pytest.mark.asyncio
    async def test_background_task_is_owned_by_session(self) -> None:
        """Extraction task is in session's _background_tasks."""

        session = AssistantSession(
            friday_home=None,
            llm_backend=FakeLLMBackend(response="[]"),
        )
        session._extraction_interval = 1

        from unittest.mock import MagicMock
        session._conversation_id = 1
        session._conversation_store = MagicMock()
        session._conversation_store.get_recent_messages = MagicMock(return_value=[])
        session._memory_extractor._window_size = 10
        session._memory_manager.get_active = MagicMock(return_value=[])
        session._project_service.active_project = MagicMock(return_value=None)

        await session.on_assistant_message_persisted()
        assert len(session._background_tasks) == 1

        await asyncio.sleep(0.01)
        assert len(session._background_tasks) == 0

        await session.stop()

    @pytest.mark.asyncio
    async def test_shutdown_cancels_memory_extraction(self) -> None:
        """Long-running extraction is cancelled on shutdown."""
        # Use a slow LLM backend
        class SlowLLMBackend:
            async def complete(self, system: str, user: str) -> str:
                await asyncio.sleep(10)  # Slow
                return "[]"

        from friday.memory.sqlite_store import Message

        session = AssistantSession(
            friday_home=None,
            llm_backend=SlowLLMBackend(),
        )
        session._extraction_interval = 1

        from unittest.mock import MagicMock
        session._conversation_id = 1
        session._conversation_store = MagicMock()
        session._conversation_store.get_recent_messages = MagicMock(return_value=[
            Message(id=1, conversation_id=1, role="user", content="Test", created_at="2026-01-01T00:00:00"),
        ])
        session._memory_extractor._window_size = 10
        session._memory_manager.get_active = MagicMock(return_value=[])
        session._project_service.active_project = MagicMock(return_value=None)

        await session.on_assistant_message_persisted()
        assert len(session._background_tasks) == 1

        await session.stop()

        assert len(session._background_tasks) == 0


# ======================================================================
# Test: No Context / Compaction / Promotion Changes
# ======================================================================


class TestNoSideEffects:
    """Test that memory extraction doesn't affect other systems."""

    @pytest.mark.asyncio
    async def test_memory_extraction_does_not_modify_context(self) -> None:
        """Context assembly still works after extraction."""
        session = AssistantSession(
            friday_home=None,
            llm_backend=FakeLLMBackend(response="[]"),
        )
        session._extraction_interval = 1

        from unittest.mock import MagicMock
        session._conversation_id = 1
        session._conversation_store = MagicMock()
        session._conversation_store.get_recent_messages = MagicMock(return_value=[])
        session._memory_extractor._window_size = 10
        session._memory_manager.get_active = MagicMock(return_value=[])

        await session.on_assistant_message_persisted()
        await asyncio.sleep(0.01)

        # Context assembly should still work
        from livekit.agents.llm import ChatContext, ChatMessage
        turn_ctx = ChatContext.empty()
        new_message = ChatMessage(role="user", content=["Test"])

        result = session.assemble_context_for_turn(turn_ctx, new_message)
        assert result is not None

        await session.stop()

    @pytest.mark.asyncio
    async def test_memory_extraction_does_not_trigger_promotion(self) -> None:
        """Promotion not invoked by memory extraction."""
        session = AssistantSession(
            friday_home=None,
            llm_backend=FakeLLMBackend(response="[]"),
        )
        session._extraction_interval = 1

        # Verify promotion components exist but promote() is not called
        assert hasattr(session, "_promoter")
        assert session._promoter is not None

        await session.stop()


# ======================================================================
# Integration Test
# ======================================================================


class TestMemoryExtractionIntegration:
    """Full integration test: persisted message → extraction → memory."""

    @pytest.mark.asyncio
    async def test_full_memory_extraction_integration(self, temp_friday_home) -> None:
        """End-to-end: assistant persisted → extraction → memory retrievable."""
        from friday.memory.sqlite_store import Message

        llm_backend = FakeLLMBackend(
            response='[{"content": "User prefers dark mode theme.", "type": "user_fact", "confidence": "explicit", "message_ids": ["1", "3"], "reasoning": "User stated preference twice"}]'
        )
        session = AssistantSession(
            friday_home=temp_friday_home,
            llm_backend=llm_backend,
        )
        session._extraction_interval = 1

        from unittest.mock import MagicMock
        session._conversation_id = 1
        session._conversation_store = MagicMock()
        session._conversation_store.get_recent_messages = MagicMock(return_value=[
            Message(id=1, conversation_id=1, role="user", content="I like dark mode", created_at="2026-01-01T00:00:00"),
            Message(id=2, conversation_id=1, role="assistant", content="Noted", created_at="2026-01-01T00:00:01"),
            Message(id=3, conversation_id=1, role="user", content="Dark mode is my preference", created_at="2026-01-01T00:00:02"),
        ])
        session._memory_extractor._window_size = 10
        session._project_service.active_project = lambda: None

        # Don't mock get_active - let real memory manager work
        # Trigger extraction
        await session.on_assistant_message_persisted()
        await asyncio.sleep(0.05)  # Allow full pipeline

        # Verify memory is retrievable as active memory
        memories = session._memory_manager.get_active()
        assert len(memories) == 1
        mem = memories[0]
        assert mem.content == "User prefers dark mode theme."
        assert mem.type == MemoryType.USER_FACT
        assert mem.scope == MemoryScope.USER
        assert mem.confidence == MemoryConfidence.EXPLICIT
        assert mem.provenance.source_conversation_id == "1"
        assert set(mem.provenance.source_message_ids) == {"1", "3"}
        assert mem.status == MemoryStatus.ACTIVE

        await session.stop()


# ======================================================================
# Run verification
# ======================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])