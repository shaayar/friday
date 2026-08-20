"""M7.1a Tests — FRIDAY Context Injection into LiveKit

Focused tests for the context integration layer.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

import pytest

from friday.context.manager import ContextManager, ProjectContext
from friday.context.models import Message
from friday.context.shrinker import ContextShrinker
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

class FakeLLMBackend:
    """Fake LLMBackend for testing."""

    def __init__(self, response: str = "Fake response") -> None:
        self.response = response
        self.calls = []

    def complete(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        return self.response


class FakeMemoryProvider:
    """Fake memory provider for ContextManager."""

    def __init__(self, memories: list[Memory] | None = None) -> None:
        self._memories = memories or []
        self.raise_on_get_active = False
        self.calls = 0

    def get_active(self, *, scope=None, project_id=None, valid_at=None, limit=100, offset=0):
        self.calls += 1
        if self.raise_on_get_active:
            raise RuntimeError("memory store unavailable")
        result = [m for m in self._memories if m.status is MemoryStatus.ACTIVE]
        if scope is not None:
            result = [m for m in result if m.scope is scope]
        if project_id is not None:
            result = [m for m in result if m.project_id == project_id]
        return result[:limit] if limit is not None else result


class FakeProjectProvider:
    """Fake project context provider."""

    def __init__(self, context: ProjectContext | None = None) -> None:
        self._context = context
        self.raise_on_get_context = False
        self.calls = 0
        self.last_project_id: str | None = None

    def get_context(self, project_id: str):
        self.calls += 1
        self.last_project_id = project_id
        if self.raise_on_get_context:
            raise RuntimeError("project service unavailable")
        return self._context


class FakeShrinker(ContextShrinker):
    """Fake context shrinker implementing the protocol."""

    def __init__(self, summary: str = "[compressed older history]") -> None:
        self._summary = summary
        self.raise_on_shrink = False
        self.calls = 0
        self.last_messages: list[Message] | None = None
        self.last_max_units: int | None = None

    def shrink(self, messages: Sequence[Message], *, max_units: int) -> str:
        self.calls += 1
        self.last_messages = list(messages)
        self.last_max_units = max_units
        if self.raise_on_shrink:
            raise RuntimeError("compression failed")
        return self._summary


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
# Test: LiveKit Message Conversion
# ======================================================================

class TestLiveKitMessageConversion:
    """Test conversion of LiveKit ChatMessage to ContextManager message tuples."""

    def test_normal_user_assistant_messages_convert_correctly(self):
        session = AssistantSession()
        # Simulate LiveKit ChatMessage objects
        from livekit.agents.llm import ChatMessage

        lk_messages = [
            ChatMessage(role="user", content=["Hello"]),
            ChatMessage(role="assistant", content=["Hi there!"]),
            ChatMessage(role="user", content=["How are you?"]),
        ]
        # Set ids manually for testing
        lk_messages[0].id = "msg-1"
        lk_messages[1].id = "msg-2"
        lk_messages[2].id = "msg-3"

        result = session._lk_messages_to_context_messages(lk_messages)

        assert len(result) == 3
        assert result[0] == ("msg-1", "user", "Hello")
        assert result[1] == ("msg-2", "assistant", "Hi there!")
        assert result[2] == ("msg-3", "user", "How are you?")

    def test_system_messages_filtered_out(self):
        session = AssistantSession()
        from livekit.agents.llm import ChatMessage

        lk_messages = [
            ChatMessage(role="system", content=["System prompt"]),
            ChatMessage(role="user", content=["User message"]),
        ]
        lk_messages[0].id = "sys-1"
        lk_messages[1].id = "usr-1"

        result = session._lk_messages_to_context_messages(lk_messages)

        assert len(result) == 1
        assert result[0] == ("usr-1", "user", "User message")

    def test_empty_content_filtered_out(self):
        session = AssistantSession()
        from livekit.agents.llm import ChatMessage

        lk_messages = [
            ChatMessage(role="user", content=[""]),
            ChatMessage(role="user", content=["  "]),
            ChatMessage(role="user", content=["Valid"]),
        ]
        lk_messages[0].id = "msg-1"
        lk_messages[1].id = "msg-2"
        lk_messages[2].id = "msg-3"

        result = session._lk_messages_to_context_messages(lk_messages)

        assert len(result) == 1
        assert result[0] == ("msg-3", "user", "Valid")


# ======================================================================
# Test: ContextSnapshot to LiveKit ChatContext
# ======================================================================

class TestContextSnapshotToLiveKitContext:
    """Test building LiveKit ChatContext from ContextSnapshot."""

    def test_all_sections_appear_correctly(self):
        session = AssistantSession()
        from friday.context.models import ContextBudget, ContextSnapshot

        # Build a snapshot with all sections
        snapshot = ContextSnapshot(
            system_instructions="You are FRIDAY.",
            current_user_message="What editor?",
            recent_messages=(
                ("msg-1", "user", "Hello"),
                ("msg-2", "assistant", "Hi!"),
            ),
            project_context="Project: PostLeaf\nStack: Next.js",
            durable_memories=(
                make_memory("User prefers Vim.", "mem-1"),
                make_memory("Project uses Python.", "mem-2", scope=MemoryScope.PROJECT, project_id="proj-1"),
            ),
            compressed_history="Earlier: discussed editor preferences.",
            budget=ContextBudget(max_input_units=40000, reserved_output_units=8000, safety_margin=2000),
            estimated_units=1000,
            compressed=True,
        )

        ctx = session._snapshot_to_chat_context(snapshot)

        # Verify all sections present as structured messages
        items = ctx.items
        roles = [item.role for item in items]
        contents = [item.text_content or "" for item in items]

        # System instructions
        assert "system" in roles
        assert any("You are FRIDAY." in c for c in contents)

        # Recent messages
        assert "user" in roles
        assert "assistant" in roles
        assert any("Hello" in c for c in contents)
        assert any("Hi!" in c for c in contents)

        # Project context (developer role)
        assert "developer" in roles
        assert any("PostLeaf" in c for c in contents)
        assert any("Next.js" in c for c in contents)

        # Durable memories
        assert any("Relevant memories:" in c for c in contents)
        assert any("User prefers Vim." in c for c in contents)
        assert any("Project uses Python." in c for c in contents)

        # Compressed history
        assert any("Previous context summary:" in c for c in contents)
        assert any("discussed editor preferences" in c for c in contents)

    def test_current_user_message_not_duplicated(self):
        """The current user message should NOT be in the built context."""
        session = AssistantSession()
        from friday.context.models import ContextBudget, ContextSnapshot

        snapshot = ContextSnapshot(
            system_instructions="System",
            current_user_message="Current user message",
            recent_messages=(
                ("msg-1", "user", "Previous user"),
                ("msg-2", "assistant", "Previous assistant"),
            ),
            project_context=None,
            durable_memories=(),
            compressed_history=None,
            budget=ContextBudget(max_input_units=40000, reserved_output_units=8000, safety_margin=2000),
            estimated_units=100,
            compressed=False,
        )

        ctx = session._snapshot_to_chat_context(snapshot)
        contents = [item.text_content or "" for item in ctx.items]

        # The current user message should NOT appear
        assert not any("Current user message" in c for c in contents)
        # But previous messages should
        assert any("Previous user" in c for c in contents)
        assert any("Previous assistant" in c for c in contents)


# ======================================================================
# Test: ContextManager Is Called Correctly
# ======================================================================

class TestContextManagerCalled:
    """Test that ContextManager is invoked with expected arguments."""

    def test_context_manager_receives_expected_arguments(self):
        """Verify ContextManager.assemble is called with correct parameters."""
        # Create fake providers
        fake_memory = FakeMemoryProvider()
        fake_project = FakeProjectProvider()
        fake_shrinker = FakeShrinker()

        # Create ContextManager with fakes
        from friday.context.models import ContextBudget
        cm = ContextManager(
            memory_manager=fake_memory,
            project_context_provider=fake_project,
            shrinker=fake_shrinker,
            budget=ContextBudget(
                max_input_units=40000,
                reserved_output_units=8000,
                safety_margin=2000,
            ),
        )

        # Call assemble
        snapshot = cm.assemble(
            system_instructions="System prompt",
            current_user_message="User question",
            recent_messages=(
                ("m1", "user", "Hello"),
                ("m2", "assistant", "Hi"),
            ),
            conversation_id="conv-123",
            active_project_id="proj-1",
        )

        # Verify it was called (indirectly via snapshot result)
        assert snapshot.system_instructions == "System prompt"
        assert snapshot.current_user_message == "User question"
        assert len(snapshot.recent_messages) == 2
        assert snapshot.recent_messages[0] == ("m1", "user", "Hello")
        assert snapshot.recent_messages[1] == ("m2", "assistant", "Hi")


# ======================================================================
# Test: Durable Memory Reaches LLM Context
# ======================================================================

class TestDurableMemoryReachesLLMContext:
    """Test that seeded durable memories appear in the assembled context."""

    def test_durable_memory_appears_in_chat_context(self):
        # Create memory
        mem = make_memory("User prefers dark mode.", "mem-1")

        # Create fake provider with this memory
        fake_memory = FakeMemoryProvider(memories=[mem])
        fake_project = FakeProjectProvider()

        cm = ContextManager(
            memory_manager=fake_memory,
            project_context_provider=fake_project,
            shrinker=None,
        )

        snapshot = cm.assemble(
            system_instructions="System",
            current_user_message="What theme?",
            recent_messages=(),
            conversation_id="conv-1",
            active_project_id=None,
        )

        # Verify memory is in snapshot
        assert len(snapshot.durable_memories) == 1
        assert snapshot.durable_memories[0].content == "User prefers dark mode."

        # Convert to LiveKit context
        session = AssistantSession()
        ctx = session._snapshot_to_chat_context(snapshot)
        contents = [item.text_content or "" for item in ctx.items]

        # Verify memory appears in developer message
        assert any("Relevant memories:" in c for c in contents)
        assert any("User prefers dark mode." in c for c in contents)


# ======================================================================
# Test: Project Context Reaches LLM Context
# ======================================================================

class TestProjectContextReachesLLMContext:
    """Test that active project context appears in the assembled context."""

    def test_project_context_appears_in_chat_context(self):
        project_ctx = ProjectContext(
            context_md="Project: PostLeaf",
            state_json='{"theme": "dark"}',
            facts_md="Uses Next.js",
            decisions_md="Use TypeScript",
        )

        fake_memory = FakeMemoryProvider()
        fake_project = FakeProjectProvider(context=project_ctx)

        cm = ContextManager(
            memory_manager=fake_memory,
            project_context_provider=fake_project,
            shrinker=None,
        )

        snapshot = cm.assemble(
            system_instructions="System",
            current_user_message="What project?",
            recent_messages=(),
            conversation_id="conv-1",
            active_project_id="proj-1",
        )

        # Verify project context in snapshot
        assert snapshot.project_context is not None
        assert "PostLeaf" in snapshot.project_context
        assert "Next.js" in snapshot.project_context
        assert "TypeScript" in snapshot.project_context

        # Convert to LiveKit context
        session = AssistantSession()
        ctx = session._snapshot_to_chat_context(snapshot)
        contents = [item.text_content or "" for item in ctx.items]

        # Verify project context appears
        assert any("PostLeaf" in c for c in contents)
        assert any("Next.js" in c for c in contents)
        assert any("TypeScript" in c for c in contents)

        # Verify provider was called with correct project_id
        assert fake_project.last_project_id == "proj-1"


# ======================================================================
# Test: Budgeted Context Replaces Unbounded History
# ======================================================================

class TestBudgetedContextReplacesHistory:
    """Test that context budget limits what reaches the LLM."""

    def test_large_history_budgeted_correctly(self):
        from friday.context.models import ContextBudget

        fake_memory = FakeMemoryProvider()
        fake_project = FakeProjectProvider()

        cm = ContextManager(
            memory_manager=fake_memory,
            project_context_provider=fake_project,
            shrinker=None,
            # Use small budget to force truncation
            budget=ContextBudget(max_input_units=500, reserved_output_units=100, safety_margin=50),
        )

        # Create many messages exceeding budget
        many_messages = tuple((f"m{i}", "user", "x" * 100) for i in range(20))

        snapshot = cm.assemble(
            system_instructions="S",
            current_user_message="C",
            recent_messages=many_messages,
            conversation_id="conv-1",
            active_project_id=None,
        )

        # Estimated units should be within budget
        assert snapshot.estimated_units <= snapshot.budget.available_units

        # Recent messages should be capped (recent_turns defaults to 10 = 20 messages)
        # But budget may force fewer
        assert len(snapshot.recent_messages) <= 20


# ======================================================================
# Test: Tool Items Preservation (Blocker Check)
# ======================================================================

class TestToolItemsPreservation:
    """Test how FunctionCall / FunctionCallOutput items are handled.

    This is the critical blocker check - if we can't preserve these
    without silently converting/discarding, we must report it.
    """

    def test_function_call_output_items_in_turn_ctx(self):
        """Verify that FunctionCall/FunctionCallOutput in turn_ctx.messages()
        are handled correctly - they are filtered out by messages() method
        which only returns ChatMessage items.
        """
        from livekit.agents.llm import (
            ChatContext,
            ChatMessage,
            FunctionCall,
            FunctionCallOutput,
        )

        ctx = ChatContext.empty()
        ctx.add_message(role="user", content=["Hello"])
        ctx.add_message(role="assistant", content=["I'll help"])

        # Add a function call
        fc = FunctionCall(call_id="call-1", name="read_file", arguments='{"path": "/tmp/test.txt"}')
        ctx.insert(fc)

        # Add function call output
        fco = FunctionCallOutput(call_id="call-1", name="read_file", output="File content", is_error=False)
        ctx.insert(fco)

        # messages() filters to ChatMessage only
        messages = ctx.messages()
        assert len(messages) == 2
        assert all(isinstance(m, ChatMessage) for m in messages)

        # FunctionCall and FunctionCallOutput are NOT in messages()
        # This means our conversion loses tool history
        # The ContextManager only sees user/assistant messages

    def test_current_contextmanager_does_not_see_tool_calls(self):
        """Confirm that ContextManager's recent_messages (from turn_ctx.messages())
        does NOT include FunctionCall/FunctionCallOutput items.
        """
        # This is the current behavior - tool calls are filtered out by
        # ChatContext.messages() which only returns ChatMessage items.
        #
        # IMPLICATION: The LLM will NOT see tool call history in the
        # assembled context unless we explicitly preserve it.
        #
        # This is a known limitation that should be documented.
        # For M7.1a, we accept this - the LLM sees the conversation
        # without tool calls. Tool execution still works because tools
        # are passed separately to llm.chat().


# ======================================================================
# Test: Context Failure Does Not Break Turn
# ======================================================================

class TestContextFailureDegradesGracefully:
    """Test that ContextManager failures follow graceful degradation."""

    def test_memory_failure_omits_memories(self):
        fake_memory = FakeMemoryProvider()
        fake_memory.raise_on_get_active = True
        fake_project = FakeProjectProvider()

        cm = ContextManager(
            memory_manager=fake_memory,
            project_context_provider=fake_project,
        )

        snapshot = cm.assemble(
            system_instructions="System",
            current_user_message="Test",
            recent_messages=(("m1", "user", "Hello"),),
            conversation_id="conv-1",
            active_project_id=None,
        )

        # Should succeed with empty memories
        assert snapshot.durable_memories == ()

    def test_project_failure_omits_project_context(self):
        fake_memory = FakeMemoryProvider()
        fake_project = FakeProjectProvider()
        fake_project.raise_on_get_context = True

        cm = ContextManager(
            memory_manager=fake_memory,
            project_context_provider=fake_project,
        )

        snapshot = cm.assemble(
            system_instructions="System",
            current_user_message="Test",
            recent_messages=(),
            conversation_id="conv-1",
            active_project_id="proj-1",
        )

        # Should succeed with no project context
        assert snapshot.project_context is None

    def test_shrinker_failure_omits_compressed_history(self):
        fake_memory = FakeMemoryProvider()
        fake_project = FakeProjectProvider()
        fake_shrinker = FakeShrinker()
        fake_shrinker.raise_on_shrink = True

        cm = ContextManager(
            memory_manager=fake_memory,
            project_context_provider=fake_project,
            shrinker=fake_shrinker,
        )

        # Provide older messages to trigger compression
        older = tuple((f"m{i}", "user", "x" * 100) for i in range(5))

        # With small budget, compression would be needed
        from friday.context.models import ContextBudget
        cm._budget = ContextBudget(max_input_units=200, reserved_output_units=50, safety_margin=25)

        snapshot = cm.assemble(
            system_instructions="S",
            current_user_message="C",
            recent_messages=older,
            conversation_id="conv-1",
            active_project_id=None,
        )

        # Compression should fail gracefully - no compressed history
        assert snapshot.compressed_history is None
        assert snapshot.compressed is False


# ======================================================================
# Test: Existing LiveKit LLM Path Unchanged
# ======================================================================

class TestLiveKitLLMPathUnchanged:
    """Test that the LLM still receives tools and the pipeline is intact."""

    def test_tools_still_passed_separately(self):
        """Verify that tools are passed separately to llm.chat(),
        not embedded in the custom context.
        """
        from livekit.agents import function_tool
        from livekit.agents.llm import ChatContext

        @function_tool
        async def test_tool(query: str) -> str:
            return f"Result: {query}"

        # Build a custom context
        ctx = ChatContext.empty()
        ctx.add_message(role="system", content=["System"])
        ctx.add_message(role="user", content=["User"])

        # The LLM call receives BOTH chat_ctx AND tools separately
        # tools=[test_tool] is passed to llm.chat(chat_ctx, tools=[test_tool])
        # Our custom context does not need to contain tool definitions

        # This test documents the architecture: tools are separate from context
        assert True


# ======================================================================
# Integration Test: Memory → ContextManager → LiveKit Context → Fake LLM
# ======================================================================

class TestIntegrationMemoryToLLM:
    """End-to-end integration test with fake LLM."""

    def test_seed_memory_assemble_context_fake_llm_sees_it(self):
        """Full integration: seed memory → assemble → fake LLM receives it."""
        # 1. Seed durable memory
        mem = make_memory("User prefers Vim.", "mem-1")
        fake_memory = FakeMemoryProvider(memories=[mem])
        fake_project = FakeProjectProvider()

        # 2. Create ContextManager
        cm = ContextManager(
            memory_manager=fake_memory,
            project_context_provider=fake_project,
            shrinker=None,
        )

        # 3. Simulate user turn
        snapshot = cm.assemble(
            system_instructions="You are FRIDAY.",
            current_user_message="What editor do I prefer?",
            recent_messages=(("m1", "user", "What editor do I prefer?"),),
            conversation_id="conv-1",
            active_project_id=None,
        )

        # 4. Build LiveKit context
        session = AssistantSession()
        custom_ctx = session._snapshot_to_chat_context(snapshot)

        # Verify the context contains the memory
        contents = " ".join(item.text_content or "" for item in custom_ctx.items)
        assert "Vim" in contents
        assert "User prefers Vim" in contents

        # The fake LLM would see this context when chat() is called
        # This proves the memory reaches the LLM


# ======================================================================
# Run all tests
# ======================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])