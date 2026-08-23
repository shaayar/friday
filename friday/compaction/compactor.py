"""ConversationCompactor — orchestration facade for persistent compaction (M5).

Wires the already-tested pieces into one workflow:

    messages -> boundary (M2) -> bounded window (M2)
             -> ConversationCompactionExtractor (M3)
             -> SQLiteCompactionStore (M4)

Responsibilities:
- deterministic trigger evaluation (hybrid message+size OR; ``force``).
- exactly one bounded extraction+persistence per invocation (no loops).
- persistence via an injected storage backend (never a raw connection).
- failure isolation: typed M3/M4 exceptions propagate; the raw conversation
  is never mutated and no separate "mark compacted" operation exists.
- idempotency: a duplicate save of an already-persisted window is treated as
  an idempotent success returning the stored compaction.

The compactor never constructs provider LLMs, never writes to memory.db,
never promotes memories, and never touches retrieval. A future runtime seam
may call ``compact`` from a background task.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from friday.compaction.boundary import next_compaction_start, select_compaction_window
from friday.compaction.exceptions import CompactionAlreadyExistsError
from friday.compaction.extractor import ConversationCompactionExtractor
from friday.compaction.extractor import _Message as ExtractorMessage
from friday.compaction.models import ConversationCompaction
from friday.compaction.trigger import should_compact
from friday.config import config
from friday.context.models import estimate_units

# Message is defined by the extractor; we re-export it for callers
Message = ExtractorMessage


class CompactionStorage(Protocol):
    """Storage operations the compactor requires (satisfied by ``SQLiteCompactionStore``)."""

    def list_for_conversation(self, conversation_id: int) -> list[ConversationCompaction]: ...

    def get(self, compaction_id: str) -> ConversationCompaction | None: ...

    def save(self, compaction: ConversationCompaction) -> ConversationCompaction: ...


@dataclass(frozen=True, slots=True)
class CompactionResult:
    """Outcome of one ``compact`` invocation.

    ``remaining_messages`` is the number of uncompacted messages still
    pending after this operation (eligible messages minus the covered
    window). A positive value on a successful bounded compaction tells the
    caller that additional work remains.
    """

    compacted: bool
    compaction: ConversationCompaction | None
    remaining_messages: int


class ConversationCompactor:
    """Orchestrate a single bounded compaction operation."""

    def __init__(
        self,
        store: CompactionStorage,
        extractor: ConversationCompactionExtractor,
        *,
        message_threshold: int = config.COMPACTION_MESSAGE_THRESHOLD,
        max_window: int = config.COMPACTION_MAX_WINDOW,
        unit_threshold: int | None = config.COMPACTION_SIZE_THRESHOLD_UNITS,
    ) -> None:
        self._store = store
        self._extractor = extractor
        self._message_threshold = message_threshold
        self._max_window = max_window
        self._unit_threshold = unit_threshold

    async def compact(
        self,
        messages: Sequence[Message],
        *,
        conversation_id: int,
        force: bool = False,
    ) -> CompactionResult:
        """Compact the next bounded window for a conversation, if triggered.

        Normal (``force=False``) runs only when the hybrid trigger fires
        (message count or size threshold). ``force=True`` bypasses thresholds
        but still obeys the persisted boundary, ``max_window``, extraction
        validation, and persistence rules. No more than one bounded window is
        compacted per call; leftover uncompacted messages are reported via
        ``remaining_messages``.
        """
        boundary = next_compaction_start(self._store.list_for_conversation(conversation_id))
        eligible_count, estimated_units = self._eligible_stats(messages, boundary)

        if eligible_count == 0:
            return CompactionResult(compacted=False, compaction=None, remaining_messages=0)

        if not should_compact(
            eligible_count,
            estimated_units,
            force=force,
            message_threshold=self._message_threshold,
            unit_threshold=self._unit_threshold,
        ):
            return CompactionResult(
                compacted=False, compaction=None, remaining_messages=eligible_count
            )

        window = select_compaction_window(
            messages, next_start=boundary, max_window=self._max_window
        )
        if not window:
            return CompactionResult(
                compacted=False, compaction=None, remaining_messages=eligible_count
            )

        compaction = await self._extractor.extract(window, conversation_id=conversation_id)
        try:
            self._store.save(compaction)
        except CompactionAlreadyExistsError:
            existing = self._store.get(compaction.compaction_id)
            if existing is None:
                raise
            compaction = existing

        return CompactionResult(
            compacted=True,
            compaction=compaction,
            remaining_messages=eligible_count - len(window),
        )

    @staticmethod
    def _eligible_stats(messages: Sequence[Message], boundary: int | None) -> tuple[int, int]:
        """Count eligible messages and their estimated units since the boundary.

        Mirrors the M2 eligibility rule (``id >= boundary``, or all messages
        when the boundary is ``None``) without replacing M2 as the window
        selection authority. ``next_compaction_start`` derives ``boundary``
        solely from persisted compactions.
        """
        count = 0
        units = 0
        for message in messages:
            if boundary is not None and message.id < boundary:
                continue
            count += 1
            units += estimate_units(message.content)
        return count, units


__all__ = ["CompactionResult", "CompactionStorage", "ConversationCompactor", "Message"]
