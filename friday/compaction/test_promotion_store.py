"""Tests for Phase 4 M6.2 SQLite promotion-ledger storage (ADR-025).

Uses temporary SQLite databases only; the user's real
``~/.friday/data/conversations.db`` is never touched.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from friday.compaction.exceptions import (
    PromotionAlreadyExistsError,
    PromotionCorruptError,
    PromotionNotFoundError,
)
from friday.compaction.models import CompactionItem, ConversationCompaction
from friday.compaction.promotion import (
    CompactionItemCategory,
    CompactionPromotion,
    PromotionResolutionKind,
    PromotionStatus,
)
from friday.compaction.promotion_store import SQLitePromotionStore
from friday.compaction.sqlite_store import SQLiteCompactionStore
from friday.memory.sqlite_store import SQLiteConversationStore

NOW = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)
LATER = datetime(2026, 1, 15, 12, 30, 0, tzinfo=UTC)

CATEGORY_ITEMS = {
    CompactionItemCategory.FACTS: ("item-f1",),
    CompactionItemCategory.DECISIONS: ("item-d1",),
    CompactionItemCategory.CHANGES: ("item-c1",),
    CompactionItemCategory.OPEN_QUESTIONS: ("item-q1",),
}


def make_item(
    item_id: str, content: str, source_message_ids: tuple[int, ...]
) -> CompactionItem:
    return CompactionItem(
        item_id=item_id, content=content, source_message_ids=source_message_ids
    )


def make_compaction(
    *,
    compaction_id: str,
    conversation_id: int,
    first_message_id: int = 1,
    last_message_id: int = 4,
    suffix: str = "",
) -> ConversationCompaction:
    return ConversationCompaction(
        compaction_id=compaction_id,
        conversation_id=conversation_id,
        first_message_id=first_message_id,
        last_message_id=last_message_id,
        created_at=NOW,
        summary="Covered promotion ledger design.",
        facts=(make_item(f"item-f1{suffix}", "Facts round-trip.", (1, 2)),),
        decisions=(make_item(f"item-d1{suffix}", "Decisions round-trip.", (3,)),),
        changes=(make_item(f"item-c1{suffix}", "Changes round-trip.", (2,)),),
        open_questions=(make_item(f"item-q1{suffix}", "Questions round-trip.", (4,)),),
    )


def make_pending(
    *,
    item_id: str = "item-f1",
    compaction_id: str = "comp-1",
    category: CompactionItemCategory = CompactionItemCategory.FACTS,
) -> CompactionPromotion:
    return CompactionPromotion.pending(
        item_id=item_id,
        compaction_id=compaction_id,
        category=category,
        created_at=NOW,
    )


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "conversations.db"


@pytest.fixture
def seeded(db_path: Path):
    """Create a conversation, messages, and a compaction with one item per category."""
    with SQLiteConversationStore(db_path) as conv_store:
        conversation = conv_store.create_conversation()
        for i in range(1, 5):
            conv_store.save_message(conversation.id, "user", f"Message {i}")
    compaction = make_compaction(
        compaction_id="comp-1",
        conversation_id=conversation.id,
    )
    with SQLiteCompactionStore(db_path) as comp_store:
        comp_store.save(compaction)
    return {
        "conversation_id": conversation.id,
        "compaction_id": compaction.compaction_id,
    }


@pytest.fixture
def store(db_path: Path):
    store = SQLitePromotionStore(db_path)
    yield store
    store.close()


class TestSaveGet:
    def test_save_pending_promotion(
        self, store: SQLitePromotionStore, seeded: dict
    ) -> None:
        promotion = make_pending(compaction_id=seeded["compaction_id"])
        returned = store.save(promotion)
        assert returned == promotion
        assert returned.status is PromotionStatus.PENDING

    def test_get_round_trip(self, store: SQLitePromotionStore, seeded: dict) -> None:
        promotion = make_pending(compaction_id=seeded["compaction_id"])
        store.save(promotion)
        retrieved = store.get("item-f1")
        assert retrieved is not None
        assert retrieved == promotion
        assert retrieved.item_id == "item-f1"
        assert retrieved.compaction_id == seeded["compaction_id"]
        assert retrieved.category is CompactionItemCategory.FACTS
        assert retrieved.created_at == NOW
        assert retrieved.updated_at == NOW

    def test_get_missing_returns_none(self, store: SQLitePromotionStore) -> None:
        assert store.get("no-such-item") is None

    def test_save_does_not_mutate_domain_object(
        self, store: SQLitePromotionStore, seeded: dict
    ) -> None:
        promotion = make_pending(compaction_id=seeded["compaction_id"])
        returned = store.save(promotion)
        assert returned == promotion
        assert promotion.status is PromotionStatus.PENDING


class TestStatusRoundTrips:
    @pytest.mark.parametrize(
        "category, item_id",
        [(c, ids[0]) for c, ids in CATEGORY_ITEMS.items()],
    )
    def test_all_categories_round_trip(
        self,
        store: SQLitePromotionStore,
        seeded: dict,
        category: CompactionItemCategory,
        item_id: str,
    ) -> None:
        promotion = make_pending(
            item_id=item_id, category=category, compaction_id=seeded["compaction_id"]
        )
        store.save(promotion)
        retrieved = store.get(item_id)
        assert retrieved is not None
        assert retrieved.category is category

    def test_pending_round_trip(
        self, store: SQLitePromotionStore, seeded: dict
    ) -> None:
        promotion = make_pending(compaction_id=seeded["compaction_id"])
        store.save(promotion)
        assert store.get("item-f1").status is PromotionStatus.PENDING
        assert store.get("item-f1").resolved_memory_ids == ()

    def test_promoted_round_trip(
        self, store: SQLitePromotionStore, seeded: dict
    ) -> None:
        promotion = make_pending(compaction_id=seeded["compaction_id"]).mark_promoted(
            ("mem-2", "mem-1"),
            resolution_kind=PromotionResolutionKind.CREATE,
            updated_at=LATER,
        )
        store.save(promotion)
        retrieved = store.get("item-f1")
        assert retrieved is not None
        assert retrieved.status is PromotionStatus.PROMOTED
        assert retrieved.resolved_memory_ids == ("mem-1", "mem-2")
        assert retrieved.resolution_kind is PromotionResolutionKind.CREATE
        assert retrieved.updated_at == LATER

    def test_rejected_round_trip(
        self, store: SQLitePromotionStore, seeded: dict
    ) -> None:
        promotion = make_pending(compaction_id=seeded["compaction_id"]).mark_rejected(
            "duplicate", updated_at=LATER
        )
        store.save(promotion)
        retrieved = store.get("item-f1")
        assert retrieved is not None
        assert retrieved.status is PromotionStatus.REJECTED
        assert retrieved.resolution_reason == "duplicate"

    def test_resolution_kind_round_trip(
        self, store: SQLitePromotionStore, seeded: dict
    ) -> None:
        promotion = make_pending(compaction_id=seeded["compaction_id"]).mark_promoted(
            ("mem-1",),
            resolution_kind=PromotionResolutionKind.SUPERSEDE,
            updated_at=LATER,
        )
        store.save(promotion)
        assert store.get("item-f1").resolution_kind is PromotionResolutionKind.SUPERSEDE

    def test_retry_count_round_trip(
        self, store: SQLitePromotionStore, seeded: dict
    ) -> None:
        promotion = make_pending(
            compaction_id=seeded["compaction_id"]
        ).record_transient_failure("timeout", updated_at=LATER)
        store.save(promotion)
        retrieved = store.get("item-f1")
        assert retrieved is not None
        assert retrieved.retry_count == 1
        assert retrieved.last_error == "timeout"

    def test_last_error_round_trip(
        self, store: SQLitePromotionStore, seeded: dict
    ) -> None:
        promotion = make_pending(
            compaction_id=seeded["compaction_id"]
        ).record_transient_failure("memory.db unavailable", updated_at=LATER)
        store.save(promotion)
        assert store.get("item-f1").last_error == "memory.db unavailable"

    def test_timestamps_round_trip(
        self, store: SQLitePromotionStore, seeded: dict
    ) -> None:
        promotion = make_pending(compaction_id=seeded["compaction_id"]).mark_rejected(
            "nope", updated_at=LATER
        )
        store.save(promotion)
        retrieved = store.get("item-f1")
        assert retrieved.created_at == NOW
        assert retrieved.updated_at == LATER

    def test_timezone_preserved(
        self, store: SQLitePromotionStore, seeded: dict
    ) -> None:
        promotion = make_pending(compaction_id=seeded["compaction_id"])
        store.save(promotion)
        retrieved = store.get("item-f1")
        assert retrieved.created_at.tzinfo is not None
        assert retrieved.created_at.utcoffset() == timedelta(0)


class TestListing:
    def test_list_for_compaction(
        self, store: SQLitePromotionStore, seeded: dict
    ) -> None:
        for item_id, category in (
            ("item-f1", CompactionItemCategory.FACTS),
            ("item-d1", CompactionItemCategory.DECISIONS),
        ):
            store.save(
                make_pending(
                    item_id=item_id,
                    category=category,
                    compaction_id=seeded["compaction_id"],
                )
            )
        entries = store.list_for_compaction(seeded["compaction_id"])
        assert {e.item_id for e in entries} == {"item-f1", "item-d1"}

    def test_multiple_compactions_isolated(
        self, store: SQLitePromotionStore, db_path: Path, seeded: dict
    ) -> None:
        with SQLiteCompactionStore(db_path) as comp_store:
            compaction_b = make_compaction(
                compaction_id="comp-2",
                conversation_id=seeded["conversation_id"],
                suffix="b",
            )
            comp_store.save(compaction_b)
        store.save(
            make_pending(item_id="item-f1", compaction_id=seeded["compaction_id"])
        )
        store.save(make_pending(item_id="item-f1b", compaction_id="comp-2"))
        assert [
            e.item_id for e in store.list_for_compaction(seeded["compaction_id"])
        ] == ["item-f1"]
        assert [e.item_id for e in store.list_for_compaction("comp-2")] == ["item-f1b"]

    def test_deterministic_ordering(
        self, store: SQLitePromotionStore, seeded: dict
    ) -> None:
        for i, (item_id, category) in enumerate(
            (
                ("item-c1", CompactionItemCategory.CHANGES),
                ("item-d1", CompactionItemCategory.DECISIONS),
                ("item-q1", CompactionItemCategory.OPEN_QUESTIONS),
            )
        ):
            created = NOW.replace(microsecond=i + 1)
            store.save(
                CompactionPromotion.pending(
                    item_id=item_id,
                    compaction_id=seeded["compaction_id"],
                    category=category,
                    created_at=created,
                )
            )
        entries = store.list_for_compaction(seeded["compaction_id"])
        assert [e.item_id for e in entries] == ["item-c1", "item-d1", "item-q1"]


class TestTransitionsPersisted:
    def test_state_transition_persisted_via_replace(
        self, store: SQLitePromotionStore, seeded: dict
    ) -> None:
        pending = make_pending(compaction_id=seeded["compaction_id"])
        store.save(pending)
        rejected = pending.mark_rejected("duplicate", updated_at=LATER)
        store.replace(rejected)
        retrieved = store.get("item-f1")
        assert retrieved is not None
        assert retrieved.status is PromotionStatus.REJECTED
        assert retrieved.resolution_reason == "duplicate"

    def test_reconsideration_persisted(
        self, store: SQLitePromotionStore, seeded: dict
    ) -> None:
        promotion = make_pending(compaction_id=seeded["compaction_id"])
        store.save(promotion)
        rejected = promotion.mark_rejected("duplicate", updated_at=LATER)
        store.replace(rejected)
        reconsidered = rejected.request_reconsideration(updated_at=LATER)
        store.replace(reconsidered)
        retrieved = store.get("item-f1")
        assert retrieved is not None
        assert retrieved.status is PromotionStatus.PENDING
        assert retrieved.resolution_reason == "duplicate"

    def test_transient_failure_remains_pending(
        self, store: SQLitePromotionStore, seeded: dict
    ) -> None:
        promotion = make_pending(compaction_id=seeded["compaction_id"])
        store.save(promotion)
        failed = promotion.record_transient_failure("boom", updated_at=LATER)
        store.replace(failed)
        retrieved = store.get("item-f1")
        assert retrieved is not None
        assert retrieved.status is PromotionStatus.PENDING
        assert retrieved.retry_count == 1
        assert retrieved.last_error == "boom"

    def test_replace_missing_raises_not_found(
        self, store: SQLitePromotionStore, seeded: dict
    ) -> None:
        with pytest.raises(PromotionNotFoundError):
            store.replace(make_pending(compaction_id=seeded["compaction_id"]))


class TestDuplicates:
    def test_duplicate_item_id_rejected(
        self, store: SQLitePromotionStore, seeded: dict
    ) -> None:
        store.save(make_pending(compaction_id=seeded["compaction_id"]))
        with pytest.raises(PromotionAlreadyExistsError):
            store.save(make_pending(compaction_id=seeded["compaction_id"]))

    def test_raw_sql_duplicate_rejected_by_unique_constraint(
        self, store: SQLitePromotionStore, seeded: dict
    ) -> None:
        store.save(make_pending(compaction_id=seeded["compaction_id"]))
        with pytest.raises(PromotionAlreadyExistsError):
            store.save(
                make_pending(compaction_id=seeded["compaction_id"]).mark_rejected(
                    "dup", updated_at=LATER
                )
            )

    def test_save_for_unknown_item_fails(self, store: SQLitePromotionStore) -> None:
        with pytest.raises(PromotionCorruptError):
            store.save(make_pending(item_id="ghost", compaction_id="comp-1"))


class TestCorruption:
    def test_corrupt_status_rejected(
        self, store: SQLitePromotionStore, seeded: dict
    ) -> None:
        store.save(make_pending(compaction_id=seeded["compaction_id"]))
        self._bypass_check_update(store, "status = 'archived'", "item-f1")
        with pytest.raises(PromotionCorruptError, match="Invalid promotion row"):
            store.get("item-f1")

    def test_corrupt_category_rejected(
        self, store: SQLitePromotionStore, seeded: dict
    ) -> None:
        store.save(make_pending(compaction_id=seeded["compaction_id"]))
        self._bypass_check_update(store, "category = 'gossip'", "item-f1")
        with pytest.raises(PromotionCorruptError, match="Invalid promotion row"):
            store.get("item-f1")

    def test_corrupt_resolution_kind_rejected(
        self, store: SQLitePromotionStore, seeded: dict
    ) -> None:
        promotion = make_pending(compaction_id=seeded["compaction_id"]).mark_promoted(
            ("mem-1",), resolution_kind=PromotionResolutionKind.CREATE, updated_at=LATER
        )
        store.save(promotion)
        self._bypass_check_update(store, "resolution_kind = 'demote'", "item-f1")
        with pytest.raises(PromotionCorruptError, match="Invalid promotion row"):
            store.get("item-f1")

    def test_malformed_memory_id_rejected(
        self, store: SQLitePromotionStore, seeded: dict
    ) -> None:
        promotion = make_pending(compaction_id=seeded["compaction_id"]).mark_promoted(
            ("mem-1",), updated_at=LATER
        )
        store.save(promotion)
        with store._conn:
            store._conn.execute(
                "INSERT INTO promotion_resolved_memory_ids (item_id, memory_id, ordinal) VALUES (?, ?, ?)",
                ("item-f1", "   ", 1),
            )
        with pytest.raises(PromotionCorruptError, match="resolved memory ID"):
            store.get("item-f1")

    def test_invalid_persisted_domain_state_rejected(
        self, store: SQLitePromotionStore, seeded: dict
    ) -> None:
        promotion = make_pending(compaction_id=seeded["compaction_id"]).mark_promoted(
            ("mem-1",), updated_at=LATER
        )
        store.save(promotion)
        with store._conn:
            store._conn.execute(
                "DELETE FROM promotion_resolved_memory_ids WHERE item_id = ?",
                ("item-f1",),
            )
        with pytest.raises(PromotionCorruptError, match="Invalid promotion row"):
            store.get("item-f1")

    @staticmethod
    def _bypass_check_update(
        store: SQLitePromotionStore, assignment: str, item_id: str
    ) -> None:
        store._conn.execute("PRAGMA ignore_check_constraints = ON")
        store._conn.execute(
            f"UPDATE compaction_promotions SET {assignment} WHERE item_id = ?",
            (item_id,),
        )
        store._conn.execute("PRAGMA ignore_check_constraints = OFF")


class TestDurability:
    def test_survives_close_reopen(self, db_path: Path, seeded: dict) -> None:
        with SQLitePromotionStore(db_path) as store:
            store.save(make_pending(compaction_id=seeded["compaction_id"]))
        with SQLitePromotionStore(db_path) as reopened:
            retrieved = reopened.get("item-f1")
            assert retrieved is not None
            assert retrieved.status is PromotionStatus.PENDING
            assert [
                e.item_id for e in reopened.list_for_compaction(seeded["compaction_id"])
            ] == ["item-f1"]


class TestCascade:
    def test_compaction_delete_cascades_to_promotions(
        self, store: SQLitePromotionStore, seeded: dict
    ) -> None:
        store.save(make_pending(compaction_id=seeded["compaction_id"]))
        with store._conn:
            store._conn.execute(
                "DELETE FROM conversation_compactions WHERE compaction_id = ?",
                (seeded["compaction_id"],),
            )
        assert store.get("item-f1") is None
        child_count = store._conn.execute(
            "SELECT COUNT(*) FROM promotion_resolved_memory_ids WHERE item_id = ?",
            ("item-f1",),
        ).fetchone()[0]
        assert child_count == 0

    def test_item_delete_cascades_to_promotion(
        self, store: SQLitePromotionStore, seeded: dict
    ) -> None:
        store.save(make_pending(compaction_id=seeded["compaction_id"]))
        with store._conn:
            store._conn.execute(
                "DELETE FROM compaction_items WHERE item_id = ?", ("item-f1",)
            )
        assert store.get("item-f1") is None


class TestIsolation:
    def test_no_memory_db_interaction(self, tmp_path: Path, monkeypatch) -> None:
        from friday import config

        monkeypatch.setattr(config.config, "FRIDAY_HOME", tmp_path)
        with SQLitePromotionStore():
            pass
        assert (tmp_path / "data" / "conversations.db").exists()
        assert not (tmp_path / "data" / "memory.db").exists()

    def test_no_llm_or_memory_pipeline_imports(self) -> None:
        import friday.compaction.promotion_store as module

        source = inspect.getsource(module)
        for forbidden in (
            "LLMBackend",
            "friday.ai",
            "MemoryResolver",
            "MemoryCandidate",
            "DurableMemoryManager",
            "ProjectService",
            "LiveKit",
            "ContextManager",
            "agent_friday",
        ):
            assert forbidden not in source


class TestApiShape:
    def test_no_public_delete_api(self, store: SQLitePromotionStore) -> None:
        assert not hasattr(store, "delete")

    def test_no_generic_update_api(self, store: SQLitePromotionStore) -> None:
        assert not hasattr(store, "update")

    def test_get_is_item_id_keyed(
        self, store: SQLitePromotionStore, seeded: dict
    ) -> None:
        store.save(make_pending(compaction_id=seeded["compaction_id"]))
        assert store.get("item-f1") is not None
