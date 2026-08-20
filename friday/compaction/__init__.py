"""Compaction subsystem — persistent conversation compaction (Phase 4).

M1 scope: immutable domain models with structural provenance validation.
M2 scope: deterministic in-memory boundary computation and bounded window
selection.
M3 scope: LLM-facing extraction (bounded window -> validated compaction).
M4 scope: SQLite persistence for compaction records in conversations.db.
M5 scope: orchestration facade + deterministic trigger (hybrid, force).
M6.1 scope: promotion-ledger domain models (ADR-025).
M6.2 scope: SQLite promotion-ledger storage in conversations.db (ADR-025).
M6.3 scope: explicit ConversationMemoryPromoter orchestrator (ADR-025);
automatic/background promotion is added in later milestones.
"""

from friday.compaction.boundary import (
    Boundary,
    next_compaction_start,
    select_compaction_window,
)
from friday.compaction.compactor import (
    CompactionResult,
    CompactionStorage,
    ConversationCompactor,
    Message,
)
from friday.compaction.exceptions import (
    CompactionAlreadyExistsError,
    CompactionCorruptError,
    CompactionError,
    CompactionNotFoundError,
    CompactionOutputError,
    CompactionProviderError,
    CompactionStorageError,
    PromotionAlreadyExistsError,
    PromotionCorruptError,
    PromotionNotFoundError,
    PromotionStorageError,
)
from friday.compaction.extractor import ConversationCompactionExtractor
from friday.compaction.models import CompactionItem, ConversationCompaction
from friday.compaction.promoter import (
    ConversationMemoryPromoter,
    PromotionItemResult,
    PromotionOutcome,
    PromotionResult,
)
from friday.compaction.promotion import (
    CompactionItemCategory,
    CompactionPromotion,
    PromotionResolutionKind,
    PromotionStatus,
)
from friday.compaction.promotion_store import SQLitePromotionStore
from friday.compaction.sqlite_store import SQLiteCompactionStore
from friday.compaction.trigger import should_compact

__all__ = [
    "Boundary",
    "CompactionAlreadyExistsError",
    "CompactionCorruptError",
    "CompactionError",
    "CompactionItem",
    "CompactionItemCategory",
    "CompactionNotFoundError",
    "CompactionOutputError",
    "CompactionPromotion",
    "CompactionProviderError",
    "CompactionResult",
    "CompactionStorage",
    "CompactionStorageError",
    "ConversationCompaction",
    "ConversationCompactionExtractor",
    "ConversationCompactor",
    "ConversationMemoryPromoter",
    "Message",
    "PromotionAlreadyExistsError",
    "PromotionCorruptError",
    "PromotionItemResult",
    "PromotionNotFoundError",
    "PromotionOutcome",
    "PromotionResolutionKind",
    "PromotionResult",
    "PromotionStatus",
    "PromotionStorageError",
    "SQLiteCompactionStore",
    "SQLitePromotionStore",
    "next_compaction_start",
    "select_compaction_window",
    "should_compact",
]