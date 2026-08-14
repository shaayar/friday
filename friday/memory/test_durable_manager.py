"""Tests for DurableMemoryManager implementation."""

from __future__ import annotations

import tempfile
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from friday.memory.durable_manager import DurableMemoryManager
from friday.memory.exceptions import MemoryAlreadyExistsError, MemoryNotFoundError
from friday.memory.models import (
    Memory,
    MemoryScope,
    MemoryStatus,
    MemoryType,
)
from friday.memory.sqlite_memory_store import SQLiteMemoryStore


class TestDurableMemoryManager:
    """Test suite for DurableMemoryManager with a real SQLite store."""

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

    @pytest.fixture
    def manager(self, store: SQLiteMemoryStore) -> DurableMemoryManager:
        """Create a DurableMemoryManager backed by the real store."""
        return DurableMemoryManager(store)

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

    def test_save_and_get(self, manager: DurableMemoryManager) -> None:
        """Test saving a memory through the manager and retrieving it."""
        memory = self._make_memory(content="Durable fact")
        manager.save(memory)

        retrieved = manager.get(memory.id)
        assert retrieved is not None
        assert retrieved.id == memory.id
        assert retrieved.content == "Durable fact"

    def test_get_missing_returns_none(self, manager: DurableMemoryManager) -> None:
        """Test that get on a missing memory returns None."""
        assert manager.get("missing-id") is None

    def test_query_filters(self, manager: DurableMemoryManager) -> None:
        """Test manager query with deterministic filters."""
        user_mem = self._make_memory(content="User fact")
        project_mem = self._make_memory(
            type=MemoryType.PROJECT_FACT,
            scope=MemoryScope.PROJECT,
            content="Project fact",
            project_id="proj-1",
        )
        manager.save(user_mem)
        manager.save(project_mem)

        user_results = manager.query(scope=MemoryScope.USER)
        project_results = manager.query(project_id="proj-1")
        active_results = manager.query(status=MemoryStatus.ACTIVE)

        assert len(user_results) == 1
        assert user_results[0].content == "User fact"
        assert len(project_results) == 1
        assert project_results[0].content == "Project fact"
        assert len(active_results) == 2

    def test_invalidate(self, manager: DurableMemoryManager) -> None:
        """Test invalidating a memory changes status and preserves content."""
        created_at = datetime.now(UTC) - timedelta(hours=1)
        memory = self._make_memory(content="Old belief", created_at=created_at)
        manager.save(memory)
        original_updated_at = memory.updated_at

        invalidated = manager.invalidate(memory.id)

        assert invalidated.status is MemoryStatus.INVALIDATED
        assert invalidated.content == "Old belief"
        assert invalidated.updated_at is not None
        assert invalidated.updated_at >= original_updated_at

        stored = manager.get(memory.id)
        assert stored is not None
        assert stored.status is MemoryStatus.INVALIDATED

    def test_invalidate_missing_raises(self, manager: DurableMemoryManager) -> None:
        """Test invalidating a missing memory raises MemoryNotFoundError."""
        with pytest.raises(MemoryNotFoundError, match="not found"):
            manager.invalidate("missing-id")

    def test_supersede(self, manager: DurableMemoryManager) -> None:
        """Test superseding links old and new memories bidirectionally."""
        old = self._make_memory(content="Old decision")
        manager.save(old)

        new = self._make_memory(content="New decision")
        saved_new, saved_old = manager.supersede(old.id, new)

        # New memory points back at the old one
        assert saved_new.supersedes == old.id
        assert saved_new.superseded_by is None
        assert saved_new.status is MemoryStatus.ACTIVE

        # Old memory is superseded and points forward
        assert saved_old.status is MemoryStatus.SUPERSEDED
        assert saved_old.superseded_by == new.id

        stored_new = manager.get(new.id)
        stored_old = manager.get(old.id)
        assert stored_new is not None and stored_new.supersedes == old.id
        assert stored_old is not None and stored_old.superseded_by == new.id
        assert stored_old.status is MemoryStatus.SUPERSEDED

    def test_supersede_missing_raises(self, manager: DurableMemoryManager) -> None:
        """Test superseding a missing old memory raises MemoryNotFoundError."""
        new = self._make_memory(content="New decision")
        with pytest.raises(MemoryNotFoundError, match="not found"):
            manager.supersede("missing-id", new)

    def test_supersede_atomic_on_failure(self, manager: DurableMemoryManager) -> None:
        """Test supersede is atomic: a failure leaves the old memory unchanged."""
        old = self._make_memory(content="Old decision")
        manager.save(old)

        # The replacement memory already exists -> save() must fail
        existing = self._make_memory(content="Existing memory")
        manager.save(existing)

        with pytest.raises(MemoryAlreadyExistsError):
            manager.supersede(old.id, existing)

        # The old memory must NOT have been marked superseded (rolled back)
        stored_old = manager.get(old.id)
        assert stored_old is not None
        assert stored_old.status is MemoryStatus.ACTIVE
        assert stored_old.superseded_by is None

    def test_get_active_helper(self, manager: DurableMemoryManager) -> None:
        """Test get_active convenience only returns ACTIVE memories."""
        active = self._make_memory(content="Active")
        inactive = self._make_memory(id="inactive-id", content="Inactive")
        manager.save(active)
        manager.save(inactive)
        manager.invalidate("inactive-id")

        results = manager.get_active()
        assert len(results) == 1
        assert results[0].id == active.id


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
