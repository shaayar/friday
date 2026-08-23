"""Context assembly models.

``ContextBudget`` bounds how much may be placed into the model context.
``estimate_units`` is the conservative character-based unit estimate the
budget is expressed in (deliberately NOT token counts — those are provider
specific). ``ContextSnapshot`` is the immutable, testable result of one
assembly pass by ``ContextManager``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TypeAlias

from friday.memory.models import Memory

# A conversation message as (message_id, role, content).
Message: TypeAlias = tuple[str, str, str]

# ~4 characters per unit — a conservative stand-in that over-counts rather
# than risk overflowing a real provider context window.
_UNIT_CHARS = 4


def estimate_units(text: str) -> int:
    """Estimate how many context units ``text`` occupies."""
    if not text:
        return 0
    return max(1, math.ceil(len(text) / _UNIT_CHARS))


@dataclass(frozen=True, slots=True)
class ContextBudget:
    """Bounds for how much input may be assembled.

    ``available_units`` is what the manager may fill after reserving space
    for the model's output and a safety margin.
    """

    max_input_units: int
    reserved_output_units: int
    safety_margin: int

    @property
    def available_units(self) -> int:
        return max(1, self.max_input_units - self.reserved_output_units - self.safety_margin)

    def remaining_after(self, used_units: int) -> int:
        return self.available_units - used_units


@dataclass(frozen=True, slots=True)
class ContextSnapshot:
    """The immutable result of a context assembly pass.

    Sources are listed from highest to lowest priority:

    1. system_instructions   (never removed)
    2. current_user_message  (never removed)
    3. recent_messages       (verbatim, capped at recent turns)
    4. project_context       (capped)
    5. durable_memories      (capped)
    6. compressed_history    (older conversation, LLM-compressed)
    """

    system_instructions: str
    current_user_message: str
    recent_messages: tuple[Message, ...]
    project_context: str | None
    durable_memories: tuple[Memory, ...]
    compressed_history: str | None
    budget: ContextBudget
    estimated_units: int
    compressed: bool = False

    def render(self) -> str:
        """Render the snapshot as a single prompt, in priority order."""
        sections: list[str] = []
        if self.system_instructions:
            sections.append(self.system_instructions)
        if self.current_user_message:
            sections.append(self.current_user_message)
        for _, role, content in self.recent_messages:
            sections.append(f"{role}: {content}")
        if self.project_context:
            sections.append(self.project_context)
        if self.durable_memories:
            sections.append("\n".join(f"- {memory.content}" for memory in self.durable_memories))
        if self.compressed_history:
            sections.append(self.compressed_history)
        return "\n".join(sections)


__all__ = [
    "ContextBudget",
    "ContextSnapshot",
    "Message",
    "estimate_units",
]
