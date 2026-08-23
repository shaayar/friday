"""Tests for Phase 4 M4 SQLite compaction storage (conversations.db)."""

from __future__ import annotations

import inspect
from datetime import UTC, datetime
from pathlib import Path

import pytest

from friday.compaction.exceptions import (
    CompactionAlreadyExistsError,
    CompactionCorruptError,
)
from friday.compaction.models import CompactionItem, ConversationCompaction
from friday.compaction.sqlite_store import SQLiteCompactionStore
from friday.memory.sqlite_store import SQLiteConversationStore

NOW = datetime(2026, 8, 15, 12, 0, 0, tzinfo=UTC)


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
    first_message_id: int,
    last_message_id: int,
    summary: str = "Summary.",
    compaction_version: int = 1,
    facts: tuple[CompactionItem, ...] = (),
    decisions: tuple[CompactionItem, ...] = (),
    changes: tuple[CompactionItem, ...] = (),
    open_questions: tuple[CompactionItem, ...] = (),
) -> ConversationCompaction:
    return ConversationCompaction(
        compaction_id=compaction_id,
        conversation_id=conversation_id,
        first_message_id=first_message_id,
        last_message_id=last_message_id,
        created_at=NOW,
        compaction_version=compaction_version,
        summary=summary,
        facts=facts,
        decisions=decisions,
        changes=changes,
        open_questions=open_questions,
    )


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "conversations.db"


@pytest.fixture
def conversation_id(db_path: Path) -> int:
    with SQLiteConversationStore(db_path) as store:
        conversation = store.create_conversation()
        for i in range(1, 5):
            store.save_message(conversation.id, "user", f"Message {i}")
        return conversation.id


@pytest.fixture
def store(db_path: Path):
    store = SQLiteCompactionStore(db_path)
    yield store
    store.close()


def all_categories_compaction(conversation_id: int) -> ConversationCompaction:
    return make_compaction(
        compaction_id="comp-1",
        conversation_id=conversation_id,
        first_message_id=1,
        last_message_id=4,
        summary="Covered storage design.",
        facts=(
            make_item("item-f1", "Storage uses conversations.db.", (1, 2)),
            make_item("item-f2", "Memory stays in memory.db.", (3,)),
        ),
        decisions=(make_item("item-d1", "Use SQLite for compaction.", (4,)),),
        changes=(make_item("item-c1", "Added compaction tables.", (2, 4)),),
        open_questions=(make_item("item-q1", "Async seam pending.", (4,)),),
    )


class TestSaveGet:
    def test_save_get_round_trip(
        self, store: SQLiteCompactionStore, conversation_id: int
    ) -> None:
        compaction = all_categories_compaction(conversation_id)
        store.save(compaction)
        retrieved = store.get(compaction.compaction_id)
        assert retrieved is not None
        assert retrieved == compaction

    def test_all_four_categories_round_trip(
        self, store: SQLiteCompactionStore, conversation_id: int
    ) -> None:
        compaction = all_categories_compaction(conversation_id)
        store.save(compaction)
        retrieved = store.get(compaction.compaction_id)
        assert retrieved is not None
        assert retrieved.summary == "Covered storage design."
        assert [i.content for i in retrieved.facts] == [
            "Storage uses conversations.db.",
            "Memory stays in memory.db.",
        ]
        assert [i.content for i in retrieved.decisions] == [
            "Use SQLite for compaction."
        ]
        assert [i.content for i in retrieved.changes] == ["Added compaction tables."]
        assert [i.content for i in retrieved.open_questions] == ["Async seam pending."]

    def test_multiple_items_per_category(
        self, store: SQLiteCompactionStore, conversation_id: int
    ) -> None:
        compaction = make_compaction(
            compaction_id="multi",
            conversation_id=conversation_id,
            first_message_id=1,
            last_message_id=4,
            facts=(
                make_item("f1", "Fact one.", (1,)),
                make_item("f2", "Fact two.", (2,)),
                make_item("f3", "Fact three.", (3,)),
            ),
        )
        store.save(compaction)
        retrieved = store.get("multi")
        assert retrieved is not None
        assert [i.item_id for i in retrieved.facts] == ["f1", "f2", "f3"]

    def test_multiple_provenance_ids(
        self, store: SQLiteCompactionStore, conversation_id: int
    ) -> None:
        compaction = make_compaction(
            compaction_id="prov",
            conversation_id=conversation_id,
            first_message_id=1,
            last_message_id=4,
            facts=(make_item("f1", "Fact.", (1, 2, 3, 4)),),
        )
        store.save(compaction)
        retrieved = store.get("prov")
        assert retrieved is not None
        assert retrieved.facts[0].source_message_ids == (1, 2, 3, 4)

    def test_empty_categories_round_trip(
        self, store: SQLiteCompactionStore, conversation_id: int
    ) -> None:
        compaction = make_compaction(
            compaction_id="empty",
            conversation_id=conversation_id,
            first_message_id=1,
            last_message_id=4,
            summary="No facts here.",
        )
        store.save(compaction)
        retrieved = store.get("empty")
        assert retrieved is not None
        assert retrieved.facts == ()
        assert retrieved.decisions == ()
        assert retrieved.changes == ()
        assert retrieved.open_questions == ()
        assert retrieved.summary == "No facts here."

    def test_get_missing_returns_none(self, store: SQLiteCompactionStore) -> None:
        assert store.get("does-not-exist") is None

    def test_storage_does_not_mutate_domain_object(
        self, store: SQLiteCompactionStore, conversation_id: int
    ) -> None:
        compaction = all_categories_compaction(conversation_id)
        returned = store.save(compaction)
        assert returned == compaction
        assert compaction.facts == all_categories_compaction(conversation_id).facts
        assert compaction.compaction_id == "comp-1"

    def test_no_update_semantics(self, store: SQLiteCompactionStore) -> None:
        assert not hasattr(store, "update")


class TestIdentityAndIdempotency:
    def test_duplicate_compaction_id_rejected(
        self, store: SQLiteCompactionStore, conversation_id: int
    ) -> None:
        compaction = all_categories_compaction(conversation_id)
        store.save(compaction)
        with pytest.raises(CompactionAlreadyExistsError):
            store.save(compaction)

    def test_different_ranges_distinct_records(
        self, store: SQLiteCompactionStore, conversation_id: int
    ) -> None:
        c1 = make_compaction(
            compaction_id="c1",
            conversation_id=conversation_id,
            first_message_id=1,
            last_message_id=2,
        )
        c2 = make_compaction(
            compaction_id="c2",
            conversation_id=conversation_id,
            first_message_id=3,
            last_message_id=4,
        )
        store.save(c1)
        store.save(c2)
        assert store.get("c1") is not None
        assert store.get("c2") is not None


class TestListing:
    def test_conversation_isolation(
        self, store: SQLiteCompactionStore, db_path: Path, conversation_id: int
    ) -> None:
        with SQLiteConversationStore(db_path) as conv_store:
            conv_b = conv_store.create_conversation()
            for i in range(1, 4):
                conv_store.save_message(conv_b.id, "user", f"Message {i}")

        store.save(
            make_compaction(
                compaction_id="a",
                conversation_id=1,
                first_message_id=1,
                last_message_id=4,
            )
        )
        store.save(
            make_compaction(
                compaction_id="b",
                conversation_id=conv_b.id,
                first_message_id=1,
                last_message_id=3,
            )
        )

        a_ids = [c.compaction_id for c in store.list_for_conversation(1)]
        b_ids = [c.compaction_id for c in store.list_for_conversation(conv_b.id)]
        assert a_ids == ["a"]
        assert b_ids == ["b"]

    def test_multiple_compactions_one_conversation(
        self, store: SQLiteCompactionStore, conversation_id: int
    ) -> None:
        store.save(
            make_compaction(
                compaction_id="c1",
                conversation_id=conversation_id,
                first_message_id=1,
                last_message_id=2,
            )
        )
        store.save(
            make_compaction(
                compaction_id="c2",
                conversation_id=conversation_id,
                first_message_id=3,
                last_message_id=4,
            )
        )
        ids = [c.compaction_id for c in store.list_for_conversation(conversation_id)]
        assert set(ids) == {"c1", "c2"}

    def test_list_for_conversation_ordering_deterministic(
        self, store: SQLiteCompactionStore, conversation_id: int
    ) -> None:
        store.save(
            make_compaction(
                compaction_id="c1",
                conversation_id=conversation_id,
                first_message_id=1,
                last_message_id=2,
            )
        )
        store.save(
            make_compaction(
                compaction_id="c2",
                conversation_id=conversation_id,
                first_message_id=3,
                last_message_id=4,
            )
        )
        ids = [c.compaction_id for c in store.list_for_conversation(conversation_id)]
        assert ids == ["c1", "c2"]

    def test_get_latest_by_last_message_id(
        self, store: SQLiteCompactionStore, conversation_id: int
    ) -> None:
        store.save(
            make_compaction(
                compaction_id="c1",
                conversation_id=conversation_id,
                first_message_id=1,
                last_message_id=2,
            )
        )
        store.save(
            make_compaction(
                compaction_id="c2",
                conversation_id=conversation_id,
                first_message_id=3,
                last_message_id=4,
            )
        )
        latest = store.get_latest_for_conversation(conversation_id)
        assert latest is not None
        assert latest.compaction_id == "c2"
        assert latest.last_message_id == 4

    def test_get_latest_none_when_no_compactions(
        self, store: SQLiteCompactionStore, conversation_id: int
    ) -> None:
        assert store.get_latest_for_conversation(conversation_id) is None


class TestDurability:
    def test_survives_close_reopen(self, db_path: Path, conversation_id: int) -> None:
        compaction = all_categories_compaction(conversation_id)
        with SQLiteCompactionStore(db_path) as store:
            store.save(compaction)
        with SQLiteCompactionStore(db_path) as reopened:
            retrieved = reopened.get("comp-1")
            assert retrieved is not None
            assert retrieved == compaction
            assert [
                c.compaction_id for c in reopened.list_for_conversation(conversation_id)
            ] == ["comp-1"]


class TestForeignKeys:
    def test_conversation_cascade_deletes_compactions(
        self, store: SQLiteCompactionStore, conversation_id: int
    ) -> None:
        store.save(
            make_compaction(
                compaction_id="c1",
                conversation_id=conversation_id,
                first_message_id=1,
                last_message_id=4,
            )
        )
        with store._conn:
            store._conn.execute(
                "DELETE FROM conversations WHERE id = ?", (conversation_id,)
            )
        assert store.get("c1") is None
        row = store._conn.execute(
            "SELECT COUNT(*) FROM compaction_items WHERE compaction_id = ?", ("c1",)
        ).fetchone()
        assert row[0] == 0

    def test_compaction_delete_cascades_to_items_and_provenance(
        self, store: SQLiteCompactionStore, conversation_id: int
    ) -> None:
        store.save(all_categories_compaction(conversation_id))
        with store._conn:
            store._conn.execute(
                "DELETE FROM conversation_compactions WHERE compaction_id = ?",
                ("comp-1",),
            )
        item_count = store._conn.execute(
            "SELECT COUNT(*) FROM compaction_items WHERE compaction_id = ?", ("comp-1",)
        ).fetchone()[0]
        assert item_count == 0
        prov_count = store._conn.execute(
            "SELECT COUNT(*) FROM compaction_provenance"
        ).fetchone()[0]
        assert prov_count == 0

    def test_save_for_missing_conversation_fails(
        self, store: SQLiteCompactionStore
    ) -> None:
        compaction = make_compaction(
            compaction_id="orphan",
            conversation_id=99999,
            first_message_id=1,
            last_message_id=4,
        )
        with pytest.raises(CompactionCorruptError):
            store.save(compaction)

    def test_missing_source_message_rejected(
        self, store: SQLiteCompactionStore, conversation_id: int
    ) -> None:
        compaction = make_compaction(
            compaction_id="bad-prov",
            conversation_id=conversation_id,
            first_message_id=1,
            last_message_id=6,
            facts=(make_item("f1", "Fact.", (1, 5)),),
        )
        with pytest.raises(CompactionCorruptError, match="source message"):
            store.save(compaction)

    def test_atomic_failure_no_partial_compaction(
        self, store: SQLiteCompactionStore, conversation_id: int
    ) -> None:
        bad = make_compaction(
            compaction_id="atomic-bad",
            conversation_id=conversation_id,
            first_message_id=1,
            last_message_id=6,
            facts=(
                make_item("f1", "Fact.", (1, 2)),
                make_item("f2", "Ghost fact.", (5,)),
            ),
        )
        with pytest.raises(CompactionCorruptError):
            store.save(bad)
        assert store.get("atomic-bad") is None
        row = store._conn.execute(
            "SELECT COUNT(*) FROM compaction_items WHERE compaction_id = ?",
            ("atomic-bad",),
        ).fetchone()
        assert row[0] == 0


class TestValidation:
    def test_invalid_category_rejected(
        self, store: SQLiteCompactionStore, conversation_id: int
    ) -> None:
        with pytest.raises(CompactionCorruptError, match="category"):
            store._validate_category("gossip")

    def test_unsupported_version_rejected_on_read(
        self, store: SQLiteCompactionStore, conversation_id: int
    ) -> None:
        compaction = make_compaction(
            compaction_id="v2",
            conversation_id=conversation_id,
            first_message_id=1,
            last_message_id=4,
            compaction_version=2,
        )
        store.save(compaction)
        with pytest.raises(CompactionCorruptError, match="version"):
            store.get("v2")


class TestIsolation:
    def test_no_raw_message_content_duplicated(
        self, store: SQLiteCompactionStore, conversation_id: int
    ) -> None:
        store.save(all_categories_compaction(conversation_id))
        content_rows = store._conn.execute(
            "SELECT content FROM compaction_items"
        ).fetchall()
        compaction_contents = {row[0] for row in content_rows}
        for i in range(1, 5):
            assert f"Message {i}" not in compaction_contents

    def test_no_memory_db_interaction(
        self, db_path: Path, tmp_path: Path, monkeypatch
    ) -> None:
        from friday import config

        monkeypatch.setattr(config.config, "FRIDAY_HOME", tmp_path)
        with SQLiteCompactionStore():
            pass
        assert (tmp_path / "data" / "conversations.db").exists()
        assert not (tmp_path / "data" / "memory.db").exists()

    def test_no_llm_interaction(self) -> None:
        import friday.compaction.sqlite_store as module

        source = inspect.getsource(module)
        assert "LLMBackend" not in source
        assert "friday.ai" not in source
        assert "complete(" not in source
