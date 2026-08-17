"""Tests for context models: ContextBudget, unit estimation, ContextSnapshot."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from friday.context.models import (
    ContextBudget,
    ContextSnapshot,
    estimate_units,
)
from friday.memory.models import (
    Memory,
    MemoryConfidence,
    MemoryProvenance,
    MemoryScope,
    MemoryStatus,
    MemoryType,
)


class TestEstimateUnits:
    def test_empty_text_is_zero(self) -> None:
        assert estimate_units("") == 0

    def test_short_text_minimum_one(self) -> None:
        assert estimate_units("hi") == 1

    def test_four_chars_per_unit(self) -> None:
        assert estimate_units("abcd") == 1
        assert estimate_units("abcdefgh") == 2

    def test_rounds_up(self) -> None:
        assert estimate_units("abcde") == 2

    def test_whitespace_counts(self) -> None:
        assert estimate_units("a" * 7 + " " * 9) == 4


class TestContextBudget:
    def test_available_units(self) -> None:
        budget = ContextBudget(
            max_input_units=40000,
            reserved_output_units=8000,
            safety_margin=2000,
        )
        assert budget.available_units == 30000

    def test_available_units_never_below_one(self) -> None:
        budget = ContextBudget(
            max_input_units=10,
            reserved_output_units=100,
            safety_margin=100,
        )
        assert budget.available_units == 1

    def test_remaining_after(self) -> None:
        budget = ContextBudget(max_input_units=1000, reserved_output_units=200, safety_margin=100)
        assert budget.remaining_after(300) == 400

    def test_is_immutable(self) -> None:
        budget = ContextBudget(max_input_units=1000, reserved_output_units=200, safety_margin=100)
        with pytest.raises(FrozenInstanceError):
            budget.max_input_units = 9999  # type: ignore[misc]


def make_memory(content: str, memory_id: str) -> Memory:
    return Memory(
        id=memory_id,
        type=MemoryType.USER_FACT,
        scope=MemoryScope.USER,
        content=content,
        confidence=MemoryConfidence.EXPLICIT,
        provenance=MemoryProvenance(source_conversation_id="conv-1", source_message_ids=("m1",)),
        status=MemoryStatus.ACTIVE,
    )


class TestContextSnapshot:
    def _snapshot(self, **overrides) -> ContextSnapshot:
        defaults = {
            "system_instructions": "You are FRIDAY.",
            "current_user_message": "Tell me about the project.",
            "recent_messages": (("m1", "user", "Hello."), ("m2", "assistant", "Hi!")),
            "project_context": "context.md contents",
            "durable_memories": (make_memory("User uses Vim.", "mem-1"),),
            "compressed_history": None,
            "budget": ContextBudget(max_input_units=1000, reserved_output_units=200, safety_margin=100),
            "estimated_units": 50,
            "compressed": False,
        }
        defaults.update(overrides)
        return ContextSnapshot(**defaults)

    def test_fields(self) -> None:
        snapshot = self._snapshot()
        assert snapshot.system_instructions == "You are FRIDAY."
        assert snapshot.current_user_message == "Tell me about the project."
        assert snapshot.recent_messages == (("m1", "user", "Hello."), ("m2", "assistant", "Hi!"))
        assert snapshot.project_context == "context.md contents"
        assert snapshot.durable_memories[0].content == "User uses Vim."
        assert snapshot.compressed_history is None
        assert snapshot.estimated_units == 50

    def test_render_priority_order(self) -> None:
        snapshot = self._snapshot(
            compressed_history="Older conversation compressed.",
        )
        rendered = snapshot.render()

        positions = [
            rendered.index("You are FRIDAY."),
            rendered.index("Tell me about the project."),
            rendered.index("Hello."),
            rendered.index("context.md contents"),
            rendered.index("User uses Vim."),
            rendered.index("Older conversation compressed."),
        ]
        assert positions == sorted(positions)

    def test_render_skips_empty_sections(self) -> None:
        snapshot = self._snapshot(project_context=None, compressed_history=None)
        rendered = snapshot.render()
        assert "context.md" not in rendered
        assert "compressed" not in rendered

    def test_render_durable_memories_prefixed(self) -> None:
        snapshot = self._snapshot()
        assert "- User uses Vim." in snapshot.render()

    def test_is_immutable(self) -> None:
        snapshot = self._snapshot()
        with pytest.raises(FrozenInstanceError):
            snapshot.current_user_message = "changed"  # type: ignore[misc]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])