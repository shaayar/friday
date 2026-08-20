"""M6.4 integration/hardening tests (Phase 4, ADR-025).

End-to-end validation of the full compaction-promotion path using REAL
temporary SQLite databases:

    ConversationCompaction
        ↓ ConversationMemoryPromoter
    MemoryCandidate
        ↓ MemoryResolver
    DurableMemoryManager.apply_batch()
        ↓
    memory.db

    AND

    ConversationCompaction
        ↓ SQLitePromotionStore
        ↓
    conversations.db

Actual guarantees exercised here (documented, NOT idealized):

- conversations.db and memory.db are separate databases; no cross-database
  transaction exists or is claimed.
- memory writes are atomic per batch within memory.db (apply_batch rolls back
  on any in-batch failure).
- the promotion ledger's item_id PRIMARY KEY is authoritative: concurrent
  saves produce at most one row.
- a memory write that succeeds while the ledger update fails leaves the
  ledger PENDING; a retry reconciles by deterministic provenance + content
  and never duplicates the memory.
- PROMOTED/REJECTED are terminal for normal promotion (NOOP on repeat).
- ineligible categories never touch memory.db and never create ledger rows.
"""

from __future__ import annotations

import os
import threading
from datetime import UTC, datetime
from pathlib import Path

import pytest

from friday.compaction.exceptions import (
    PromotionAlreadyExistsError,
    PromotionStorageError,
)
from friday.compaction.models import CompactionItem, ConversationCompaction
from friday.compaction.promoter import ConversationMemoryPromoter, PromotionOutcome
from friday.compaction.promotion import (
    CompactionItemCategory,
    CompactionPromotion,
    PromotionStatus,
)
from friday.compaction.promotion_store import SQLitePromotionStore
from friday.compaction.sqlite_store import SQLiteCompactionStore
from friday.memory.durable_manager import DurableMemoryManager
from friday.memory.exceptions import MemoryStorageError
from friday.memory.models import (
    Memory,
    MemoryConfidence,
    MemoryProvenance,
    MemoryScope,
    MemoryStatus,
    MemoryType,
)
from friday.memory.resolver import MemoryResolver
from friday.memory.sqlite_memory_store import SQLiteMemoryStore
from friday.memory.sqlite_store import SQLiteConversationStore

FIXED_NOW = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def make_item(item_id: str, content: str, source_message_ids: tuple[int, ...]) -> CompactionItem:
    return CompactionItem(item_id=item_id, content=content, source_message_ids=source_message_ids)


def make_compaction(
    *,
    conversation_id: int,
    compaction_id: str = "comp-1",
    summary: str = "The conversation covered setup and design.",
    facts: tuple[CompactionItem, ...] = (),
    decisions: tuple[CompactionItem, ...] = (),
    changes: tuple[CompactionItem, ...] = (),
    open_questions: tuple[CompactionItem, ...] = (),
) -> ConversationCompaction:
    return ConversationCompaction(
        compaction_id=compaction_id,
        conversation_id=conversation_id,
        first_message_id=1,
        last_message_id=10,
        created_at=FIXED_NOW,
        summary=summary,
        facts=facts,
        decisions=decisions,
        changes=changes,
        open_questions=open_questions,
    )


def seed_conversation(conv_db: Path) -> int:
    with SQLiteConversationStore(conv_db) as store:
        conversation = store.create_conversation()
        for index in range(1, 11):
            store.save_message(conversation.id, "user", f"Message {index}")
        return conversation.id


def seed_compaction(conv_db: Path, conversation_id: int, **overrides) -> ConversationCompaction:
    with SQLiteCompactionStore(conv_db) as store:
        compaction = make_compaction(conversation_id=conversation_id, **overrides)
        store.save(compaction)
    return compaction


def seed_memory(mem_db: Path, memory: Memory) -> Memory:
    with SQLiteMemoryStore(mem_db) as store:
        store.save(memory)
    return memory


def default_promoter(conv_db: Path, mem_db: Path):
    promotion_store = SQLitePromotionStore(conv_db)
    memory_store = SQLiteMemoryStore(mem_db)
    manager = DurableMemoryManager(memory_store)
    promoter = ConversationMemoryPromoter(promotion_store, manager, MemoryResolver())
    return promoter, promotion_store, memory_store


@pytest.fixture
def db_paths(tmp_path: Path) -> tuple[Path, Path]:
    return tmp_path / "conversations.db", tmp_path / "memory.db"


@pytest.fixture
def conversation_id(db_paths: tuple[Path, Path]) -> int:
    conv_db, _ = db_paths
    return seed_conversation(conv_db)


# ----------------------------------------------------------------------
# Failpoint infrastructure
# ----------------------------------------------------------------------


class FailpointPromotionStore(SQLitePromotionStore):
    """SQLitePromotionStore that can be told to fail save()/replace() calls."""

    def __init__(
        self,
        db_path: Path,
        *,
        fail_save: bool = False,
        fail_replace: bool = False,
    ) -> None:
        super().__init__(db_path)
        self.fail_save = fail_save
        self.fail_replace = fail_replace

    def save(self, promotion: CompactionPromotion) -> CompactionPromotion:
        if self.fail_save:
            raise PromotionStorageError("ledger save failed (test failpoint)")
        return super().save(promotion)

    def replace(self, promotion: CompactionPromotion) -> CompactionPromotion:
        if self.fail_replace:
            raise PromotionStorageError("ledger replace failed (test failpoint)")
        return super().replace(promotion)


class FailpointMemoryManager:
    """Protocol-compatible memory manager that can fail get_active()/apply_batch()."""

    def __init__(self, manager: DurableMemoryManager) -> None:
        self._manager = manager
        self.fail_get_active = False
        self.fail_apply = False

    def get_active(
        self,
        *,
        scope: MemoryScope | None = None,
        project_id: str | None = None,
        valid_at=None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Memory]:
        if self.fail_get_active:
            raise MemoryStorageError("memory.db unavailable (get_active failpoint)")
        return self._manager.get_active(
            scope=scope, project_id=project_id, valid_at=valid_at, limit=limit, offset=offset
        )

    def apply_batch(self, resolutions) -> list[Memory | None]:
        if self.fail_apply:
            raise MemoryStorageError("memory.db unavailable (apply_batch failpoint)")
        return self._manager.apply_batch(resolutions)


class StorageSaveFailpoint:
    """MemoryStorage proxy that fails save() after N successful saves (mid-batch crash)."""

    def __init__(self, storage: SQLiteMemoryStore, *, fail_after: int | None = None) -> None:
        self._storage = storage
        self.fail_after = fail_after
        self.save_count = 0

    def save(self, memory: Memory) -> Memory:
        if self.fail_after is not None and self.save_count >= self.fail_after:
            raise MemoryStorageError("mid-batch save failure (test failpoint)")
        result = self._storage.save(memory)
        self.save_count += 1
        return result

    def get(self, memory_id: str) -> Memory | None:
        return self._storage.get(memory_id)

    def update(self, memory: Memory) -> Memory:
        return self._storage.update(memory)

    def query(self, **kwargs) -> list[Memory]:
        return self._storage.query(**kwargs)

    def transaction(self):
        return self._storage.transaction()


class CountingResolver:
    def __init__(self, resolver: MemoryResolver) -> None:
        self._resolver = resolver
        self.calls = 0

    def resolve(self, candidates, *, existing_memories):
        self.calls += 1
        return self._resolver.resolve(candidates, existing_memories=existing_memories)


class CountingMemoryManager:
    def __init__(self, manager: DurableMemoryManager) -> None:
        self._manager = manager
        self.apply_calls = 0

    def get_active(self, **kwargs) -> list[Memory]:
        return self._manager.get_active(**kwargs)

    def apply_batch(self, resolutions) -> list[Memory | None]:
        self.apply_calls += 1
        return self._manager.apply_batch(resolutions)


# ======================================================================
# GROUP 1 — END-TO-END CREATE
# ======================================================================


def test_group1_end_to_end_create(db_paths, conversation_id) -> None:
    conv_db, mem_db = db_paths
    compaction = seed_compaction(
        conv_db, conversation_id, facts=(make_item("fact-1", "I use Ubuntu on my desktop.", (1, 2)),)
    )

    promoter, promotion_store, memory_store = default_promoter(conv_db, mem_db)
    try:
        result = promoter.promote(compaction, project_id="proj-1")

        outcome = result.items[0]
        assert outcome.item_id == "fact-1"
        assert outcome.category is CompactionItemCategory.FACTS
        assert outcome.outcome is PromotionOutcome.PROMOTED
        assert outcome.resolution_kind is not None

        memories = memory_store.query(conversation_id=conversation_id)
        assert len(memories) == 1
        memory = memories[0]
        assert memory.type is MemoryType.USER_FACT
        assert memory.scope is MemoryScope.USER
        assert memory.status is MemoryStatus.ACTIVE
        assert memory.project_id is None
        assert memory.confidence is MemoryConfidence.EXPLICIT
        assert memory.provenance.source_conversation_id == str(conversation_id)
        assert memory.provenance.source_message_ids == ("1", "2")

        entry = promotion_store.get("fact-1")
        assert entry.status is PromotionStatus.PROMOTED
        assert entry.resolved_memory_ids == (memory.id,)
        assert outcome.memory_ids == (memory.id,)
    finally:
        promotion_store.close()
        memory_store.close()

    with SQLitePromotionStore(conv_db) as reopened_promotion:
        entry = reopened_promotion.get("fact-1")
        assert entry.status is PromotionStatus.PROMOTED
        assert entry.resolved_memory_ids == (outcome.memory_ids[0],)
    with SQLiteMemoryStore(mem_db) as reopened_memory:
        memory = reopened_memory.get(entry.resolved_memory_ids[0])
        assert memory.status is MemoryStatus.ACTIVE
        assert memory.provenance.source_conversation_id == str(conversation_id)
        assert memory.provenance.source_message_ids == ("1", "2")


# ======================================================================
# GROUP 2 — END-TO-END SUPERSEDE
# ======================================================================


def test_group2_end_to_end_supersede(db_paths, conversation_id) -> None:
    conv_db, mem_db = db_paths
    old = Memory(
        type=MemoryType.PROJECT_FACT,
        scope=MemoryScope.PROJECT,
        content="FRIDAY stores compacted conversations in SQLite.",
        id="mem-old",
        project_id="proj-1",
    )
    seed_memory(mem_db, old)

    compaction = seed_compaction(
        conv_db,
        conversation_id,
        facts=(
            make_item(
                "fact-1",
                "FRIDAY now uses PostgreSQL for compacted conversation persistence.",
                (1, 2),
            ),
        ),
    )

    promoter, promotion_store, memory_store = default_promoter(conv_db, mem_db)
    try:
        result = promoter.promote(compaction, project_id="proj-1")

        outcome = result.items[0]
        assert outcome.outcome is PromotionOutcome.PROMOTED
        assert outcome.resolution_kind.value == "supersede"
        assert len(outcome.memory_ids) == 1
        new_id = outcome.memory_ids[0]
        assert new_id != "mem-old"

        entry = promotion_store.get("fact-1")
        assert entry.status is PromotionStatus.PROMOTED
        assert entry.resolution_kind.value == "supersede"
        assert entry.resolved_memory_ids == (new_id,)

        new = memory_store.get(new_id)
        assert new.status is MemoryStatus.ACTIVE
        assert new.supersedes == "mem-old"
        assert new.type is MemoryType.PROJECT_FACT
        assert new.project_id == "proj-1"
        assert new.content == "FRIDAY now uses PostgreSQL for compacted conversation persistence."

        superseded = memory_store.get("mem-old")
        assert superseded.status is MemoryStatus.SUPERSEDED
        assert superseded.superseded_by == new_id

        expected = make_compaction(
            conversation_id=conversation_id,
            facts=(
                make_item(
                    "fact-1",
                    "FRIDAY now uses PostgreSQL for compacted conversation persistence.",
                    (1, 2),
                ),
            ),
        )
        assert compaction == expected
    finally:
        promotion_store.close()
        memory_store.close()


# ======================================================================
# GROUP 3 — REJECT PATH
# ======================================================================


def test_group3_reject_path(db_paths, conversation_id) -> None:
    conv_db, mem_db = db_paths
    content = "FRIDAY uses SQLite for compaction storage."
    existing = Memory(
        type=MemoryType.PROJECT_FACT,
        scope=MemoryScope.PROJECT,
        content=content,
        id="mem-dup",
        project_id="proj-1",
    )
    seed_memory(mem_db, existing)

    compaction = seed_compaction(
        conv_db, conversation_id, facts=(make_item("fact-1", content, (1, 2)),)
    )

    promoter, promotion_store, memory_store = default_promoter(conv_db, mem_db)
    try:
        result = promoter.promote(compaction, project_id="proj-1")

        outcome = result.items[0]
        assert outcome.outcome is PromotionOutcome.REJECTED
        assert "duplicate" in (outcome.reason or "")

        assert len(memory_store.query(conversation_id=conversation_id)) == 0
        assert memory_store.get("mem-dup").status is MemoryStatus.ACTIVE

        entry = promotion_store.get("fact-1")
        assert entry.status is PromotionStatus.REJECTED
        assert entry.resolution_reason == outcome.reason
        assert entry.retry_count == 0

        # Repeat: NOOP, no new memory, ledger stays REJECTED.
        second = promoter.promote(compaction, project_id="proj-1")
        assert second.items[0].outcome is PromotionOutcome.NOOP
        assert second.items[0].reason == "already_rejected"
        assert len(memory_store.query(conversation_id=conversation_id)) == 0
        assert promotion_store.get("fact-1").status is PromotionStatus.REJECTED
    finally:
        promotion_store.close()
        memory_store.close()


# ======================================================================
# GROUP 4 — INELIGIBLE CATEGORIES
# ======================================================================


def test_group4_ineligible_categories(db_paths, conversation_id) -> None:
    conv_db, mem_db = db_paths
    compaction = seed_compaction(
        conv_db,
        conversation_id,
        summary="A durable project summary that must never become memory.",
        facts=(make_item("fact-1", "I use Ubuntu on my desktop.", (1, 2)),),
        decisions=(make_item("decision-1", "FRIDAY will persist memory in SQLite.", (3, 4)),),
        changes=(make_item("change-1", "Moved message storage to SQLite.", (4, 5)),),
        open_questions=(make_item("question-1", "Should promotion be automatic?", (6,)),),
    )

    promotion_store = SQLitePromotionStore(conv_db)
    memory_store = SQLiteMemoryStore(mem_db)
    manager = DurableMemoryManager(memory_store)
    resolver = MemoryResolver()
    counting_manager = CountingMemoryManager(manager)
    counting_resolver = CountingResolver(resolver)
    promoter = ConversationMemoryPromoter(promotion_store, counting_manager, counting_resolver)
    try:
        result = promoter.promote(compaction, project_id="proj-1")
        by_id = {r.item_id: r for r in result.items}

        assert by_id["fact-1"].outcome is PromotionOutcome.PROMOTED
        assert by_id["decision-1"].outcome is PromotionOutcome.PROMOTED
        assert by_id["change-1"].outcome is PromotionOutcome.SKIPPED
        assert by_id["change-1"].reason == "changes_not_promotable"
        assert by_id["question-1"].outcome is PromotionOutcome.SKIPPED
        assert by_id["question-1"].reason == "open_questions_not_promotable"

        # Ineligible categories never create ledger rows.
        assert promotion_store.get("change-1") is None
        assert promotion_store.get("question-1") is None
        assert promotion_store.get("fact-1").status is PromotionStatus.PROMOTED
        assert promotion_store.get("decision-1").status is PromotionStatus.PROMOTED

        # SUMMARY never becomes a CONVERSATION_SUMMARY memory.
        assert not any(m.type is MemoryType.CONVERSATION_SUMMARY for m in memory_store.query())
        assert not any("must never become memory" in m.content for m in memory_store.query())

        # The resolver was invoked exactly once (one coherent eligible batch).
        assert counting_resolver.calls == 1
        assert counting_manager.apply_calls == 1
        # Only the two eligible items produced memories.
        assert len(memory_store.query(conversation_id=conversation_id)) == 2
    finally:
        promotion_store.close()
        memory_store.close()


# ======================================================================
# GROUP 5 — PROJECT BOUNDARIES
# ======================================================================


def test_group5_user_fact_ignores_supplied_project_id(db_paths, conversation_id) -> None:
    conv_db, mem_db = db_paths
    compaction = seed_compaction(
        conv_db, conversation_id, facts=(make_item("fact-1", "I use Ubuntu on my desktop.", (1, 2)),)
    )
    promoter, promotion_store, memory_store = default_promoter(conv_db, mem_db)
    try:
        promoter.promote(compaction, project_id="proj-1")
        memory = memory_store.query(conversation_id=conversation_id)[0]
        assert memory.scope is MemoryScope.USER
        assert memory.project_id is None
    finally:
        promotion_store.close()
        memory_store.close()


def test_group5_project_fact_with_project_id(db_paths, conversation_id) -> None:
    conv_db, mem_db = db_paths
    compaction = seed_compaction(
        conv_db, conversation_id, facts=(make_item("fact-1", "FRIDAY uses Python 3.12.", (1, 2)),)
    )
    promoter, promotion_store, memory_store = default_promoter(conv_db, mem_db)
    try:
        promoter.promote(compaction, project_id="proj-1")
        memory = memory_store.query(conversation_id=conversation_id)[0]
        assert memory.scope is MemoryScope.PROJECT
        assert memory.project_id == "proj-1"
        assert memory.type is MemoryType.PROJECT_FACT
    finally:
        promotion_store.close()
        memory_store.close()


def test_group5_project_fact_without_project_id_rejected(db_paths, conversation_id) -> None:
    conv_db, mem_db = db_paths
    compaction = seed_compaction(
        conv_db, conversation_id, facts=(make_item("fact-1", "FRIDAY uses Python 3.12.", (1, 2)),)
    )
    promoter, promotion_store, memory_store = default_promoter(conv_db, mem_db)
    try:
        result = promoter.promote(compaction)
        assert result.items[0].outcome is PromotionOutcome.REJECTED
        assert result.items[0].reason == "project_fact_requires_project_id"
        assert memory_store.query() == []
        assert promotion_store.get("fact-1").status is PromotionStatus.REJECTED
    finally:
        promotion_store.close()
        memory_store.close()


def test_group5_project_decision_with_project_id(db_paths, conversation_id) -> None:
    conv_db, mem_db = db_paths
    compaction = seed_compaction(
        conv_db, conversation_id, decisions=(make_item("decision-1", "Use SQLite for compaction.", (3, 4)),)
    )
    promoter, promotion_store, memory_store = default_promoter(conv_db, mem_db)
    try:
        promoter.promote(compaction, project_id="proj-1")
        memory = memory_store.query(conversation_id=conversation_id)[0]
        assert memory.type is MemoryType.PROJECT_DECISION
        assert memory.scope is MemoryScope.PROJECT
        assert memory.project_id == "proj-1"
    finally:
        promotion_store.close()
        memory_store.close()


def test_group5_project_decision_without_project_id_rejected(db_paths, conversation_id) -> None:
    conv_db, mem_db = db_paths
    compaction = seed_compaction(
        conv_db, conversation_id, decisions=(make_item("decision-1", "Use SQLite for compaction.", (3, 4)),)
    )
    promoter, promotion_store, memory_store = default_promoter(conv_db, mem_db)
    try:
        result = promoter.promote(compaction)
        assert result.items[0].outcome is PromotionOutcome.REJECTED
        assert result.items[0].reason == "decision_requires_project_id"
        assert memory_store.query() == []
    finally:
        promotion_store.close()
        memory_store.close()


def test_group5_project_name_in_content_never_invents_project_id(db_paths, conversation_id) -> None:
    conv_db, mem_db = db_paths
    compaction = seed_compaction(
        conv_db,
        conversation_id,
        facts=(make_item("fact-1", "The project Phoenix uses Bazel.", (1, 2)),),
    )
    promoter, promotion_store, memory_store = default_promoter(conv_db, mem_db)
    try:
        result = promoter.promote(compaction)
        assert result.items[0].outcome is PromotionOutcome.REJECTED
        assert result.items[0].reason == "project_fact_requires_project_id"
        assert memory_store.query() == []
        assert promotion_store.get("fact-1").status is PromotionStatus.REJECTED
    finally:
        promotion_store.close()
        memory_store.close()


# ======================================================================
# GROUP 6 — PROVENANCE
# ======================================================================


def test_group6_provenance_propagation(db_paths, conversation_id) -> None:
    conv_db, mem_db = db_paths
    compaction = seed_compaction(
        conv_db,
        conversation_id,
        facts=(make_item("fact-1", "I use Ubuntu on my desktop.", (2, 5, 7)),),
    )
    promoter, promotion_store, memory_store = default_promoter(conv_db, mem_db)
    try:
        promoter.promote(compaction, project_id="proj-1")
        memory = memory_store.query(conversation_id=conversation_id)[0]
        # ConversationCompaction.conversation_id → MemoryCandidate → MemoryProvenance.
        assert memory.provenance.source_conversation_id == str(conversation_id)
        # CompactionItem.source_message_ids → MemoryCandidate → MemoryProvenance (as str).
        assert memory.provenance.source_message_ids == ("2", "5", "7")
        # No message content is duplicated into provenance.
        assert memory.content != "Message 2"
        assert not any(mid == memory.content for mid in memory.provenance.source_message_ids)
    finally:
        promotion_store.close()
        memory_store.close()


# ======================================================================
# GROUP 7 — IDEMPOTENT SUCCESS
# ======================================================================


def test_group7_idempotent_success(db_paths, conversation_id) -> None:
    conv_db, mem_db = db_paths
    compaction = seed_compaction(
        conv_db, conversation_id, facts=(make_item("fact-1", "I use Ubuntu on my desktop.", (1, 2)),)
    )

    promoter, promotion_store, memory_store = default_promoter(conv_db, mem_db)
    try:
        first = promoter.promote(compaction, project_id="proj-1")
        assert first.items[0].outcome is PromotionOutcome.PROMOTED
        assert len(memory_store.query(conversation_id=conversation_id)) == 1

        second = promoter.promote(compaction, project_id="proj-1")
        assert second.items[0].outcome is PromotionOutcome.NOOP
        assert second.items[0].reason == "already_promoted"

        assert len(memory_store.query(conversation_id=conversation_id)) == 1
        assert promotion_store.get("fact-1").status is PromotionStatus.PROMOTED
        assert len(promotion_store.list_for_compaction("comp-1")) == 1
    finally:
        promotion_store.close()
        memory_store.close()


# ======================================================================
# GROUP 8 — CRITICAL: MEMORY SUCCESS / LEDGER FAILURE
# ======================================================================


def test_group8_memory_success_ledger_failure_then_reconcile(db_paths, conversation_id) -> None:
    conv_db, mem_db = db_paths
    compaction = seed_compaction(
        conv_db, conversation_id, facts=(make_item("fact-1", "I use Ubuntu on my desktop.", (1, 2)),)
    )

    failing_store = FailpointPromotionStore(conv_db, fail_replace=True)
    memory_store = SQLiteMemoryStore(mem_db)
    manager = DurableMemoryManager(memory_store)
    promoter = ConversationMemoryPromoter(failing_store, manager, MemoryResolver())

    try:
        result = promoter.promote(compaction, project_id="proj-1")
        assert result.items[0].outcome is PromotionOutcome.FAILED

        # Memory commit succeeded and persists.
        memories = memory_store.query(conversation_id=conversation_id)
        assert len(memories) == 1
        memory = memories[0]
        assert memory.status is MemoryStatus.ACTIVE

        # Ledger reflects the failure: still PENDING (no PROMOTED persisted).
        entry = failing_store.get("fact-1")
        assert entry.status is PromotionStatus.PENDING

        # Compaction remains persisted.
        with SQLiteCompactionStore(conv_db) as store:
            assert store.get("comp-1") is not None

        # Retry with the ledger healthy again.
        failing_store.fail_replace = False
        retry = promoter.promote(compaction, project_id="proj-1")
        assert retry.items[0].outcome is PromotionOutcome.RECONCILED

        # Exactly ONE durable memory exists; no second CREATE.
        assert len(memory_store.query(conversation_id=conversation_id)) == 1
        assert memory_store.query(conversation_id=conversation_id)[0].id == memory.id

        # Ledger eventually records successful reconciliation as PROMOTED.
        entry = failing_store.get("fact-1")
        assert entry.status is PromotionStatus.PROMOTED
        assert entry.resolved_memory_ids == (memory.id,)
    finally:
        failing_store.close()
        memory_store.close()


# ======================================================================
# GROUP 9 — MEMORY FAILURE / LEDGER FAILURE ISOLATION
# ======================================================================


def test_group9_memory_failure_isolation_then_recovery(db_paths, conversation_id) -> None:
    conv_db, mem_db = db_paths
    compaction = seed_compaction(
        conv_db, conversation_id, facts=(make_item("fact-1", "I use Ubuntu on my desktop.", (1, 2)),)
    )

    promotion_store = SQLitePromotionStore(conv_db)
    memory_store = SQLiteMemoryStore(mem_db)
    manager = FailpointMemoryManager(DurableMemoryManager(memory_store))
    promoter = ConversationMemoryPromoter(promotion_store, manager, MemoryResolver())

    try:
        manager.fail_apply = True
        result = promoter.promote(compaction, project_id="proj-1")
        assert result.items[0].outcome is PromotionOutcome.FAILED
        assert result.items[0].reason.startswith("memory_application_failed")

        # No partial writes.
        assert memory_store.query() == []
        # Ledger stays PENDING with retry recorded.
        entry = promotion_store.get("fact-1")
        assert entry.status is PromotionStatus.PENDING
        assert entry.retry_count == 1
        assert entry.last_error is not None
        # Not REJECTED, not PROMOTED.
        assert entry.status is not PromotionStatus.REJECTED
        # Compaction still persisted.
        with SQLiteCompactionStore(conv_db) as store:
            assert store.get("comp-1") is not None

        # Restore and retry → success.
        manager.fail_apply = False
        retry = promoter.promote(compaction, project_id="proj-1")
        assert retry.items[0].outcome is PromotionOutcome.PROMOTED
        assert len(memory_store.query(conversation_id=conversation_id)) == 1
        assert promotion_store.get("fact-1").status is PromotionStatus.PROMOTED
    finally:
        promotion_store.close()
        memory_store.close()


# ======================================================================
# GROUP 10 — APPLY_BATCH ATOMICITY
# ======================================================================


def test_group10_apply_batch_atomicity(db_paths, conversation_id) -> None:
    conv_db, mem_db = db_paths
    compaction = seed_compaction(
        conv_db,
        conversation_id,
        facts=(
            make_item("fact-1", "I use Ubuntu on my desktop.", (1, 2)),
            make_item("fact-2", "I use Arch on my laptop.", (2, 3)),
        ),
    )

    memory_store = SQLiteMemoryStore(mem_db)
    failing_storage = StorageSaveFailpoint(memory_store, fail_after=1)
    manager = DurableMemoryManager(failing_storage)
    promotion_store = SQLitePromotionStore(conv_db)
    promoter = ConversationMemoryPromoter(promotion_store, manager, MemoryResolver())

    try:
        result = promoter.promote(compaction, project_id="proj-1")
        assert all(r.outcome is PromotionOutcome.FAILED for r in result.items)

        # Mid-batch failure rolls the whole batch back: zero partial writes.
        assert memory_store.query() == []

        # Affected ledger entries stay PENDING with transient failures recorded.
        for item_id in ("fact-1", "fact-2"):
            entry = promotion_store.get(item_id)
            assert entry.status is PromotionStatus.PENDING
            assert entry.retry_count == 1
            assert entry.last_error.startswith("memory_application_failed")

        # Retry with the failure removed: all valid candidates promote, no dups.
        failing_storage.fail_after = None
        retry = promoter.promote(compaction, project_id="proj-1")
        assert all(r.outcome is PromotionOutcome.PROMOTED for r in retry.items)
        memories = memory_store.query(conversation_id=conversation_id)
        assert len(memories) == 2
        assert {m.content for m in memories} == {
            "I use Ubuntu on my desktop.",
            "I use Arch on my laptop.",
        }
        assert promotion_store.get("fact-1").status is PromotionStatus.PROMOTED
        assert promotion_store.get("fact-2").status is PromotionStatus.PROMOTED
    finally:
        promotion_store.close()
        memory_store.close()


# ======================================================================
# GROUP 11 — MULTIPLE ITEMS
# ======================================================================


def test_group11_multiple_items_independent_outcomes(db_paths, conversation_id) -> None:
    conv_db, mem_db = db_paths
    rejected_content = "FRIDAY uses SQLite for compaction storage."
    seed_memory(
        mem_db,
        Memory(
            type=MemoryType.PROJECT_FACT,
            scope=MemoryScope.PROJECT,
            content=rejected_content,
            id="mem-existing",
            project_id="proj-1",
        ),
    )

    compaction = seed_compaction(
        conv_db,
        conversation_id,
        facts=(
            make_item("fact-1", "I use Ubuntu on my desktop.", (1, 2)),
            make_item("fact-2", rejected_content, (2, 3)),
        ),
        decisions=(make_item("decision-1", "Deploy the service stack as containers.", (3, 4)),),
        changes=(make_item("change-1", "Moved storage to SQLite.", (4, 5)),),
        open_questions=(make_item("question-1", "Automatic promotion?", (6,)),),
    )

    memory_store = SQLiteMemoryStore(mem_db)
    manager = DurableMemoryManager(memory_store)
    promotion_store = SQLitePromotionStore(conv_db)
    resolver = MemoryResolver()
    counting_resolver = CountingResolver(resolver)
    counting_manager = CountingMemoryManager(manager)
    promoter = ConversationMemoryPromoter(promotion_store, counting_manager, counting_resolver)

    try:
        result = promoter.promote(compaction, project_id="proj-1")
        assert [r.item_id for r in result.items] == [
            "fact-1",
            "fact-2",
            "decision-1",
            "change-1",
            "question-1",
        ]
        by_id = {r.item_id: r for r in result.items}
        assert by_id["fact-1"].outcome is PromotionOutcome.PROMOTED
        assert by_id["fact-2"].outcome is PromotionOutcome.REJECTED
        assert by_id["decision-1"].outcome is PromotionOutcome.PROMOTED
        assert by_id["change-1"].outcome is PromotionOutcome.SKIPPED
        assert by_id["question-1"].outcome is PromotionOutcome.SKIPPED

        # One coherent batch for all eligible resolutions.
        assert counting_resolver.calls == 1
        assert counting_manager.apply_calls == 1

        # Independent persistence.
        assert len(memory_store.query(conversation_id=conversation_id)) == 2
        assert promotion_store.get("fact-1").status is PromotionStatus.PROMOTED
        assert promotion_store.get("fact-2").status is PromotionStatus.REJECTED
        assert promotion_store.get("decision-1").status is PromotionStatus.PROMOTED
        assert promotion_store.get("change-1") is None
        assert promotion_store.get("question-1") is None
        assert memory_store.get("mem-existing").status is MemoryStatus.ACTIVE
    finally:
        promotion_store.close()
        memory_store.close()


# ======================================================================
# GROUP 12 — CONCURRENT / REPEATED PROMOTION
# ======================================================================


class BarrierPromotionStore(SQLitePromotionStore):
    """Ledger store that waits AFTER get() so both threads observe None before
    either one saves (deterministically forces the both-saw-None race)."""

    def __init__(self, db_path: Path, barrier: threading.Barrier) -> None:
        super().__init__(db_path)
        self._barrier = barrier

    def get(self, item_id: str) -> CompactionPromotion | None:
        result = super().get(item_id)
        self._barrier.wait(timeout=10)
        return result


def _promote_in_thread(
    conv_db: Path,
    mem_db: Path,
    compaction: ConversationCompaction,
    barrier: threading.Barrier,
    results: list,
    errors: list,
) -> None:
    try:
        promotion_store = BarrierPromotionStore(conv_db, barrier)
        memory_store = SQLiteMemoryStore(mem_db)
        manager = DurableMemoryManager(memory_store)
        promoter = ConversationMemoryPromoter(promotion_store, manager, MemoryResolver())
        results.append(promoter.promote(compaction, project_id="proj-1"))
        promotion_store.close()
        memory_store.close()
    except Exception as exc:  # noqa: BLE001 - collected for assertion below
        errors.append(exc)


def test_group12_repeated_promotion_across_instances(db_paths, conversation_id) -> None:
    conv_db, mem_db = db_paths
    compaction = seed_compaction(
        conv_db, conversation_id, facts=(make_item("fact-1", "I use Ubuntu on my desktop.", (1, 2)),)
    )

    promoter_a, promotion_store_a, memory_store_a = default_promoter(conv_db, mem_db)
    try:
        first = promoter_a.promote(compaction, project_id="proj-1")
        assert first.items[0].outcome is PromotionOutcome.PROMOTED
    finally:
        promotion_store_a.close()
        memory_store_a.close()

    # A brand-new promoter instance sees the committed PROMOTED state → NOOP.
    promoter_b, promotion_store_b, memory_store_b = default_promoter(conv_db, mem_db)
    try:
        second = promoter_b.promote(compaction, project_id="proj-1")
        assert second.items[0].outcome is PromotionOutcome.NOOP
        assert len(memory_store_b.query(conversation_id=conversation_id)) == 1
        assert len(promotion_store_b.list_for_compaction("comp-1")) == 1
    finally:
        promotion_store_b.close()
        memory_store_b.close()


def test_group12_concurrent_ledger_save_is_authoritative(db_paths, conversation_id) -> None:
    conv_db, _mem_db = db_paths
    seed_compaction(conv_db, conversation_id, facts=(make_item("fact-1", "I use Ubuntu.", (1, 2)),))
    promotion = CompactionPromotion.pending(
        item_id="fact-1", compaction_id="comp-1", category=CompactionItemCategory.FACTS
    )

    # Pre-create the promotion tables so the threads race only on the INSERT.
    with SQLitePromotionStore(conv_db):
        pass

    barrier = threading.Barrier(2)
    outcomes: list[bool] = []
    errors: list[Exception] = []

    def save_once() -> None:
        barrier.wait(timeout=10)
        try:
            with SQLitePromotionStore(conv_db) as store:
                store.save(promotion)
                outcomes.append(True)
        except PromotionAlreadyExistsError as exc:
            errors.append(exc)

    threads = [threading.Thread(target=save_once) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(outcomes) == 1
    assert len(errors) == 1
    assert isinstance(errors[0], PromotionAlreadyExistsError)

    with SQLitePromotionStore(conv_db) as store:
        assert len(store.list_for_compaction("comp-1")) == 1


def test_group12_concurrent_promote_race_has_no_duplicates(db_paths, conversation_id) -> None:
    conv_db, mem_db = db_paths
    compaction = seed_compaction(
        conv_db, conversation_id, facts=(make_item("fact-1", "I use Ubuntu on my desktop.", (1, 2)),)
    )

    # Both databases already exist with full schema in production; initialize
    # them up front so the threads race only on the promotion ledger, not on
    # first-run schema creation.
    with SQLitePromotionStore(conv_db) as promotion_store:
        assert promotion_store is not None
    with SQLiteMemoryStore(mem_db) as memory_store:
        assert memory_store is not None

    barrier = threading.Barrier(2)
    results: list = []
    errors: list[Exception] = []
    threads = [
        threading.Thread(
            target=_promote_in_thread, args=(conv_db, mem_db, compaction, barrier, results, errors)
        )
        for _ in range(2)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    # The both-saw-None race is resolved by the ledger PRIMARY KEY: exactly one
    # thread wins the save; the loser raises PromotionAlreadyExistsError and
    # never writes memory.
    assert len(results) == 1
    assert len(errors) == 1
    assert isinstance(errors[0], PromotionAlreadyExistsError)
    assert results[0].items[0].outcome is PromotionOutcome.PROMOTED

    with SQLitePromotionStore(conv_db) as store:
        entries = store.list_for_compaction("comp-1")
        assert len(entries) == 1
        assert entries[0].status is PromotionStatus.PROMOTED
    with SQLiteMemoryStore(mem_db) as store:
        memories = store.query(conversation_id=conversation_id)
        assert len(memories) == 1
        assert memories[0].status is MemoryStatus.ACTIVE


# ======================================================================
# GROUP 13 — CRASH-STYLE INTERRUPTIONS
# ======================================================================


def test_group13_boundary_a_before_memory_write(db_paths, conversation_id) -> None:
    """A: failure before any memory write."""
    conv_db, mem_db = db_paths
    compaction = seed_compaction(
        conv_db, conversation_id, facts=(make_item("fact-1", "I use Ubuntu on my desktop.", (1, 2)),)
    )
    promotion_store = SQLitePromotionStore(conv_db)
    memory_store = SQLiteMemoryStore(mem_db)
    manager = FailpointMemoryManager(DurableMemoryManager(memory_store))
    promoter = ConversationMemoryPromoter(promotion_store, manager, MemoryResolver())
    try:
        manager.fail_apply = True
        promoter.promote(compaction, project_id="proj-1")
        assert memory_store.query() == []
        entry = promotion_store.get("fact-1")
        assert entry.status is PromotionStatus.PENDING
        assert entry.retry_count == 1

        manager.fail_apply = False
        retry = promoter.promote(compaction, project_id="proj-1")
        assert retry.items[0].outcome is PromotionOutcome.PROMOTED
        assert len(memory_store.query(conversation_id=conversation_id)) == 1
    finally:
        promotion_store.close()
        memory_store.close()


def test_group13_boundary_b_during_memory_batch(db_paths, conversation_id) -> None:
    """B: failure inside the memory batch rolls the batch back."""
    conv_db, mem_db = db_paths
    compaction = seed_compaction(
        conv_db,
        conversation_id,
        facts=(
            make_item("fact-1", "I use Ubuntu on my desktop.", (1, 2)),
            make_item("fact-2", "I use Arch on my laptop.", (2, 3)),
        ),
    )
    memory_store = SQLiteMemoryStore(mem_db)
    failing_storage = StorageSaveFailpoint(memory_store, fail_after=1)
    promotion_store = SQLitePromotionStore(conv_db)
    promoter = ConversationMemoryPromoter(
        promotion_store, DurableMemoryManager(failing_storage), MemoryResolver()
    )
    try:
        promoter.promote(compaction, project_id="proj-1")
        assert memory_store.query() == []  # full rollback, no partial writes
        for item_id in ("fact-1", "fact-2"):
            assert promotion_store.get(item_id).status is PromotionStatus.PENDING

        failing_storage.fail_after = None
        retry = promoter.promote(compaction, project_id="proj-1")
        assert all(r.outcome is PromotionOutcome.PROMOTED for r in retry.items)
        assert len(memory_store.query(conversation_id=conversation_id)) == 2
    finally:
        promotion_store.close()
        memory_store.close()


def test_group13_boundary_c_d_after_memory_commit_before_during_ledger_update(
    db_paths, conversation_id
) -> None:
    """C/D: memory committed, ledger update fails → PENDING; retry reconciles."""
    conv_db, mem_db = db_paths
    compaction = seed_compaction(
        conv_db, conversation_id, facts=(make_item("fact-1", "I use Ubuntu on my desktop.", (1, 2)),)
    )
    failing_store = FailpointPromotionStore(conv_db, fail_replace=True)
    memory_store = SQLiteMemoryStore(mem_db)
    promoter = ConversationMemoryPromoter(failing_store, DurableMemoryManager(memory_store), MemoryResolver())
    try:
        result = promoter.promote(compaction, project_id="proj-1")
        assert result.items[0].outcome is PromotionOutcome.FAILED
        assert len(memory_store.query(conversation_id=conversation_id)) == 1
        assert failing_store.get("fact-1").status is PromotionStatus.PENDING

        failing_store.fail_replace = False
        retry = promoter.promote(compaction, project_id="proj-1")
        assert retry.items[0].outcome is PromotionOutcome.RECONCILED
        assert len(memory_store.query(conversation_id=conversation_id)) == 1
        assert failing_store.get("fact-1").status is PromotionStatus.PROMOTED
    finally:
        failing_store.close()
        memory_store.close()


def test_group13_boundary_e_after_ledger_promoted_persisted(db_paths, conversation_id) -> None:
    """E: fully committed → retry is NOOP; no duplicate possible."""
    conv_db, mem_db = db_paths
    compaction = seed_compaction(
        conv_db, conversation_id, facts=(make_item("fact-1", "I use Ubuntu on my desktop.", (1, 2)),)
    )
    promoter, promotion_store, memory_store = default_promoter(conv_db, mem_db)
    try:
        first = promoter.promote(compaction, project_id="proj-1")
        assert first.items[0].outcome is PromotionOutcome.PROMOTED
        memory_count = len(memory_store.query(conversation_id=conversation_id))

        second = promoter.promote(compaction, project_id="proj-1")
        assert second.items[0].outcome is PromotionOutcome.NOOP
        assert len(memory_store.query(conversation_id=conversation_id)) == memory_count
        assert promotion_store.get("fact-1").status is PromotionStatus.PROMOTED
    finally:
        promotion_store.close()
        memory_store.close()


# ======================================================================
# GROUP 14 — IMMUTABILITY
# ======================================================================


def test_group14_promotion_does_not_mutate(db_paths, conversation_id) -> None:
    conv_db, mem_db = db_paths
    compaction = seed_compaction(
        conv_db,
        conversation_id,
        facts=(
            make_item("fact-1", "I use Ubuntu on my desktop.", (1, 2)),
            make_item("fact-2", "FRIDAY uses Python 3.12.", (2, 3)),
        ),
        decisions=(make_item("decision-1", "Use SQLite for compaction.", (3, 4)),),
    )
    before_items = {
        item.item_id: item
        for item in (*compaction.facts, *compaction.decisions, *compaction.changes)
    }
    before_messages = None
    with SQLiteConversationStore(conv_db) as store:
        before_messages = store.get_recent_messages(conversation_id, limit=100)

    promoter, promotion_store, memory_store = default_promoter(conv_db, mem_db)
    try:
        promoter.promote(compaction, project_id="proj-1")

        for item in (*compaction.facts, *compaction.decisions, *compaction.changes):
            assert item == before_items[item.item_id]
            assert item.source_message_ids == before_items[item.item_id].source_message_ids
        assert compaction.summary == "The conversation covered setup and design."

        with SQLiteConversationStore(conv_db) as store:
            after_messages = store.get_recent_messages(conversation_id, limit=100)
        assert after_messages == before_messages

        # Persisted compaction record is byte-identical to the original domain object.
        with SQLiteCompactionStore(conv_db) as store:
            persisted = store.get("comp-1")
        assert persisted == compaction
    finally:
        promotion_store.close()
        memory_store.close()


# ======================================================================
# GROUP 15 — FAILURE ISOLATION
# ======================================================================


def test_group15_failures_isolated_from_conversation_state(db_paths, conversation_id, tmp_path) -> None:
    conv_db, mem_db = db_paths
    compaction = seed_compaction(
        conv_db, conversation_id, facts=(make_item("fact-1", "I use Ubuntu on my desktop.", (1, 2)),)
    )
    with SQLiteConversationStore(conv_db) as store:
        before_messages = store.get_recent_messages(conversation_id, limit=100)

    failing_store = FailpointPromotionStore(conv_db, fail_replace=True)
    memory_store = SQLiteMemoryStore(mem_db)
    promoter = ConversationMemoryPromoter(failing_store, DurableMemoryManager(memory_store), MemoryResolver())
    try:
        # A hard ledger failure mid-promotion.
        result = promoter.promote(compaction, project_id="proj-1")
        assert result.items[0].outcome is PromotionOutcome.FAILED

        # Raw messages untouched.
        with SQLiteConversationStore(conv_db) as store:
            assert store.get_recent_messages(conversation_id, limit=100) == before_messages
        # Compaction not deleted; boundary not moved (still exactly one compaction).
        with SQLiteCompactionStore(conv_db) as store:
            assert store.get("comp-1") is not None
            assert [c.compaction_id for c in store.list_for_conversation(conversation_id)] == ["comp-1"]
        # No arbitrary files written outside the two databases.
        assert sorted(os.listdir(tmp_path)) == sorted(["conversations.db", "memory.db"])
    finally:
        failing_store.close()
        memory_store.close()


# ======================================================================
# GROUP 17 — PERSISTENCE REOPEN
# ======================================================================


def test_group17_reopen_pending_state(db_paths, conversation_id) -> None:
    conv_db, _mem_db = db_paths
    seed_compaction(conv_db, conversation_id, facts=(make_item("fact-1", "I use Ubuntu.", (1, 2)),))
    pending = CompactionPromotion.pending(
        item_id="fact-1", compaction_id="comp-1", category=CompactionItemCategory.FACTS
    )
    with SQLitePromotionStore(conv_db) as store:
        store.save(pending)

    with SQLitePromotionStore(conv_db) as store:
        loaded = store.get("fact-1")
    assert loaded.status is PromotionStatus.PENDING
    assert loaded.compaction_id == "comp-1"
    assert loaded.retry_count == 0


def test_group17_reopen_promoted_state(db_paths, conversation_id) -> None:
    conv_db, mem_db = db_paths
    compaction = seed_compaction(
        conv_db, conversation_id, facts=(make_item("fact-1", "I use Ubuntu on my desktop.", (1, 2)),)
    )
    promoter, promotion_store, memory_store = default_promoter(conv_db, mem_db)
    try:
        result = promoter.promote(compaction, project_id="proj-1")
        memory_id = result.items[0].memory_ids[0]
    finally:
        promotion_store.close()
        memory_store.close()

    with SQLitePromotionStore(conv_db) as store:
        entry = store.get("fact-1")
        assert entry.status is PromotionStatus.PROMOTED
        assert entry.resolved_memory_ids == (memory_id,)
    with SQLiteMemoryStore(mem_db) as store:
        memory = store.get(memory_id)
        assert memory.status is MemoryStatus.ACTIVE
        assert memory.provenance.source_conversation_id == str(conversation_id)


def test_group17_reopen_rejected_state(db_paths, conversation_id) -> None:
    conv_db, mem_db = db_paths
    compaction = seed_compaction(
        conv_db, conversation_id, decisions=(make_item("decision-1", "Use SQLite.", (3, 4)),)
    )
    promoter, promotion_store, memory_store = default_promoter(conv_db, mem_db)
    try:
        result = promoter.promote(compaction)
        assert result.items[0].outcome is PromotionOutcome.REJECTED
    finally:
        promotion_store.close()
        memory_store.close()

    with SQLitePromotionStore(conv_db) as store:
        entry = store.get("decision-1")
        assert entry.status is PromotionStatus.REJECTED
        assert entry.resolution_reason == "decision_requires_project_id"
    with SQLiteMemoryStore(mem_db) as store:
        assert store.query() == []


def test_group17_reopen_reconciled_state_persists_as_promoted(db_paths, conversation_id) -> None:
    conv_db, mem_db = db_paths
    compaction = seed_compaction(
        conv_db, conversation_id, facts=(make_item("fact-1", "I use Ubuntu on my desktop.", (1, 2)),)
    )
    existing = Memory(
        type=MemoryType.USER_FACT,
        scope=MemoryScope.USER,
        content="I use Ubuntu on my desktop.",
        id="mem-reconciled",
        provenance=MemoryProvenance(
            source_conversation_id=str(conversation_id), source_message_ids=("1", "2")
        ),
    )
    seed_memory(mem_db, existing)

    promoter, promotion_store, memory_store = default_promoter(conv_db, mem_db)
    try:
        result = promoter.promote(compaction, project_id="proj-1")
        assert result.items[0].outcome is PromotionOutcome.RECONCILED
    finally:
        promotion_store.close()
        memory_store.close()

    # RECONCILED is a runtime outcome; it persists as the PROMOTED ledger state.
    with SQLitePromotionStore(conv_db) as store:
        entry = store.get("fact-1")
        assert entry.status is PromotionStatus.PROMOTED
        assert entry.resolved_memory_ids == ("mem-reconciled",)
    with SQLiteMemoryStore(mem_db) as store:
        assert len(store.query()) == 1
        assert store.get("mem-reconciled").status is MemoryStatus.ACTIVE