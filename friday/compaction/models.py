"""
Compaction domain models.

These types define the persistent conversation-compaction vocabulary used by
the Phase 4 compactor, retrieval, and storage layers. They are intentionally
independent from any database, provider, or transport implementation.

Domain validation here is structural only: ID types, range ordering, and
provenance boundaries. Proving that a message ID physically exists in the
database is a storage-layer concern (out of scope for the domain model).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _require_aware_timestamp(name: str, value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value


def _validate_message_id(name: str, value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _normalize_source_message_ids(source_message_ids) -> tuple[int, ...]:
    if isinstance(source_message_ids, (str, bytes)) or not hasattr(source_message_ids, "__iter__"):
        raise TypeError("source_message_ids must be an iterable of integers")
    normalized: list[int] = []
    for message_id in source_message_ids:
        normalized.append(_validate_message_id("source_message_ids", message_id))
    return tuple(sorted(set(normalized)))


@dataclass(frozen=True, slots=True)
class CompactionItem:
    """A single structured compaction record (one of facts/decisions/changes/open_questions).

    ``source_message_ids`` must reference actual message IDs within the
    compaction's covered message range. IDs are normalized to a sorted,
    de-duplicated tuple of positive integers (duplicate provenance is
    collapsed deterministically).
    """

    item_id: str
    content: str
    source_message_ids: tuple[int, ...]

    def __post_init__(self) -> None:
        item_id = str(self.item_id).strip()
        if not item_id:
            raise ValueError("item_id cannot be empty")
        object.__setattr__(self, "item_id", item_id)

        if not isinstance(self.content, str) or not self.content.strip():
            raise ValueError("content cannot be empty")
        object.__setattr__(self, "content", self.content)

        source_message_ids = _normalize_source_message_ids(self.source_message_ids)
        if not source_message_ids:
            raise ValueError("source_message_ids cannot be empty")
        object.__setattr__(self, "source_message_ids", source_message_ids)


_STRUCTURED_CATEGORIES = ("facts", "decisions", "changes", "open_questions")


@dataclass(frozen=True, slots=True)
class ConversationCompaction:
    """An immutable, derived compaction of a contiguous message range.

    ``first_message_id`` and ``last_message_id`` define the covered range.
    Every item's ``source_message_ids`` must fall inside that range.

    ``next_start`` is NOT stored here; it is derived by the boundary
    computation (M2) from persisted compactions.
    """

    compaction_id: str
    conversation_id: int
    first_message_id: int
    last_message_id: int
    created_at: datetime = field(default_factory=_utc_now)
    compaction_version: int = 1
    summary: str = ""
    facts: tuple[CompactionItem, ...] = ()
    decisions: tuple[CompactionItem, ...] = ()
    changes: tuple[CompactionItem, ...] = ()
    open_questions: tuple[CompactionItem, ...] = ()

    def __post_init__(self) -> None:
        compaction_id = str(self.compaction_id).strip()
        if not compaction_id:
            raise ValueError("compaction_id cannot be empty")
        object.__setattr__(self, "compaction_id", compaction_id)

        conversation_id = _validate_message_id("conversation_id", self.conversation_id)
        object.__setattr__(self, "conversation_id", conversation_id)

        first_message_id = _validate_message_id("first_message_id", self.first_message_id)
        last_message_id = _validate_message_id("last_message_id", self.last_message_id)
        if first_message_id > last_message_id:
            raise ValueError("first_message_id must be <= last_message_id")
        object.__setattr__(self, "first_message_id", first_message_id)
        object.__setattr__(self, "last_message_id", last_message_id)

        created_at = _require_aware_timestamp("created_at", self.created_at)
        object.__setattr__(self, "created_at", created_at)

        if isinstance(self.compaction_version, bool) or not isinstance(self.compaction_version, int):
            raise TypeError("compaction_version must be an integer")
        if self.compaction_version <= 0:
            raise ValueError("compaction_version must be a positive integer")

        if not isinstance(self.summary, str):
            raise TypeError("summary must be a string")

        for category in _STRUCTURED_CATEGORIES:
            items = getattr(self, category)
            if not isinstance(items, tuple):
                raise TypeError(f"{category} must be a tuple of CompactionItem")
            for item in items:
                if not isinstance(item, CompactionItem):
                    raise TypeError(f"{category} must contain only CompactionItem instances")
                for message_id in item.source_message_ids:
                    if not (first_message_id <= message_id <= last_message_id):
                        raise ValueError(
                            "source_message_ids must fall within the covered message range "
                            f"[{first_message_id}, {last_message_id}]"
                        )


__all__ = [
    "CompactionItem",
    "ConversationCompaction",
]