"""ContextManager — assembles a runtime ``ContextSnapshot`` within budget.

This module orchestrates existing components (``ContextBudget``,
``ContextSnapshot``, ``estimate_units``, ``ContextShrinker``, the durable
memory manager, and a project-context provider) rather than duplicating
their logic.

Source priority (highest first):

1. system instructions   (never removed)
2. current user message  (never removed)
3. recent conversation   (verbatim, capped to recent turns)
4. project context       (capped)
5. durable memories      (capped, ranked)
6. compressed history    (older conversation, only when over budget)

Budget enforcement is strictly best-effort: failures in memory retrieval,
project context, or shrinking degrade gracefully and never abort the build.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from friday.config import config
from friday.context.models import (
    ContextBudget,
    ContextSnapshot,
    Message,
    estimate_units,
)
from friday.context.shrinker import ContextShrinker
from friday.memory.models import (
    Memory,
    MemoryConfidence,
    MemoryScope,
)
from friday.memory.text import significant_terms

logger = logging.getLogger(__name__)

# A generous upper bound for retrieval so ranking happens before capping.
_RETRIEVAL_LIMIT = 1000
# Sentinel drop-rank for sources that must never be removed.
_NEVER = 10**9

_CONFIDENCE_RANK = {
    MemoryConfidence.EXPLICIT: 0,
    MemoryConfidence.INFERRED: 1,
    MemoryConfidence.TENTATIVE: 2,
}


class MemoryProvider(Protocol):
    """Read-only active-memory access; satisfied by ``DurableMemoryManager``."""

    def get_active(
        self,
        *,
        scope: MemoryScope | None = None,
        project_id: str | None = None,
        valid_at: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Memory]: ...


@dataclass(frozen=True, slots=True)
class ProjectContext:
    """Read-only project knowledge, mirroring the private workspace files.

    ``changelog.md`` is intentionally excluded. ``facts_md`` and
    ``decisions_md`` are optional and included subject to the configured cap.
    """

    context_md: str = ""
    state_json: str = ""
    facts_md: str | None = None
    decisions_md: str | None = None


class ProjectContextProvider(Protocol):
    """Smallest read-only abstraction for project context.

    Implementations resolve the active project and read its private
    workspace. FRIDAY's own ``ProjectService`` can adapt to this without the
    context package importing it.
    """

    def get_context(self, project_id: str) -> ProjectContext | None: ...


@dataclass(slots=True)
class _Part:
    priority: int
    label: str
    text: str
    drop_rank: int
    data: object = None


class ContextManager:
    """Assemble a budget-enforced ``ContextSnapshot`` from existing sources."""

    def __init__(
        self,
        *,
        memory_manager: MemoryProvider,
        project_context_provider: ProjectContextProvider | None = None,
        shrinker: ContextShrinker | None = None,
        budget: ContextBudget | None = None,
        recent_turns: int | None = None,
        memory_cap: int | None = None,
        project_context_cap_units: int | None = None,
    ) -> None:
        self._memory_manager = memory_manager
        self._project_provider = project_context_provider
        self._shrinker = shrinker
        self._budget = budget or ContextBudget(
            max_input_units=config.CONTEXT_MAX_INPUT_UNITS,
            reserved_output_units=config.CONTEXT_RESERVED_OUTPUT_UNITS,
            safety_margin=config.CONTEXT_SAFETY_MARGIN,
        )
        self._recent_turns = (
            recent_turns if recent_turns is not None else config.CONTEXT_RECENT_TURNS
        )
        self._memory_cap = memory_cap if memory_cap is not None else config.CONTEXT_MEMORY_CAP
        self._project_cap = (
            project_context_cap_units
            if project_context_cap_units is not None
            else config.CONTEXT_PROJECT_CAP_UNITS
        )

    def assemble(
        self,
        *,
        system_instructions: str,
        current_user_message: str | None,
        recent_messages: Sequence[Message],
        conversation_id: str | int | None,
        active_project_id: str | None,
    ) -> ContextSnapshot:
        """Assemble a context snapshot for the current request.

        ``conversation_id`` is reserved for provenance; retrieval is scoped
        to the active project and the user, not to a single conversation.
        """
        now = _utc_now()
        available = self._budget.available_units

        recent = list(recent_messages)[-self._recent_turns * 2 :]
        older = list(recent_messages)[: len(recent_messages) - len(recent)]

        current_text = current_user_message or ""
        memories = self._retrieve_memories(active_project_id, current_text, now)
        project_text = self._project_context(active_project_id)

        parts: list[_Part] = [
            _Part(1, "system_instructions", system_instructions, _NEVER),
            _Part(2, "current_user_message", current_text, _NEVER),
        ]
        for index, message in enumerate(recent):
            message_id, role, content = message
            parts.append(
                _Part(
                    3,
                    f"recent_message:{message_id}",
                    f"{role}: {content}",
                    4 + index,
                    data=message,
                )
            )
        if project_text:
            parts.append(_Part(4, "project_context", project_text, 3))
        if memories:
            parts.append(_Part(5, "durable_memories", _render_memories(memories), 2, data=tuple(memories)))

        used = sum(estimate_units(part.text) for part in parts)

        # Preserve the verbatim recent window first, dropping the least
        # important droppable sources (durable, project, then recent oldest
        # first) until the budget fits. system + current are never dropped.
        while used > available:
            removable = [part for part in parts if part.drop_rank != _NEVER]
            if not removable:
                break
            lowest = min(removable, key=lambda part: part.drop_rank)
            parts.remove(lowest)
            used -= estimate_units(lowest.text)

        # Enrich the remaining budget with a compressed summary of the older
        # window (never exceeding the leftover; compressed history is the
        # lowest-value source and is added only into spare room).
        compressed_history: str | None = None
        remaining = available - used
        if remaining > 0 and older and self._shrinker is not None:
            compressed_history = self._compress(older, remaining)
            if compressed_history is not None:
                parts.append(
                    _Part(
                        6,
                        "compressed_history",
                        compressed_history,
                        1,
                        data=compressed_history,
                    )
                )
                used += estimate_units(compressed_history)

        snapshot = self._build_snapshot(parts, used)
        return snapshot

    # ------------------------------------------------------------------
    # Snapshot population
    # ------------------------------------------------------------------

    def _build_snapshot(self, parts: list[_Part], used: int) -> ContextSnapshot:
        recent_messages = tuple(part.data for part in parts if part.priority == 3)
        project_part = next((part for part in parts if part.priority == 4), None)
        durable_part = next((part for part in parts if part.priority == 5), None)
        compressed_part = next((part for part in parts if part.priority == 6), None)

        return ContextSnapshot(
            system_instructions=next(part.text for part in parts if part.priority == 1),
            current_user_message=next(part.text for part in parts if part.priority == 2),
            recent_messages=recent_messages,
            project_context=project_part.text if project_part else None,
            durable_memories=tuple(durable_part.data) if durable_part else (),
            compressed_history=compressed_part.text if compressed_part else None,
            budget=self._budget,
            estimated_units=used,
            compressed=compressed_part is not None,
        )

    # ------------------------------------------------------------------
    # Durable memory retrieval (isolated)
    # ------------------------------------------------------------------

    def _retrieve_memories(self, project_id: str | None, query_text: str, now: datetime) -> list[Memory]:
        try:
            active = self._memory_manager.get_active(valid_at=now, limit=_RETRIEVAL_LIMIT)
        except Exception:  # noqa: BLE001 - storage boundary; degrade, never abort
            logger.warning("Durable memory retrieval failed; omitting durable context")
            return []

        scoped = [
            memory
            for memory in active
            if memory.scope is MemoryScope.USER
            or (
                memory.scope is MemoryScope.PROJECT
                and project_id is not None
                and memory.project_id == project_id
            )
        ]
        scoped.sort(key=lambda memory: self._memory_rank(memory, query_text))
        return scoped[: self._memory_cap]

    def _memory_rank(self, memory: Memory, query_text: str) -> tuple[int, int, float]:
        """Deterministic rank: lexical relevance → confidence → recency."""
        shared = significant_terms(query_text) & significant_terms(memory.content)
        confidence = _CONFIDENCE_RANK.get(memory.confidence, 2)
        created_at = memory.created_at
        timestamp = created_at.timestamp() if created_at is not None else 0.0
        return (-len(shared), confidence, -timestamp)

    # ------------------------------------------------------------------
    # Project context (isolated)
    # ------------------------------------------------------------------

    def _project_context(self, project_id: str | None) -> str | None:
        if project_id is None or self._project_provider is None:
            return None
        try:
            context = self._project_provider.get_context(project_id)
        except Exception:  # noqa: BLE001 - provider boundary; degrade, never abort
            logger.warning("Project context retrieval failed; omitting project context")
            return None
        if context is None:
            return None

        sections = [
            section
            for section in (context.context_md, context.state_json, context.facts_md, context.decisions_md)
            if section
        ]
        if not sections:
            return None

        # context.md and state.json are always preferred; facts/decisions are
        # included only while the composed text stays within the cap.
        always = [section for section in (context.context_md, context.state_json) if section]
        optional = [section for section in (context.facts_md, context.decisions_md) if section]
        text = "\n\n".join(always)
        for section in optional:
            candidate = f"{text}\n\n{section}"
            if estimate_units(candidate) <= self._project_cap:
                text = candidate
        return text

    # ------------------------------------------------------------------
    # Compression (isolated)
    # ------------------------------------------------------------------

    def _compress(self, older: list[Message], max_units: int) -> str | None:
        try:
            return self._shrinker.shrink(older, max_units=max_units)
        except Exception:  # noqa: BLE001 - compression boundary; degrade, never abort
            logger.warning("Context compression failed; omitting compressed history")
            return None


def _render_memories(memories: list[Memory]) -> str:
    return "\n".join(f"- {memory.content}" for memory in memories)


def _utc_now() -> datetime:
    return datetime.now(UTC)


__all__ = [
    "ContextManager",
    "MemoryProvider",
    "ProjectContext",
    "ProjectContextProvider",
]