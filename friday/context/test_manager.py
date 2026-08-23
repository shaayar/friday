"""Tests for ContextManager assembly, budget enforcement, and failure isolation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from friday.context.manager import (
    ContextManager,
    ProjectContext,
)
from friday.context.models import (
    ContextBudget,
    ContextSnapshot,
)
from friday.memory.models import (
    Memory,
    MemoryConfidence,
    MemoryProvenance,
    MemoryScope,
    MemoryStatus,
    MemoryType,
)

NOW = datetime(2026, 8, 15, 12, 0, 0, tzinfo=UTC)


def make_memory(
    content: str,
    memory_id: str,
    *,
    scope: MemoryScope = MemoryScope.USER,
    confidence: MemoryConfidence = MemoryConfidence.EXPLICIT,
    created_at: datetime = NOW,
    status: MemoryStatus = MemoryStatus.ACTIVE,
    project_id: str | None = None,
) -> Memory:
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
        provenance=MemoryProvenance(
            source_conversation_id="conv-1", source_message_ids=("m1",)
        ),
        created_at=created_at,
        updated_at=created_at,
        valid_from=created_at,
        status=status,
        project_id=project_id,
    )


def message(message_id: str, role: str, content: str) -> tuple[str, str, str]:
    return (message_id, role, content)


class FakeMemoryProvider:
    """Returns active memories; honours the ACTIVE contract of get_active."""

    def __init__(self, memories: list[Memory] | None = None) -> None:
        self._memories = list(memories or [])
        self.raise_on_get_active = False
        self.calls = 0
        self.saves: list[Memory] = []

    def get_active(
        self, *, scope=None, project_id=None, valid_at=None, limit=100, offset=0
    ):
        self.calls += 1
        if self.raise_on_get_active:
            raise RuntimeError("memory store unavailable")
        result = [m for m in self._memories if m.status is MemoryStatus.ACTIVE]
        if scope is not None:
            result = [m for m in result if m.scope is scope]
        if project_id is not None:
            result = [m for m in result if m.project_id == project_id]
        return result[:limit] if limit is not None else result

    def save(self, memory: Memory) -> Memory:
        self.saves.append(memory)
        return memory


class FakeProjectProvider:
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


class FakeShrinker:
    def __init__(self, summary: str = "[compressed older history]") -> None:
        self._summary = summary
        self.raise_on_shrink = False
        self.calls = 0
        self.last_messages: list | None = None
        self.last_max_units: int | None = None

    def shrink(self, messages, *, max_units: int) -> str:
        self.calls += 1
        self.last_messages = list(messages)
        self.last_max_units = max_units
        if self.raise_on_shrink:
            raise RuntimeError("compression failed")
        return self._summary


def default_budget(
    *, max_input: int = 40_000, reserved: int = 8_000, safety: int = 2_000
) -> ContextBudget:
    return ContextBudget(
        max_input_units=max_input,
        reserved_output_units=reserved,
        safety_margin=safety,
    )


class TestBasicAssembly:
    def make_manager(self, **overrides) -> ContextManager:
        defaults = {
            "memory_manager": FakeMemoryProvider(),
            "budget": default_budget(),
        }
        defaults.update(overrides)
        return ContextManager(**defaults)

    def test_basic_assembly(self) -> None:
        memories = [
            make_memory("User uses Vim.", "mem-1"),
        ]
        manager = self.make_manager(memory_manager=FakeMemoryProvider(memories))
        snapshot = manager.assemble(
            system_instructions="You are FRIDAY.",
            current_user_message="What about vim?",
            recent_messages=[
                message("m1", "user", "Hello."),
                message("m2", "assistant", "Hi!"),
            ],
            _conversation_id="conv-1",
            active_project_id=None,
        )
        assert snapshot.system_instructions == "You are FRIDAY."
        assert snapshot.current_user_message == "What about vim?"
        assert snapshot.recent_messages == (
            ("m1", "user", "Hello."),
            ("m2", "assistant", "Hi!"),
        )
        assert snapshot.durable_memories == (memories[0],)
        assert snapshot.project_context is None
        assert snapshot.compressed_history is None
        assert snapshot.estimated_units > 0

    def test_source_ordering_in_render(self) -> None:
        memories = [make_memory("User uses Vim.", "mem-1")]
        manager = self.make_manager(
            memory_manager=FakeMemoryProvider(memories),
            project_context_provider=FakeProjectProvider(
                ProjectContext(context_md="Project context.md", state_json="{}")
            ),
        )
        snapshot = manager.assemble(
            system_instructions="SYSTEM",
            current_user_message="CURRENT",
            recent_messages=[message("m1", "user", "RECENT")],
            _conversation_id="conv-1",
            active_project_id="proj-1",
        )
        rendered = snapshot.render()
        positions = [
            rendered.index("SYSTEM"),
            rendered.index("CURRENT"),
            rendered.index("RECENT"),
            rendered.index("Project context.md"),
            rendered.index("User uses Vim."),
        ]
        assert positions == sorted(positions)

    def test_recent_turn_capping(self) -> None:
        manager = self.make_manager()
        messages = [
            message(f"m{i}", "user" if i % 2 else "assistant", f"msg {i}")
            for i in range(30)
        ]
        snapshot = manager.assemble(
            system_instructions="S",
            current_user_message="C",
            recent_messages=messages,
            _conversation_id="conv-1",
            active_project_id=None,
        )
        # recent_turns defaults to 10 -> last 20 messages.
        assert len(snapshot.recent_messages) == 20
        assert snapshot.recent_messages[0][0] == "m10"
        assert snapshot.recent_messages[-1][0] == "m29"
        # Order preserved.
        ids = [m[0] for m in snapshot.recent_messages]
        assert ids == sorted(ids)

    def test_conversation_id_accepted_without_snapshot_field(self) -> None:
        manager = self.make_manager()
        snapshot = manager.assemble(
            system_instructions="S",
            current_user_message=None,
            recent_messages=[],
            _conversation_id="conv-9",
            active_project_id=None,
        )
        assert isinstance(snapshot, ContextSnapshot)
        assert snapshot.current_user_message == ""


class TestMemoryRetrieval:
    def test_active_and_scope_respected(self) -> None:
        memories = [
            make_memory("User fact", "user-1"),
            make_memory(
                "Project fact", "proj-1", scope=MemoryScope.PROJECT, project_id="proj-1"
            ),
            make_memory(
                "Other project fact",
                "proj-2",
                scope=MemoryScope.PROJECT,
                project_id="proj-2",
            ),
            make_memory("Stale", "stale-1", status=MemoryStatus.INVALIDATED),
            make_memory("Superseded", "sup-1", status=MemoryStatus.SUPERSEDED),
        ]
        manager = ContextManager(
            memory_manager=FakeMemoryProvider(memories),
            budget=default_budget(),
        )
        snapshot = manager.assemble(
            system_instructions="S",
            current_user_message="C",
            recent_messages=[],
            _conversation_id="conv-1",
            active_project_id="proj-1",
        )
        contents = {m.content for m in snapshot.durable_memories}
        assert contents == {"User fact", "Project fact"}

    def test_memory_cap(self) -> None:
        memories = [make_memory(f"User fact {i}", f"mem-{i}") for i in range(15)]
        manager = ContextManager(
            memory_manager=FakeMemoryProvider(memories),
            budget=default_budget(),
            memory_cap=10,
        )
        snapshot = manager.assemble(
            system_instructions="S",
            current_user_message="C",
            recent_messages=[],
            _conversation_id="conv-1",
            active_project_id=None,
        )
        assert len(snapshot.durable_memories) == 10

    def test_lexical_relevance_ordering(self) -> None:
        memories = [
            make_memory(
                "User uses Neovim.", "neovim", created_at=NOW + timedelta(hours=2)
            ),
            make_memory("User uses Vim.", "vim", created_at=NOW),
            make_memory(
                "User likes sushi.", "sushi", created_at=NOW + timedelta(hours=3)
            ),
        ]
        manager = ContextManager(
            memory_manager=FakeMemoryProvider(memories),
            budget=default_budget(),
        )
        snapshot = manager.assemble(
            system_instructions="S",
            current_user_message="Which editor works best for vim config?",
            recent_messages=[],
            _conversation_id="conv-1",
            active_project_id=None,
        )
        ordered = [m.id for m in snapshot.durable_memories]
        assert ordered == ["vim", "sushi", "neovim"]

    def test_confidence_ordering(self) -> None:
        memories = [
            make_memory(
                "User prefers vim plugins.",
                "inferred",
                confidence=MemoryConfidence.INFERRED,
                created_at=NOW + timedelta(hours=1),
            ),
            make_memory(
                "User uses vim daily.",
                "explicit",
                confidence=MemoryConfidence.EXPLICIT,
                created_at=NOW,
            ),
        ]
        manager = ContextManager(
            memory_manager=FakeMemoryProvider(memories),
            budget=default_budget(),
        )
        snapshot = manager.assemble(
            system_instructions="S",
            current_user_message="vim usage",
            recent_messages=[],
            _conversation_id="conv-1",
            active_project_id=None,
        )
        ordered = [m.id for m in snapshot.durable_memories]
        assert ordered == ["explicit", "inferred"]

    def test_recency_ordering(self) -> None:
        memories = [
            make_memory("User uses vim.", "older", created_at=NOW - timedelta(days=3)),
            make_memory("User uses vim.", "newer", created_at=NOW),
        ]
        manager = ContextManager(
            memory_manager=FakeMemoryProvider(memories),
            budget=default_budget(),
        )
        snapshot = manager.assemble(
            system_instructions="S",
            current_user_message="vim",
            recent_messages=[],
            _conversation_id="conv-1",
            active_project_id=None,
        )
        ordered = [m.id for m in snapshot.durable_memories]
        assert ordered == ["newer", "older"]

    def test_empty_memory_store(self) -> None:
        manager = ContextManager(
            memory_manager=FakeMemoryProvider([]),
            budget=default_budget(),
        )
        snapshot = manager.assemble(
            system_instructions="S",
            current_user_message="C",
            recent_messages=[],
            _conversation_id="conv-1",
            active_project_id=None,
        )
        assert snapshot.durable_memories == ()

    def test_memory_retrieval_failure(self) -> None:
        provider = FakeMemoryProvider([make_memory("User fact", "mem-1")])
        provider.raise_on_get_active = True
        manager = ContextManager(memory_manager=provider, budget=default_budget())
        snapshot = manager.assemble(
            system_instructions="S",
            current_user_message="C",
            recent_messages=[message("m1", "user", "hello")],
            _conversation_id="conv-1",
            active_project_id=None,
        )
        assert snapshot.durable_memories == ()
        assert snapshot.system_instructions == "S"
        assert snapshot.current_user_message == "C"


class TestProjectContext:
    def make_manager(self, provider) -> ContextManager:
        return ContextManager(
            memory_manager=FakeMemoryProvider(),
            project_context_provider=provider,
            budget=default_budget(),
        )

    def test_project_context_inclusion(self) -> None:
        provider = FakeProjectProvider(
            ProjectContext(
                context_md="Project context.md",
                state_json='{"name": "PostLeaf"}',
                facts_md="Facts line",
                decisions_md="Decision line",
            )
        )
        manager = self.make_manager(provider)
        snapshot = manager.assemble(
            system_instructions="S",
            current_user_message="C",
            recent_messages=[],
            _conversation_id="conv-1",
            active_project_id="proj-1",
        )
        assert snapshot.project_context is not None
        assert "Project context.md" in snapshot.project_context
        assert "PostLeaf" in snapshot.project_context
        assert "Facts line" in snapshot.project_context
        assert "Decision line" in snapshot.project_context
        assert provider.last_project_id == "proj-1"

    def test_no_active_project_returns_none(self) -> None:
        provider = FakeProjectProvider(ProjectContext(context_md="Context"))
        manager = self.make_manager(provider)
        snapshot = manager.assemble(
            system_instructions="S",
            current_user_message="C",
            recent_messages=[],
            _conversation_id="conv-1",
            active_project_id=None,
        )
        assert snapshot.project_context is None
        assert provider.calls == 0

    def test_no_provider_returns_none(self) -> None:
        manager = ContextManager(
            memory_manager=FakeMemoryProvider(),
            project_context_provider=None,
            budget=default_budget(),
        )
        snapshot = manager.assemble(
            system_instructions="S",
            current_user_message="C",
            recent_messages=[],
            _conversation_id="conv-1",
            active_project_id="proj-1",
        )
        assert snapshot.project_context is None

    def test_provider_none_result_returns_none(self) -> None:
        manager = self.make_manager(FakeProjectProvider(None))
        snapshot = manager.assemble(
            system_instructions="S",
            current_user_message="C",
            recent_messages=[],
            _conversation_id="conv-1",
            active_project_id="proj-1",
        )
        assert snapshot.project_context is None

    def test_project_context_failure_returns_none(self) -> None:
        provider = FakeProjectProvider(ProjectContext(context_md="Context"))
        provider.raise_on_get_context = True
        manager = self.make_manager(provider)
        snapshot = manager.assemble(
            system_instructions="S",
            current_user_message="C",
            recent_messages=[message("m1", "user", "hello")],
            _conversation_id="conv-1",
            active_project_id="proj-1",
        )
        assert snapshot.project_context is None
        assert snapshot.system_instructions == "S"

    def test_project_context_cap_drops_optional_sections(self) -> None:
        provider = FakeProjectProvider(
            ProjectContext(
                context_md="CONTEXT",
                state_json="STATE",
                facts_md="F" * 100,
                decisions_md="D" * 100,
            )
        )
        manager = ContextManager(
            memory_manager=FakeMemoryProvider(),
            project_context_provider=provider,
            budget=default_budget(),
            project_context_cap_units=20,
        )
        snapshot = manager.assemble(
            system_instructions="S",
            current_user_message="C",
            recent_messages=[],
            _conversation_id="conv-1",
            active_project_id="proj-1",
        )
        # context.md and state.json are always kept; facts/decisions dropped.
        assert snapshot.project_context is not None
        assert "CONTEXT" in snapshot.project_context
        assert "STATE" in snapshot.project_context
        assert "F" * 100 not in snapshot.project_context


class TestBudgetAndShrinking:
    def make_manager(
        self, *, budget, shrinker=None, memories=None, recent_turns=10
    ) -> ContextManager:
        return ContextManager(
            memory_manager=FakeMemoryProvider(memories or []),
            project_context_provider=None,
            shrinker=shrinker,
            budget=budget,
            recent_turns=recent_turns,
        )

    def test_within_budget_no_shrinker(self) -> None:
        shrinker = FakeShrinker()
        manager = self.make_manager(budget=default_budget(), shrinker=shrinker)
        snapshot = manager.assemble(
            system_instructions="S",
            current_user_message="C",
            recent_messages=[message("m1", "user", "hello")],
            _conversation_id="conv-1",
            active_project_id=None,
        )
        assert shrinker.calls == 0
        assert snapshot.compressed_history is None
        assert snapshot.compressed is False
        assert snapshot.estimated_units <= snapshot.budget.available_units

    def test_budget_overflow_reduces_lowest_priority(self) -> None:
        budget = ContextBudget(
            max_input_units=10, reserved_output_units=0, safety_margin=0
        )
        manager = self.make_manager(budget=budget, recent_turns=2)
        messages = [message(f"m{i}", "user", "x" * 30) for i in range(8)]
        snapshot = manager.assemble(
            system_instructions="S",
            current_user_message="C",
            recent_messages=messages,
            _conversation_id="conv-1",
            active_project_id=None,
        )
        assert snapshot.estimated_units <= budget.available_units
        assert snapshot.system_instructions == "S"
        assert snapshot.current_user_message == "C"
        # Oldest recent messages are trimmed first; the newest remain.
        assert len(snapshot.recent_messages) < len(messages)

    def test_shrinker_invoked_only_when_required(self) -> None:
        budget = ContextBudget(
            max_input_units=10, reserved_output_units=0, safety_margin=0
        )
        shrinker = FakeShrinker()
        manager = self.make_manager(budget=budget, shrinker=shrinker, recent_turns=2)
        messages = [message(f"m{i}", "user", "x" * 30) for i in range(8)]
        manager.assemble(
            system_instructions="S",
            current_user_message="C",
            recent_messages=messages,
            _conversation_id="conv-1",
            active_project_id=None,
        )
        assert shrinker.calls == 1

    def test_shrinker_failure_degrades(self) -> None:
        budget = ContextBudget(
            max_input_units=10, reserved_output_units=0, safety_margin=0
        )
        shrinker = FakeShrinker()
        shrinker.raise_on_shrink = True
        manager = self.make_manager(budget=budget, shrinker=shrinker, recent_turns=2)
        messages = [message(f"m{i}", "user", "x" * 30) for i in range(8)]
        snapshot = manager.assemble(
            system_instructions="S",
            current_user_message="C",
            recent_messages=messages,
            _conversation_id="conv-1",
            active_project_id=None,
        )
        assert snapshot.compressed_history is None
        assert snapshot.system_instructions == "S"
        assert snapshot.current_user_message == "C"

    def test_system_and_current_never_removed(self) -> None:
        budget = ContextBudget(
            max_input_units=2, reserved_output_units=0, safety_margin=0
        )
        manager = self.make_manager(budget=budget)
        snapshot = manager.assemble(
            system_instructions="SYSTEM",
            current_user_message="CURRENT",
            recent_messages=[message("m1", "user", "x" * 50)],
            _conversation_id="conv-1",
            active_project_id=None,
        )
        assert snapshot.system_instructions == "SYSTEM"
        assert snapshot.current_user_message == "CURRENT"

    def test_compressed_history_uses_older_messages(self) -> None:
        budget = ContextBudget(
            max_input_units=8, reserved_output_units=0, safety_margin=0
        )
        shrinker = FakeShrinker(summary="SUMMARY")
        manager = self.make_manager(budget=budget, shrinker=shrinker, recent_turns=2)
        messages = [message(f"m{i}", "user", "x" * 30) for i in range(8)]
        snapshot = manager.assemble(
            system_instructions="S",
            current_user_message="C",
            recent_messages=messages,
            _conversation_id="conv-1",
            active_project_id=None,
        )
        # recent window = last 4; older = first 4 -> shrinker got the older block.
        assert shrinker.calls == 1
        assert [m[0] for m in shrinker.last_messages] == ["m0", "m1", "m2", "m3"]
        assert snapshot.compressed_history == "SUMMARY"
        assert snapshot.compressed is True
        assert "SUMMARY" in snapshot.render()

    def test_no_persistence_of_compressed_context(self) -> None:
        budget = ContextBudget(
            max_input_units=8, reserved_output_units=0, safety_margin=0
        )
        memory_provider = FakeMemoryProvider([make_memory("User fact", "mem-1")])
        shrinker = FakeShrinker(summary="SUMMARY")
        manager = ContextManager(
            memory_manager=memory_provider,
            shrinker=shrinker,
            budget=budget,
            recent_turns=2,
        )
        messages = [message(f"m{i}", "user", "x" * 30) for i in range(8)]
        snapshot = manager.assemble(
            system_instructions="S",
            current_user_message="C",
            recent_messages=messages,
            _conversation_id="conv-1",
            active_project_id=None,
        )
        assert snapshot.compressed_history == "SUMMARY"
        assert memory_provider.saves == []
        assert shrinker.last_max_units is not None and shrinker.last_max_units >= 0

    def test_recent_messages_preserved_verbatim(self) -> None:
        budget = ContextBudget(
            max_input_units=12, reserved_output_units=0, safety_margin=0
        )
        shrinker = FakeShrinker(summary="SUMMARY")
        manager = self.make_manager(budget=budget, shrinker=shrinker, recent_turns=2)
        messages = [message(f"m{i}", "user", "x" * 30) for i in range(8)]
        snapshot = manager.assemble(
            system_instructions="S",
            current_user_message="C",
            recent_messages=messages,
            _conversation_id="conv-1",
            active_project_id=None,
        )
        # Some recent messages survive, verbatim and in order.
        assert snapshot.recent_messages
        ids = [m[0] for m in snapshot.recent_messages]
        assert ids == sorted(ids)
        assert all(m[1] == "user" for m in snapshot.recent_messages)


class TestTinyBudgetImportantScenario:
    """The explicitly requested important test."""

    def test_tiny_budget_long_conversation(self) -> None:
        # Budget is small enough that the recent window fits only after the
        # older window is compressed into the leftover space.
        budget = ContextBudget(
            max_input_units=20, reserved_output_units=0, safety_margin=0
        )
        shrinker = FakeShrinker(summary="OLDER SUMMARY")
        raw_conversation = [message(f"m{i}", "user", "y" * 4) for i in range(8)]
        original = list(raw_conversation)
        manager = ContextManager(
            memory_manager=FakeMemoryProvider([]),
            shrinker=shrinker,
            budget=budget,
            recent_turns=2,
        )
        snapshot = manager.assemble(
            system_instructions="SYSTEM",
            current_user_message="CURRENT",
            recent_messages=raw_conversation,
            _conversation_id="conv-1",
            active_project_id=None,
        )

        # system instructions survive
        assert snapshot.system_instructions == "SYSTEM"
        # current user message survives
        assert snapshot.current_user_message == "CURRENT"
        # recent messages preserved verbatim as much as possible (all fit here)
        assert snapshot.recent_messages == tuple(original[-4:])
        assert all(m in original for m in snapshot.recent_messages)
        # older history is the part that gets compressed
        assert snapshot.compressed_history == "OLDER SUMMARY"
        assert shrinker.calls == 1
        # raw conversation remains untouched
        assert raw_conversation == original
        # the compressed result is in the snapshot but persisted nowhere
        assert "OLDER SUMMARY" in snapshot.render()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
