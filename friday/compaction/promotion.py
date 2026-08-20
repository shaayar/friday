"""Promotion-ledger domain model (Phase 4 M6.1, ADR-025).

Tracks the optional projection of a single ``CompactionItem`` from
conversation compaction into durable memory.

Lifecycle (per ADR-025):

    PENDING → PROMOTED
    PENDING → REJECTED
    REJECTED → PENDING   (explicit reconsideration only)

PROMOTED is terminal. REJECTED is terminal unless explicit reconsideration
is requested. Transient failures do NOT become a separate FAILED state;
they leave the item PENDING.

The ledger is keyed by the deterministic ``CompactionItem.item_id``. No
separate promotion ID replaces it, and no ``promoted`` boolean is added to
``CompactionItem``.

Domain validation here is structural only (IDs, enums, timestamps, status
consistency). Storage, memory-pipeline integration, and orchestration are
intentionally out of scope for this domain layer.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import Enum


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _require_aware_timestamp(name: str, value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value


def _normalize_optional_text(name: str, value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        raise ValueError(f"{name} cannot be empty")
    return text


def _normalize_memory_ids(memory_ids) -> tuple[str, ...]:
    if isinstance(memory_ids, (str, bytes)) or not hasattr(memory_ids, "__iter__"):
        raise TypeError("resolved_memory_ids must be an iterable of strings")
    normalized: list[str] = []
    for memory_id in memory_ids:
        text = str(memory_id).strip()
        if not text:
            raise ValueError("resolved_memory_ids cannot contain empty values")
        normalized.append(text)
    return tuple(sorted(set(normalized)))


class CompactionItemCategory(str, Enum):
    """The structured compaction category an item belongs to (M1)."""

    FACTS = "facts"
    DECISIONS = "decisions"
    CHANGES = "changes"
    OPEN_QUESTIONS = "open_questions"


class PromotionStatus(str, Enum):
    """Lifecycle states of a promotion-ledger entry (ADR-025)."""

    PENDING = "pending"
    PROMOTED = "promoted"
    REJECTED = "rejected"


class PromotionResolutionKind(str, Enum):
    """Kind of resolution produced by the memory resolver (CREATE/SUPERSEDE)."""

    CREATE = "create"
    SUPERSEDE = "supersede"


@dataclass(frozen=True, slots=True)
class CompactionPromotion:
    """An immutable promotion-ledger entry for a single ``CompactionItem``.

    ``item_id`` is the source identity; the same ``CompactionItem.item_id``
    always refers to the same ledger entry. State transitions are explicit
    methods that return a new ``CompactionPromotion``; arbitrary mutation is
    not allowed.

    ``summary`` and ``open_questions`` items are never promoted per
    ADR-025, but the ledger is a general per-item record and does not embed
    the promotion policy itself.
    """

    item_id: str
    compaction_id: str
    category: CompactionItemCategory
    status: PromotionStatus = PromotionStatus.PENDING
    resolved_memory_ids: tuple[str, ...] = ()
    resolution_kind: PromotionResolutionKind | None = None
    resolution_reason: str | None = None
    retry_count: int = 0
    last_error: str | None = None
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        item_id = str(self.item_id).strip()
        if not item_id:
            raise ValueError("item_id cannot be empty")
        object.__setattr__(self, "item_id", item_id)

        compaction_id = str(self.compaction_id).strip()
        if not compaction_id:
            raise ValueError("compaction_id cannot be empty")
        object.__setattr__(self, "compaction_id", compaction_id)

        if not isinstance(self.category, CompactionItemCategory):
            raise TypeError(f"Invalid category: {self.category!r}")
        if not isinstance(self.status, PromotionStatus):
            raise TypeError(f"Invalid status: {self.status!r}")
        if self.resolution_kind is not None and not isinstance(
            self.resolution_kind, PromotionResolutionKind
        ):
            raise TypeError(f"Invalid resolution kind: {self.resolution_kind!r}")

        if isinstance(self.retry_count, bool) or not isinstance(self.retry_count, int):
            raise TypeError("retry_count must be an integer")
        if self.retry_count < 0:
            raise ValueError("retry_count cannot be negative")

        memory_ids = _normalize_memory_ids(self.resolved_memory_ids)
        object.__setattr__(self, "resolved_memory_ids", memory_ids)

        resolution_reason = _normalize_optional_text("resolution_reason", self.resolution_reason)
        object.__setattr__(self, "resolution_reason", resolution_reason)

        last_error = _normalize_optional_text("last_error", self.last_error)
        object.__setattr__(self, "last_error", last_error)

        created_at = _require_aware_timestamp("created_at", self.created_at)
        object.__setattr__(self, "created_at", created_at)

        updated_at = created_at if self.updated_at is None else _require_aware_timestamp("updated_at", self.updated_at)
        if updated_at < created_at:
            raise ValueError("updated_at cannot be earlier than created_at")
        object.__setattr__(self, "updated_at", updated_at)

        if self.status is PromotionStatus.PROMOTED:
            if not memory_ids:
                raise ValueError("a PROMOTED promotion requires resolved memory ID(s)")
        elif memory_ids:
            raise ValueError("a non-PROMOTED promotion cannot claim resolved memory IDs")
        if self.status is PromotionStatus.REJECTED and not resolution_reason:
            raise ValueError("a REJECTED promotion requires a resolution reason")
        if self.resolution_kind is not None and self.status is not PromotionStatus.PROMOTED:
            raise ValueError("resolution_kind is only valid for PROMOTED promotions")

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def pending(
        cls,
        item_id: str,
        compaction_id: str,
        category: CompactionItemCategory,
        *,
        created_at: datetime | None = None,
    ) -> CompactionPromotion:
        """Create a fresh PENDING ledger entry for a compaction item."""
        return cls(
            item_id=item_id,
            compaction_id=compaction_id,
            category=category,
            created_at=created_at if created_at is not None else _utc_now(),
        )

    # ------------------------------------------------------------------
    # State transitions (return new immutable instances)
    # ------------------------------------------------------------------

    def mark_promoted(
        self,
        memory_ids: Sequence[str],
        *,
        resolution_kind: PromotionResolutionKind | None = None,
        updated_at: datetime | None = None,
    ) -> CompactionPromotion:
        """Transition PENDING → PROMOTED with the resulting memory ID(s)."""
        if self.status is not PromotionStatus.PENDING:
            raise ValueError(
                f"cannot promote a {self.status.value!r} promotion; only PENDING may become PROMOTED"
            )
        return replace(
            self,
            status=PromotionStatus.PROMOTED,
            resolved_memory_ids=memory_ids,
            resolution_kind=resolution_kind,
            updated_at=updated_at if updated_at is not None else _utc_now(),
        )

    def mark_rejected(
        self,
        reason: str,
        *,
        updated_at: datetime | None = None,
    ) -> CompactionPromotion:
        """Transition PENDING → REJECTED with a required resolution reason."""
        if self.status is not PromotionStatus.PENDING:
            raise ValueError(
                f"cannot reject a {self.status.value!r} promotion; only PENDING may become REJECTED"
            )
        return replace(
            self,
            status=PromotionStatus.REJECTED,
            resolution_reason=reason,
            updated_at=updated_at if updated_at is not None else _utc_now(),
        )

    def request_reconsideration(self, *, updated_at: datetime | None = None) -> CompactionPromotion:
        """Transition REJECTED → PENDING; must be explicitly requested."""
        if self.status is not PromotionStatus.REJECTED:
            raise ValueError(
                f"cannot reconsider a {self.status.value!r} promotion; only REJECTED may be reconsidered"
            )
        return replace(
            self,
            status=PromotionStatus.PENDING,
            updated_at=updated_at if updated_at is not None else _utc_now(),
        )

    def record_transient_failure(self, error: str, *, updated_at: datetime | None = None) -> CompactionPromotion:
        """Record a transient failure; the item stays PENDING and retry_count increments.

        Per ADR-025, transient failures never become a separate FAILED state.
        """
        if self.status is not PromotionStatus.PENDING:
            raise ValueError(
                f"cannot record a failure on a {self.status.value!r} promotion; only PENDING may be retried"
            )
        return replace(
            self,
            retry_count=self.retry_count + 1,
            last_error=error,
            updated_at=updated_at if updated_at is not None else _utc_now(),
        )


__all__ = [
    "CompactionItemCategory",
    "CompactionPromotion",
    "PromotionResolutionKind",
    "PromotionStatus",
]