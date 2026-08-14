"""Tests for SQLiteMemoryStore implementation."""

from __future__ import annotations

import sqlite3
import tempfile
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from friday.memory.exceptions import (
    MemoryAlreadyExistsError,
    MemoryCorruptError,
    MemoryNotFoundError,
    MemoryStorageError,
)
from friday.memory.models import (
    Memory,
    MemoryConfidence,
    MemoryProvenance,
    MemoryScope,
    MemoryStatus,
    MemoryType,
)
from friday.memory.sqlite_memory_store import SQLiteMemoryStore


class TestSQLiteMemoryStore:
    """Test suite for SQLiteMemoryStore."""

    @pytest.fixture
    def temp_db_path(self) -> Path:
        """Create a temporary database path for testing."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            return Path(f.name)

    @pytest.fixture
    def store(self, temp_db_path: Path) -> Generator[SQLiteMemoryStore, None, None]:
        """Create a store instance with temporary database."""
        store = SQLiteMemoryStore(temp_db_path)
        yield store
        store.close()
        temp_db_path.unlink(missing_ok=True)

    def _make_memory(self, **kwargs) -> Memory:
        """Helper to create a valid memory with defaults."""
        defaults = {
            "type": MemoryType.USER_FACT,
            "scope": MemoryScope.USER,
            "content": "Test memory",
        }
        defaults.update(kwargs)
        if defaults["scope"] is MemoryScope.PROJECT and "project_id" not in defaults:
            defaults["project_id"] = "test-project"
        return Memory(**defaults)

    def test_save_and_get(self, store: SQLiteMemoryStore) -> None:
        """Test saving and retrieving a memory."""
        memory = self._make_memory()
        saved = store.save(memory)

        assert saved.id == memory.id
        assert saved.content == memory.content

        retrieved = store.get(memory.id)
        assert retrieved is not None
        assert retrieved.id == memory.id
        assert retrieved.content == memory.content
        assert retrieved.type == memory.type
        assert retrieved.scope == memory.scope

    def test_get_nonexistent_returns_none(self, store: SQLiteMemoryStore) -> None:
        """Test that getting a non-existent memory returns None."""
        result = store.get("nonexistent-id")
        assert result is None

    def test_duplicate_id_raises(self, store: SQLiteMemoryStore) -> None:
        """Test that saving a memory with existing ID raises MemoryAlreadyExistsError."""
        memory = self._make_memory()
        store.save(memory)

        # Try to save another memory with the same ID
        duplicate = self._make_memory(id=memory.id, content="Different content")
        with pytest.raises(MemoryAlreadyExistsError):
            store.save(duplicate)

    def test_update_existing(self, store: SQLiteMemoryStore) -> None:
        """Test updating an existing memory."""
        memory = self._make_memory(content="Original")
        store.save(memory)

        # Update content
        updated = Memory(
            id=memory.id,
            type=memory.type,
            scope=memory.scope,
            content="Updated content",
            status=memory.status,
            confidence=memory.confidence,
            provenance=memory.provenance,
            created_at=memory.created_at,
            updated_at=datetime.now(UTC),
            valid_from=memory.valid_from,
            valid_until=memory.valid_until,
            supersedes=memory.supersedes,
            superseded_by=memory.superseded_by,
            project_id=memory.project_id,
        )
        saved = store.update(updated)

        assert saved.content == "Updated content"
        assert saved.updated_at is not None and memory.updated_at is not None
        assert saved.updated_at > memory.updated_at

        retrieved = store.get(memory.id)
        assert retrieved is not None
        assert retrieved.content == "Updated content"

    def test_update_nonexistent_raises(self, store: SQLiteMemoryStore) -> None:
        """Test that updating a non-existent memory raises MemoryNotFoundError."""
        memory = self._make_memory()
        with pytest.raises(MemoryNotFoundError):
            store.update(memory)

    def test_query_by_scope(self, store: SQLiteMemoryStore) -> None:
        """Test querying memories by scope."""
        user_mem = self._make_memory(type=MemoryType.USER_FACT, scope=MemoryScope.USER, content="User fact")
        project_mem = self._make_memory(
            type=MemoryType.PROJECT_FACT,
            scope=MemoryScope.PROJECT,
            content="Project fact",
            project_id="proj-1",
        )
        conv_mem = self._make_memory(
            type=MemoryType.CONVERSATION_SUMMARY,
            scope=MemoryScope.CONVERSATION,
            content="Conv summary",
        )
        store.save(user_mem)
        store.save(project_mem)
        store.save(conv_mem)

        user_results = store.query(scope=MemoryScope.USER)
        project_results = store.query(scope=MemoryScope.PROJECT)
        conv_results = store.query(scope=MemoryScope.CONVERSATION)

        assert len(user_results) == 1
        assert user_results[0].content == "User fact"
        assert len(project_results) == 1
        assert project_results[0].content == "Project fact"
        assert len(conv_results) == 1
        assert conv_results[0].content == "Conv summary"

    def test_query_by_type(self, store: SQLiteMemoryStore) -> None:
        """Test querying memories by type."""
        fact = self._make_memory(type=MemoryType.USER_FACT, content="User fact")
        decision = self._make_memory(
            type=MemoryType.PROJECT_DECISION,
            scope=MemoryScope.PROJECT,
            content="Project decision",
            project_id="proj-1",
        )
        store.save(fact)
        store.save(decision)

        fact_results = store.query(memory_type=MemoryType.USER_FACT)
        decision_results = store.query(memory_type=MemoryType.PROJECT_DECISION)

        assert len(fact_results) == 1
        assert fact_results[0].type == MemoryType.USER_FACT
        assert len(decision_results) == 1
        assert decision_results[0].type == MemoryType.PROJECT_DECISION

    def test_query_by_status(self, store: SQLiteMemoryStore) -> None:
        """Test querying memories by status."""
        active = self._make_memory(status=MemoryStatus.ACTIVE)
        superseded = self._make_memory(id="superseded-id", status=MemoryStatus.SUPERSEDED)
        invalidated = self._make_memory(id="invalidated-id", status=MemoryStatus.INVALIDATED)
        store.save(active)
        store.save(superseded)
        store.save(invalidated)

        active_results = store.query(status=MemoryStatus.ACTIVE)
        superseded_results = store.query(status=MemoryStatus.SUPERSEDED)
        invalidated_results = store.query(status=MemoryStatus.INVALIDATED)

        assert len(active_results) == 1
        assert active_results[0].status == MemoryStatus.ACTIVE
        assert len(superseded_results) == 1
        assert superseded_results[0].status == MemoryStatus.SUPERSEDED
        assert len(invalidated_results) == 1
        assert invalidated_results[0].status == MemoryStatus.INVALIDATED

    def test_query_by_project_id(self, store: SQLiteMemoryStore) -> None:
        """Test querying memories by project_id."""
        proj1_mem = self._make_memory(
            type=MemoryType.PROJECT_FACT,
            scope=MemoryScope.PROJECT,
            content="Project 1 fact",
            project_id="proj-1",
        )
        proj2_mem = self._make_memory(
            type=MemoryType.PROJECT_FACT,
            scope=MemoryScope.PROJECT,
            content="Project 2 fact",
            project_id="proj-2",
        )
        user_mem = self._make_memory(type=MemoryType.USER_FACT, scope=MemoryScope.USER, content="User fact")
        store.save(proj1_mem)
        store.save(proj2_mem)
        store.save(user_mem)

        proj1_results = store.query(project_id="proj-1")
        proj2_results = store.query(project_id="proj-2")

        assert len(proj1_results) == 1
        assert proj1_results[0].project_id == "proj-1"
        assert len(proj2_results) == 1
        assert proj2_results[0].project_id == "proj-2"

    def test_query_by_conversation_id(self, store: SQLiteMemoryStore) -> None:
        """Test querying memories by conversation_id via provenance."""
        mem1 = self._make_memory(
            content="From conv 1",
            provenance=MemoryProvenance(source_conversation_id="conv-1", source_message_ids=("msg-1",)),
        )
        store.save(mem1)

        mem2 = self._make_memory(
            id="mem-2",
            content="From conv 2",
            provenance=MemoryProvenance(source_conversation_id="conv-2", source_message_ids=("msg-2",)),
        )
        store.save(mem2)

        conv1_results = store.query(conversation_id="conv-1")
        conv2_results = store.query(conversation_id="conv-2")

        assert len(conv1_results) == 1
        assert conv1_results[0].content == "From conv 1"
        assert len(conv2_results) == 1
        assert conv2_results[0].content == "From conv 2"

    def test_query_temporal_valid_at(self, store: SQLiteMemoryStore) -> None:
        """Test querying memories valid at a specific time."""
        now = datetime.now(UTC)
        past = now - timedelta(days=10)
        future = now + timedelta(days=10)

        # Valid now
        valid_now = self._make_memory(
            content="Valid now",
            valid_from=past,
            valid_until=future,
        )
        # Expired
        expired = self._make_memory(
            id="expired-id",
            content="Expired",
            valid_from=past - timedelta(days=5),
            valid_until=past,
        )
        # Future
        future_mem = self._make_memory(
            id="future-id",
            content="Future",
            valid_from=future,
            valid_until=future + timedelta(days=5),
        )
        store.save(valid_now)
        store.save(expired)
        store.save(future_mem)

        results = store.query(valid_at=now)
        assert len(results) == 1
        assert results[0].content == "Valid now"

    def test_query_created_after_before(self, store: SQLiteMemoryStore) -> None:
        """Test querying memories by creation time range."""
        base = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)
        early = self._make_memory(id="early", content="Early", created_at=base)
        middle = self._make_memory(id="middle", content="Middle", created_at=base + timedelta(days=5))
        late = self._make_memory(id="late", content="Late", created_at=base + timedelta(days=10))
        store.save(early)
        store.save(middle)
        store.save(late)

        after_early = store.query(created_after=base + timedelta(days=1))
        before_late = store.query(created_before=base + timedelta(days=8))

        assert len(after_early) == 2
        assert all(m.id in ("middle", "late") for m in after_early)
        assert len(before_late) == 2
        assert all(m.id in ("early", "middle") for m in before_late)

    def test_query_limit_offset(self, store: SQLiteMemoryStore) -> None:
        """Test query limit and offset pagination."""
        for i in range(5):
            mem = self._make_memory(id=f"mem-{i}", content=f"Memory {i}")
            store.save(mem)

        page1 = store.query(limit=2, offset=0)
        page2 = store.query(limit=2, offset=2)
        page3 = store.query(limit=2, offset=4)

        assert len(page1) == 2
        assert len(page2) == 2
        assert len(page3) == 1
        assert page1[0].id == "mem-4"  # Ordered by created_at DESC
        assert page1[1].id == "mem-3"
        assert page2[0].id == "mem-2"
        assert page2[1].id == "mem-1"
        assert page3[0].id == "mem-0"

    def test_all_memory_types(self, store: SQLiteMemoryStore) -> None:
        """Test saving and retrieving all memory types."""
        types_and_scopes = [
            (MemoryType.USER_FACT, MemoryScope.USER, None),
            (MemoryType.PROJECT_FACT, MemoryScope.PROJECT, "proj-1"),
            (MemoryType.PROJECT_CONSTRAINT, MemoryScope.PROJECT, "proj-1"),
            (MemoryType.PROJECT_DECISION, MemoryScope.PROJECT, "proj-1"),
            (MemoryType.CONVERSATION_SUMMARY, MemoryScope.CONVERSATION, None),
        ]

        for mem_type, scope, proj_id in types_and_scopes:
            mem = self._make_memory(type=mem_type, scope=scope, content=f"Content for {mem_type.value}", project_id=proj_id)
            store.save(mem)

        for mem_type, scope, proj_id in types_and_scopes:
            results = store.query(memory_type=mem_type)
            assert len(results) == 1
            assert results[0].type == mem_type

    def test_all_scopes(self, store: SQLiteMemoryStore) -> None:
        """Test all scopes are persisted correctly."""
        for scope in [MemoryScope.USER, MemoryScope.PROJECT, MemoryScope.CONVERSATION]:
            scope_type = {
                MemoryScope.USER: MemoryType.USER_FACT,
                MemoryScope.PROJECT: MemoryType.PROJECT_FACT,
                MemoryScope.CONVERSATION: MemoryType.CONVERSATION_SUMMARY,
            }[scope]
            kwargs = {"type": scope_type, "scope": scope, "content": f"Scope {scope.value}"}
            if scope == MemoryScope.PROJECT:
                kwargs["project_id"] = "proj-1"
            mem = self._make_memory(**kwargs)
            store.save(mem)

        for scope in [MemoryScope.USER, MemoryScope.PROJECT, MemoryScope.CONVERSATION]:
            results = store.query(scope=scope)
            assert len(results) >= 1

    def test_all_statuses(self, store: SQLiteMemoryStore) -> None:
        """Test all statuses are persisted correctly."""
        for status in [MemoryStatus.ACTIVE, MemoryStatus.SUPERSEDED, MemoryStatus.INVALIDATED]:
            mem = self._make_memory(id=f"mem-{status.value}", status=status, content=f"Status {status.value}")
            store.save(mem)

        for status in [MemoryStatus.ACTIVE, MemoryStatus.SUPERSEDED, MemoryStatus.INVALIDATED]:
            results = store.query(status=status)
            assert len(results) >= 1

    def test_all_confidence_levels(self, store: SQLiteMemoryStore) -> None:
        """Test all confidence levels are persisted correctly."""
        for confidence in [MemoryConfidence.EXPLICIT, MemoryConfidence.INFERRED, MemoryConfidence.TENTATIVE]:
            mem = self._make_memory(id=f"mem-{confidence.value}", confidence=confidence, content=f"Confidence {confidence.value}")
            store.save(mem)

        for confidence in [MemoryConfidence.EXPLICIT, MemoryConfidence.INFERRED, MemoryConfidence.TENTATIVE]:
            results = store.query()  # No filter, check all
            confidences = {m.confidence for m in results}
            assert confidence in confidences

    def test_provenance_round_trip(self, store: SQLiteMemoryStore) -> None:
        """Test provenance is saved and loaded correctly."""
        provenance = MemoryProvenance(source_conversation_id="conv-123", source_message_ids=("msg-1", "msg-2", "msg-3"))
        memory = self._make_memory(provenance=provenance)
        store.save(memory)

        retrieved = store.get(memory.id)
        assert retrieved is not None
        assert retrieved.provenance.source_conversation_id == "conv-123"
        assert retrieved.provenance.source_message_ids == ("msg-1", "msg-2", "msg-3")

    def test_provenance_without_conversation(self, store: SQLiteMemoryStore) -> None:
        """Test memory without provenance."""
        memory = self._make_memory(provenance=MemoryProvenance())
        store.save(memory)

        retrieved = store.get(memory.id)
        assert retrieved is not None
        assert retrieved.provenance.source_conversation_id is None
        assert retrieved.provenance.source_message_ids == ()

    def test_timestamps_round_trip(self, store: SQLiteMemoryStore) -> None:
        """Test all timestamp fields round-trip correctly."""
        created = datetime(2026, 6, 15, 10, 30, tzinfo=UTC)
        updated = created + timedelta(hours=1)
        valid_from = created
        valid_until = created + timedelta(days=30)

        memory = self._make_memory(
            created_at=created,
            updated_at=updated,
            valid_from=valid_from,
            valid_until=valid_until,
        )
        store.save(memory)

        retrieved = store.get(memory.id)
        assert retrieved is not None
        assert retrieved.created_at == created
        assert retrieved.updated_at == updated
        assert retrieved.valid_from == valid_from
        assert retrieved.valid_until == valid_until

    def test_supersession_fields(self, store: SQLiteMemoryStore) -> None:
        """Test supersedes and superseded_by fields persist correctly."""
        old = self._make_memory(id="old-id", content="Old")
        store.save(old)

        new = self._make_memory(
            id="new-id",
            content="New",
            supersedes="old-id",
            superseded_by=None,
        )
        store.save(new)

        superseded_old = Memory(
            id="old-id",
            type=old.type,
            scope=old.scope,
            content=old.content,
            status=MemoryStatus.SUPERSEDED,
            confidence=old.confidence,
            provenance=old.provenance,
            created_at=old.created_at,
            updated_at=datetime.now(UTC),
            valid_from=old.valid_from,
            valid_until=old.valid_until,
            supersedes=old.supersedes,
            superseded_by="new-id",
            project_id=old.project_id,
        )
        store.update(superseded_old)

        retrieved_new = store.get("new-id")
        retrieved_old = store.get("old-id")

        assert retrieved_new is not None
        assert retrieved_new.supersedes == "old-id"
        assert retrieved_new.superseded_by is None

        assert retrieved_old is not None
        assert retrieved_old.supersedes is None
        assert retrieved_old.superseded_by == "new-id"
        assert retrieved_old.status == MemoryStatus.SUPERSEDED

    def test_project_id_persistence(self, store: SQLiteMemoryStore) -> None:
        """Test project_id is saved and loaded correctly."""
        memory = self._make_memory(
            type=MemoryType.PROJECT_FACT,
            scope=MemoryScope.PROJECT,
            content="Project memory",
            project_id="my-project-123",
        )
        store.save(memory)

        retrieved = store.get(memory.id)
        assert retrieved is not None
        assert retrieved.project_id == "my-project-123"

    def test_persistence_after_reopen(self, temp_db_path: Path) -> None:
        """Test data persists after closing and reopening the store."""
        store1 = SQLiteMemoryStore(temp_db_path)
        memory = self._make_memory(content="Persistent")
        store1.save(memory)
        store1.close()

        store2 = SQLiteMemoryStore(temp_db_path)
        retrieved = store2.get(memory.id)
        assert retrieved is not None
        assert retrieved.content == "Persistent"
        store2.close()

    def test_schema_initialization(self, temp_db_path: Path) -> None:
        """Test schema is initialized on first use."""
        store = SQLiteMemoryStore(temp_db_path)
        # If we get here without exception, schema was created
        assert store._conn.execute("PRAGMA user_version").fetchone()[0] == 1
        store.close()

    def test_schema_version(self, temp_db_path: Path) -> None:
        """Test schema version is tracked."""
        store = SQLiteMemoryStore(temp_db_path)
        version = store._conn.execute("PRAGMA user_version").fetchone()[0]
        assert version == 1
        store.close()

    def test_transaction_rollback(self, store: SQLiteMemoryStore) -> None:
        """Test transaction rolls back on exception."""
        memory1 = self._make_memory(id="mem-1", content="First")
        store.save(memory1)

        try:
            with store.transaction():
                memory2 = self._make_memory(id="mem-2", content="Second")
                store.save(memory2)
                # Force an error
                raise ValueError("Simulated error")
        except ValueError:
            pass

        # mem-2 should not exist
        assert store.get("mem-2") is None
        # mem-1 should still exist
        assert store.get("mem-1") is not None

    def test_transaction_commit(self, store: SQLiteMemoryStore) -> None:
        """Test transaction commits on success."""
        with store.transaction():
            memory1 = self._make_memory(id="mem-1", content="First")
            store.save(memory1)
            memory2 = self._make_memory(id="mem-2", content="Second")
            store.save(memory2)

        assert store.get("mem-1") is not None
        assert store.get("mem-2") is not None

    def test_foreign_key_cascade_delete_provenance(self, store: SQLiteMemoryStore) -> None:
        """Test that deleting a memory cascades to provenance."""
        memory = self._make_memory(provenance=MemoryProvenance(source_conversation_id="conv-1", source_message_ids=("msg-1",)))
        store.save(memory)

        # Verify provenance exists
        prov = store._conn.execute(
            "SELECT * FROM memory_provenance WHERE memory_id = ?", (memory.id,)
        ).fetchone()
        assert prov is not None

        msgs = store._conn.execute(
            "SELECT * FROM memory_source_messages WHERE memory_id = ?", (memory.id,)
        ).fetchall()
        assert len(msgs) == 1

        # Delete the memory directly via SQL to test cascade
        with store._conn:
            store._conn.execute("DELETE FROM memories WHERE id = ?", (memory.id,))

        prov = store._conn.execute(
            "SELECT * FROM memory_provenance WHERE memory_id = ?", (memory.id,)
        ).fetchone()
        assert prov is None

        msgs = store._conn.execute(
            "SELECT * FROM memory_source_messages WHERE memory_id = ?", (memory.id,)
        ).fetchall()
        assert len(msgs) == 0

    def test_foreign_key_cascade_delete_supersession(self, store: SQLiteMemoryStore) -> None:
        """Test that deleting a superseded memory sets FK to NULL."""
        old = self._make_memory(id="old-id", content="Old")
        store.save(old)

        new = self._make_memory(id="new-id", content="New", supersedes="old-id")
        store.save(new)

        # Verify FK exists
        row = store._conn.execute("SELECT supersedes FROM memories WHERE id = ?", ("new-id",)).fetchone()
        assert row["supersedes"] == "old-id"

        # Delete old memory
        with store._conn:
            store._conn.execute("DELETE FROM memories WHERE id = ?", ("old-id",))

        # FK should be NULL
        row = store._conn.execute("SELECT supersedes FROM memories WHERE id = ?", ("new-id",)).fetchone()
        assert row["supersedes"] is None

    def test_unknown_schema_version_fails(self, temp_db_path: Path) -> None:
        """Test that unknown schema version raises error."""
        # Create DB with version 999
        conn = sqlite3.connect(temp_db_path)
        conn.execute("PRAGMA user_version = 999")
        conn.close()

        with pytest.raises(MemoryStorageError, match="Unknown schema version"):
            SQLiteMemoryStore(temp_db_path)

    def test_corrupt_row_raises(self, store: SQLiteMemoryStore) -> None:
        """Test that an invalid stored row raises MemoryCorruptError on load."""
        memory = self._make_memory(content="Will be corrupted")
        store.save(memory)

        # Corrupt the type/scope pairing directly in the database.
        # Both values are valid enums (pass DB CHECK) but violate the
        # domain invariant that type implies scope.
        with store._conn:
            store._conn.execute(
                "UPDATE memories SET scope = 'project' WHERE id = ?", (memory.id,)
            )

        with pytest.raises(MemoryCorruptError, match="Invalid memory row"):
            store.get(memory.id)

    def test_corrupt_empty_content_raises(self, store: SQLiteMemoryStore) -> None:
        """Test that a row with empty content raises MemoryCorruptError on load."""
        memory = self._make_memory(content="Will be corrupted")
        store.save(memory)

        with store._conn:
            store._conn.execute(
                "UPDATE memories SET content = '' WHERE id = ?", (memory.id,)
            )

        with pytest.raises(MemoryCorruptError, match="Invalid memory row"):
            store.get(memory.id)

    def test_database_isolation(self, temp_db_path: Path) -> None:
        """Test multiple store instances on same DB see each other's writes."""
        store1 = SQLiteMemoryStore(temp_db_path)
        store2 = SQLiteMemoryStore(temp_db_path)

        mem = self._make_memory(content="From store1")
        store1.save(mem)

        retrieved = store2.get(mem.id)
        assert retrieved is not None
        assert retrieved.content == "From store1"

        store1.close()
        store2.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])