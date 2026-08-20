"""Compaction boundary computation and bounded window selection (M2).

Pure deterministic in-memory logic with no database access.

Message identity follows the repository's conversation store:
``friday.memory.sqlite_store.Message.id`` is an ``int`` (SQLite AUTOINCREMENT,
monotonic across inserts but not guaranteed gap-free; ordering is by ``id``).
The boundary arithmetic ``max(last_message_id) + 1`` is therefore a safe
threshold regardless of gaps: it is a lower bound on the next uncompacted
message, not an assertion that every integer between bounds exists.

``next_start`` is always derived from compactions; it is never stored.
A ``None`` boundary means no compaction has been recorded yet, so the window
starts at the first available message.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Protocol, TypeAlias

from friday.compaction.models import ConversationCompaction

Boundary: TypeAlias = int | None


def _validate_boundary(boundary: Boundary) -> int | None:
    if boundary is None:
        return None
    if isinstance(boundary, bool) or not isinstance(boundary, int):
        raise TypeError("boundary must be an integer or None")
    if boundary <= 0:
        raise ValueError("boundary must be a positive integer")
    return boundary


def _validate_max_window(max_window: int) -> int:
    if isinstance(max_window, bool) or not isinstance(max_window, int):
        raise TypeError("max_window must be an integer")
    if max_window <= 0:
        raise ValueError("max_window must be a positive integer")
    return max_window


def next_compaction_start(compactions: Iterable[ConversationCompaction]) -> Boundary:
    """Return ``1 + max(last_message_id)`` across successful compactions.

    Returns ``None`` when no compactions exist (the window starts at the
    first available message). The boundary is always the greatest completed
    boundary, regardless of input order; duplicate or overlapping ranges are
    tolerated and the derived boundary is conservative (never before any
    covered message).
    """
    greatest: int | None = None
    for compaction in compactions:
        if not isinstance(compaction, ConversationCompaction):
            raise TypeError("compactions must contain only ConversationCompaction instances")
        last_message_id = compaction.last_message_id
        if greatest is None or last_message_id > greatest:
            greatest = last_message_id
    if greatest is None:
        return None
    return greatest + 1


class _Message(Protocol):
    id: int


Message: TypeAlias = _Message


def select_compaction_window(
    messages: Sequence[Message],
    *,
    next_start: Boundary,
    max_window: int,
) -> tuple[Message, ...]:
    """Select the next bounded compaction window from ordered messages.

    Only messages with ``id >= next_start`` are eligible; the first
    ``max_window`` of them are returned in original order. Original message
    objects are preserved and the input sequence is never mutated. When
    ``next_start`` is ``None`` every message is eligible.
    """
    boundary = _validate_boundary(next_start)
    _validate_max_window(max_window)

    selected: list[Message] = []
    for message in messages:
        if boundary is not None and message.id < boundary:
            continue
        selected.append(message)
        if len(selected) >= max_window:
            break
    return tuple(selected)


__all__ = [
    "Boundary",
    "Message",
    "next_compaction_start",
    "select_compaction_window",
]