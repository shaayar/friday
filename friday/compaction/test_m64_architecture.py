"""M6.4 architecture-level tests (Phase 4, ADR-025).

Covers:
- group 16: the promotion path has no unexpected dependencies.
- group 18: corrupted ledger/memory data raises typed errors, never silently
  valid-looking objects.
- group 19: architectural invariants (separation of the two databases,
  promotion policy, no invented abstractions, no cross-DB transaction).
"""

from __future__ import annotations

import inspect
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from friday.compaction.exceptions import PromotionCorruptError
from friday.compaction.models import CompactionItem, ConversationCompaction
from friday.compaction.promotion import CompactionItemCategory, CompactionPromotion
from friday.compaction.promotion_store import SQLitePromotionStore
from friday.compaction.sqlite_store import SQLiteCompactionStore
from friday.memory.exceptions import MemoryCorruptError
from friday.memory.models import Memory, MemoryScope, MemoryType
from friday.memory.sqlite_memory_store import SQLiteMemoryStore
from friday.memory.sqlite_store import SQLiteConversationStore

FIXED_NOW = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)


def make_item(
    item_id: str, content: str, source_message_ids: tuple[int, ...]
) -> CompactionItem:
    return CompactionItem(
        item_id=item_id, content=content, source_message_ids=source_message_ids
    )


def make_compaction(
    *,
    conversation_id: int,
    compaction_id: str = "comp-1",
    facts: tuple[CompactionItem, ...] = (),
    **_: object,
) -> ConversationCompaction:
    return ConversationCompaction(
        compaction_id=compaction_id,
        conversation_id=conversation_id,
        first_message_id=1,
        last_message_id=10,
        created_at=FIXED_NOW,
        facts=facts,
    )


def seed_conversation(conv_db: Path) -> int:
    with SQLiteConversationStore(conv_db) as store:
        conversation = store.create_conversation()
        for index in range(1, 11):
            store.save_message(conversation.id, "user", f"Message {index}")
        return conversation.id


def seed_compaction(
    conv_db: Path, conversation_id: int, **overrides
) -> ConversationCompaction:
    with SQLiteCompactionStore(conv_db) as store:
        compaction = make_compaction(conversation_id=conversation_id, **overrides)
        store.save(compaction)
    return compaction


PROMOTION_PATH_MODULES = (
    "friday.compaction.promoter",
    "friday.compaction.promotion_store",
    "friday.compaction.promotion",
    "friday.compaction.sqlite_store",
)


def _module_source(module_name: str) -> str:
    import importlib

    return inspect.getsource(importlib.import_module(module_name))


# ======================================================================
# GROUP 16 — NO UNEXPECTED DEPENDENCIES
# ======================================================================


@pytest.mark.parametrize("module_name", PROMOTION_PATH_MODULES)
def test_group16_promotion_path_has_no_unexpected_dependencies(
    module_name: str,
) -> None:
    source = _module_source(module_name)
    for forbidden in (
        "livekit",
        "agent_friday",
        "friday.context",
        "ContextManager",
        "opencode",
        "hermes",
        "browser",
        "selenium",
        "playwright",
        "requests",
        "httpx",
        "urllib.request",
        "socket",
    ):
        assert forbidden not in source, (
            f"{module_name} references forbidden token {forbidden!r}"
        )


def test_group16_promotion_is_explicit_local_operation(tmp_path: Path) -> None:
    conv_db = tmp_path / "conversations.db"
    mem_db = tmp_path / "memory.db"
    conversation_id = seed_conversation(conv_db)
    compaction = seed_compaction(
        conv_db, conversation_id, facts=(make_item("fact-1", "I use Ubuntu.", (1, 2)),)
    )

    from friday.compaction.promoter import ConversationMemoryPromoter
    from friday.memory.durable_manager import DurableMemoryManager
    from friday.memory.resolver import MemoryResolver

    with (
        SQLitePromotionStore(conv_db) as promotion_store,
        SQLiteMemoryStore(mem_db) as memory_store,
    ):
        promoter = ConversationMemoryPromoter(
            promotion_store, DurableMemoryManager(memory_store), MemoryResolver()
        )
        result = promoter.promote(compaction, project_id="proj-1")
        assert result.items[0].outcome.value == "promoted"

    # No network, no external service: only the two local databases exist.
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "conversations.db",
        "memory.db",
    ]


# ======================================================================
# GROUP 18 — DATA CORRUPTION
# ======================================================================


def _seed_valid_pending(conv_db: Path, conversation_id: int) -> None:
    seed_compaction(
        conv_db, conversation_id, facts=(make_item("fact-1", "I use Ubuntu.", (1, 2)),)
    )
    with SQLitePromotionStore(conv_db) as store:
        store.save(
            CompactionPromotion.pending(
                item_id="fact-1",
                compaction_id="comp-1",
                category=CompactionItemCategory.FACTS,
                created_at=FIXED_NOW,
            )
        )


def _corrupt(conv_db: Path, item_id: str, **fields) -> None:
    """Bypass CHECK constraints deliberately and inject a corrupt value."""
    conn = sqlite3.connect(conv_db)
    try:
        conn.execute("PRAGMA ignore_check_constraints = ON")
        sets = ", ".join(f"{column} = ?" for column in fields)
        conn.execute(
            f"UPDATE compaction_promotions SET {sets} WHERE item_id = ?",
            (*fields.values(), item_id),
        )
        conn.commit()
    finally:
        conn.close()


def test_group18_corrupt_status(tmp_path: Path) -> None:
    conv_db = tmp_path / "conversations.db"
    _seed_valid_pending(conv_db, seed_conversation(conv_db))
    _corrupt(conv_db, "fact-1", status="bogus")

    with SQLitePromotionStore(conv_db) as store, pytest.raises(PromotionCorruptError):
        store.get("fact-1")


def test_group18_corrupt_category(tmp_path: Path) -> None:
    conv_db = tmp_path / "conversations.db"
    _seed_valid_pending(conv_db, seed_conversation(conv_db))
    _corrupt(conv_db, "fact-1", category="facts-but-not")

    with SQLitePromotionStore(conv_db) as store, pytest.raises(PromotionCorruptError):
        store.get("fact-1")


def test_group18_corrupt_resolution_kind(tmp_path: Path) -> None:
    conv_db = tmp_path / "conversations.db"
    _seed_valid_pending(conv_db, seed_conversation(conv_db))
    _corrupt(conv_db, "fact-1", resolution_kind="upsert")

    with SQLitePromotionStore(conv_db) as store, pytest.raises(PromotionCorruptError):
        store.get("fact-1")


def test_group18_corrupt_memory_id(tmp_path: Path) -> None:
    conv_db = tmp_path / "conversations.db"
    _seed_valid_pending(conv_db, seed_conversation(conv_db))
    _corrupt(conv_db, "fact-1", status="promoted")
    _corrupt(conv_db, "fact-1", resolution_kind="create")
    conn = sqlite3.connect(conv_db)
    try:
        conn.execute("PRAGMA ignore_check_constraints = ON")
        conn.execute(
            "INSERT INTO promotion_resolved_memory_ids (item_id, memory_id, ordinal) VALUES (?, ?, ?)",
            ("fact-1", "", 0),
        )
        conn.commit()
    finally:
        conn.close()

    with SQLitePromotionStore(conv_db) as store, pytest.raises(PromotionCorruptError):
        store.get("fact-1")


def test_group18_corrupt_timestamp(tmp_path: Path) -> None:
    conv_db = tmp_path / "conversations.db"
    _seed_valid_pending(conv_db, seed_conversation(conv_db))
    _corrupt(conv_db, "fact-1", updated_at="not-a-date")

    with SQLitePromotionStore(conv_db) as store, pytest.raises(PromotionCorruptError):
        store.get("fact-1")


def test_group18_corrupt_retry_count(tmp_path: Path) -> None:
    conv_db = tmp_path / "conversations.db"
    _seed_valid_pending(conv_db, seed_conversation(conv_db))
    _corrupt(conv_db, "fact-1", retry_count=-5)

    with SQLitePromotionStore(conv_db) as store, pytest.raises(PromotionCorruptError):
        store.get("fact-1")


def test_group18_corrupt_promoted_without_memory_ids(tmp_path: Path) -> None:
    conv_db = tmp_path / "conversations.db"
    _seed_valid_pending(conv_db, seed_conversation(conv_db))
    _corrupt(conv_db, "fact-1", status="promoted")

    with SQLitePromotionStore(conv_db) as store, pytest.raises(PromotionCorruptError):
        store.get("fact-1")


def test_group18_corrupt_memory_row_raises_memory_corrupt(tmp_path: Path) -> None:
    mem_db = tmp_path / "memory.db"
    with SQLiteMemoryStore(mem_db) as store:
        store.save(
            Memory(
                type=MemoryType.USER_FACT,
                scope=MemoryScope.USER,
                content="I use Ubuntu.",
                id="mem-1",
            )
        )
    conn = sqlite3.connect(mem_db)
    try:
        conn.execute("PRAGMA ignore_check_constraints = ON")
        conn.execute("UPDATE memories SET status = 'gone' WHERE id = 'mem-1'")
        conn.commit()
    finally:
        conn.close()

    with SQLiteMemoryStore(mem_db) as store, pytest.raises(MemoryCorruptError):
        store.get("mem-1")


# ======================================================================
# GROUP 19 — ARCHITECTURAL INVARIANTS
# ======================================================================


def test_group19_compaction_store_never_imports_memory_db() -> None:
    source = _module_source("friday.compaction.sqlite_store")
    assert "sqlite_memory_store" not in source
    assert "SQLiteMemoryStore" not in source
    assert "friday.memory" not in source


def test_group19_promotion_store_never_imports_memory_db() -> None:
    source = _module_source("friday.compaction.promotion_store")
    assert "sqlite_memory_store" not in source
    assert "SQLiteMemoryStore" not in source
    assert "friday.memory" not in source


def test_group19_memory_store_never_imports_conversations_db() -> None:
    source = _module_source("friday.memory.sqlite_memory_store")
    assert "friday.compaction" not in source
    assert "SQLiteCompactionStore" not in source
    assert "SQLitePromotionStore" not in source


def test_group19_compaction_does_not_create_memory_db(tmp_path: Path) -> None:
    conv_db = tmp_path / "conversations.db"
    mem_db = tmp_path / "memory.db"
    conversation_id = seed_conversation(conv_db)
    with SQLiteCompactionStore(conv_db) as store:
        store.save(
            make_compaction(
                conversation_id=conversation_id,
                facts=(make_item("fact-1", "I use Ubuntu.", (1, 2)),),
            )
        )
    assert not mem_db.exists()


def test_group19_promotion_store_does_not_create_memory_db(tmp_path: Path) -> None:
    conv_db = tmp_path / "conversations.db"
    mem_db = tmp_path / "memory.db"
    conversation_id = seed_conversation(conv_db)
    seed_compaction(
        conv_db, conversation_id, facts=(make_item("fact-1", "I use Ubuntu.", (1, 2)),)
    )
    with SQLitePromotionStore(conv_db) as store:
        store.save(
            CompactionPromotion.pending(
                item_id="fact-1",
                compaction_id="comp-1",
                category=CompactionItemCategory.FACTS,
            )
        )
    assert not mem_db.exists()


def test_group19_memory_store_does_not_create_conversations_db(tmp_path: Path) -> None:
    conv_db = tmp_path / "conversations.db"
    mem_db = tmp_path / "memory.db"
    with SQLiteMemoryStore(mem_db) as store:
        store.save(
            Memory(type=MemoryType.USER_FACT, scope=MemoryScope.USER, content="X.")
        )
    assert not conv_db.exists()


def test_group19_promoter_uses_memory_resolver() -> None:
    source = _module_source("friday.compaction.promoter")
    assert "resolve(" in source
    assert "MemoryCandidate" in source


def test_group19_promoter_uses_durable_memory_manager() -> None:
    source = _module_source("friday.compaction.promoter")
    assert "apply_batch" in source
    assert "get_active" in source


def test_group19_summary_never_converted_to_conversation_summary() -> None:
    source = _module_source("friday.compaction.promoter")
    assert "CONVERSATION_SUMMARY" not in source


def test_group19_changes_not_automatically_promoted() -> None:
    source = _module_source("friday.compaction.promoter")
    assert "changes_not_promotable" in source


def test_group19_open_questions_not_promoted() -> None:
    source = _module_source("friday.compaction.promoter")
    assert "open_questions_not_promotable" in source


def test_group19_decisions_require_project_id() -> None:
    source = _module_source("friday.compaction.promoter")
    assert "decision_requires_project_id" in source


def test_group19_project_id_never_derived_from_content() -> None:
    source = _module_source("friday.compaction.promoter")
    # The only project_id source is the caller-supplied parameter; nothing
    # derives it from content or an LLM.
    assert "project_id: str | None = None" in source
    assert "LLMBackend" not in source
    assert "friday.ai" not in source
    assert "infer_project" not in source


def test_group19_confidence_starts_explicit_and_never_inferred() -> None:
    source = _module_source("friday.compaction.promoter")
    assert "MemoryConfidence.EXPLICIT" in source
    assert "INFERRED" not in source


def test_group19_compaction_immutable_domain() -> None:
    import dataclasses

    assert dataclasses.is_dataclass(ConversationCompaction)
    assert dataclasses.is_dataclass(CompactionItem)
    assert ConversationCompaction.__dataclass_params__.frozen
    assert CompactionItem.__dataclass_params__.frozen


def test_group19_no_promoted_boolean() -> None:
    item = CompactionItem(item_id="x", content="y", source_message_ids=(1,))
    assert not hasattr(item, "promoted")
    assert "promoted" not in _module_source("friday.compaction.models")


def test_group19_no_cross_database_transaction_claimed() -> None:
    source = _module_source("friday.compaction.promoter")
    # The promoter never opens its own database connection and never calls a
    # transaction spanning both databases.
    assert "sqlite3.connect" not in source
    assert "transaction(" not in source
    # ADR-025 documents the no-cross-DB-transaction guarantee.
    with open(
        Path(__file__).parent.parent.parent / "docs" / "ADR-025.md", encoding="utf-8"
    ) as fh:
        adr_text = fh.read()
    assert "cross-database" in adr_text.lower() or "cross-DB" in adr_text.lower()
    assert "exactly-once" in adr_text.lower()
