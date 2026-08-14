"""SQLite storage for durable memories."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager, nullcontext
from datetime import datetime
from pathlib import Path
from typing import Self

from friday.config import config
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


def _default_database_path() -> Path:
    return config.FRIDAY_HOME / "data" / "memory.db"


def _require_aware_timestamp(name: str, value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value


class SQLiteMemoryStore:
    """SQLite implementation of MemoryStorage protocol."""

    SCHEMA_VERSION = 1

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._db_path = Path(db_path) if db_path is not None else _default_database_path()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._transaction_depth = 0
        self._initialize_schema()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def _initialize_schema(self) -> None:
        current_version = self._conn.execute("PRAGMA user_version").fetchone()[0]
        if current_version == 0:
            self._create_schema_v1()
            self._conn.execute("PRAGMA user_version = 1")
        elif current_version == self.SCHEMA_VERSION:
            return
        else:
            raise MemoryStorageError(f"Unknown schema version: {current_version}")

    def _create_schema_v1(self) -> None:
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE memories (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    content TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    confidence TEXT NOT NULL DEFAULT 'explicit',
                    project_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    valid_from TEXT NOT NULL,
                    valid_until TEXT,
                    supersedes TEXT,
                    superseded_by TEXT,
                    CHECK (scope IN ('user', 'project', 'conversation')),
                    CHECK (type IN ('user_fact', 'project_fact', 'project_constraint', 'project_decision', 'conversation_summary')),
                    CHECK (status IN ('active', 'superseded', 'invalidated')),
                    CHECK (confidence IN ('explicit', 'inferred', 'tentative')),
                    CHECK (valid_until IS NULL OR valid_until >= valid_from),
                    CHECK (updated_at >= created_at),
                    CHECK (supersedes != id),
                    CHECK (superseded_by != id),
                    FOREIGN KEY (supersedes) REFERENCES memories(id) ON DELETE SET NULL,
                    FOREIGN KEY (superseded_by) REFERENCES memories(id) ON DELETE SET NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE INDEX idx_memories_scope ON memories(scope)
                """
            )
            self._conn.execute(
                """
                CREATE INDEX idx_memories_type ON memories(type)
                """
            )
            self._conn.execute(
                """
                CREATE INDEX idx_memories_status ON memories(status)
                """
            )
            self._conn.execute(
                """
                CREATE INDEX idx_memories_project_id ON memories(project_id)
                """
            )
            self._conn.execute(
                """
                CREATE INDEX idx_memories_valid_from ON memories(valid_from)
                """
            )
            self._conn.execute(
                """
                CREATE INDEX idx_memories_supersedes ON memories(supersedes)
                """
            )
            self._conn.execute(
                """
                CREATE INDEX idx_memories_superseded_by ON memories(superseded_by)
                """
            )

            self._conn.execute(
                """
                CREATE TABLE memory_provenance (
                    memory_id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE CASCADE
                )
                """
            )
            self._conn.execute(
                """
                CREATE INDEX idx_memory_provenance_conversation ON memory_provenance(conversation_id)
                """
            )

            self._conn.execute(
                """
                CREATE TABLE memory_source_messages (
                    memory_id TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL,
                    PRIMARY KEY (memory_id, message_id),
                    FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE CASCADE
                )
                """
            )
            self._conn.execute(
                """
                CREATE INDEX idx_memory_source_messages_message ON memory_source_messages(message_id)
                """
            )

    @contextmanager
    def transaction(self):
        """Context manager for atomic multi-operation batches.

        Commits on clean exit, rolls back on exception. Nested operations
        must not commit individually (see _tx).
        """
        self._transaction_depth += 1
        try:
            with self._conn:
                yield self._conn
        finally:
            self._transaction_depth -= 1

    def _tx(self):
        """Return a connection context manager scoped to the current operation.

        When inside an explicit transaction() batch, return a no-op context so
        individual operations do not commit prematurely. Otherwise return the
        connection itself, which begins/commits a transaction for this single
        operation.
        """
        if self._transaction_depth > 0:
            return nullcontext()
        return self._conn

    def save(self, memory: Memory) -> Memory:
        """Persist a new memory. Fails if ID already exists."""
        self._validate_memory(memory)
        params = self._memory_to_params(memory)

        try:
            with self._tx():
                self._conn.execute(
                    """
                    INSERT INTO memories (
                        id, type, scope, content, status, confidence, project_id,
                        created_at, updated_at, valid_from, valid_until, supersedes, superseded_by
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    params,
                )
                self._save_provenance(memory)
        except sqlite3.IntegrityError as e:
            if "PRIMARY KEY" in str(e) or "UNIQUE" in str(e):
                raise MemoryAlreadyExistsError(f"Memory with ID {memory.id} already exists") from e
            raise MemoryStorageError(f"Failed to save memory: {e}") from e

        return memory

    def get(self, memory_id: str) -> Memory | None:
        """Retrieve a memory by ID."""
        row = self._conn.execute(
            "SELECT * FROM memories WHERE id = ?", (memory_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_memory(row)

    def update(self, memory: Memory) -> Memory:
        """Update an existing memory. Fails if ID does not exist."""
        self._validate_memory(memory)

        # Check existence first
        existing = self._conn.execute(
            "SELECT id FROM memories WHERE id = ?", (memory.id,)
        ).fetchone()
        if existing is None:
            raise MemoryNotFoundError(f"Memory with ID {memory.id} not found")

        params = self._memory_to_params(memory)

        try:
            with self._tx():
                self._conn.execute(
                    """
                    UPDATE memories SET
                        type = ?, scope = ?, content = ?, status = ?, confidence = ?,
                        project_id = ?, updated_at = ?, valid_from = ?, valid_until = ?,
                        supersedes = ?, superseded_by = ?
                    WHERE id = ?
                    """,
                    (*params[1:7], *params[8:], params[0]),
                )
                self._save_provenance(memory)
        except sqlite3.IntegrityError as e:
            raise MemoryStorageError(f"Failed to update memory: {e}") from e

        return memory

    def query(
        self,
        *,
        scope: MemoryScope | None = None,
        memory_type: MemoryType | None = None,
        status: MemoryStatus | None = None,
        project_id: str | None = None,
        conversation_id: str | int | None = None,
        valid_at: datetime | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Memory]:
        """Query memories with deterministic filters."""
        where_clauses = []
        params = []

        if scope is not None:
            where_clauses.append("scope = ?")
            params.append(scope.value)

        if memory_type is not None:
            where_clauses.append("type = ?")
            params.append(memory_type.value)

        if status is not None:
            where_clauses.append("status = ?")
            params.append(status.value)

        if project_id is not None:
            where_clauses.append("project_id = ?")
            params.append(project_id)

        if conversation_id is not None:
            where_clauses.append(
                "id IN (SELECT memory_id FROM memory_provenance WHERE conversation_id = ?)"
            )
            params.append(str(conversation_id))

        if valid_at is not None:
            _require_aware_timestamp("valid_at", valid_at)
            valid_at_iso = valid_at.isoformat(timespec="microseconds")
            where_clauses.append(
                "valid_from <= ? AND (valid_until IS NULL OR ? < valid_until)"
            )
            params.extend([valid_at_iso, valid_at_iso])

        if created_after is not None:
            _require_aware_timestamp("created_after", created_after)
            where_clauses.append("created_at > ?")
            params.append(created_after.isoformat(timespec="microseconds"))

        if created_before is not None:
            _require_aware_timestamp("created_before", created_before)
            where_clauses.append("created_at < ?")
            params.append(created_before.isoformat(timespec="microseconds"))

        where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""
        params.extend([limit, offset])

        rows = self._conn.execute(
            f"SELECT * FROM memories {where_sql} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params,
        ).fetchall()

        return [self._row_to_memory(row) for row in rows]

    def _validate_memory(self, memory: Memory) -> None:
        """Validate memory before persistence."""
        # The Memory.__post_init__ already validates most things, but we double-check
        if not isinstance(memory.id, str) or not memory.id.strip():
            raise MemoryCorruptError("Memory ID cannot be empty")

    def _memory_to_params(self, memory: Memory) -> tuple:
        """Convert Memory to SQL parameters."""
        return (
            memory.id,
            memory.type.value,
            memory.scope.value,
            memory.content,
            memory.status.value,
            memory.confidence.value,
            memory.project_id,
            memory.created_at.isoformat(timespec="microseconds"),
            memory.updated_at.isoformat(timespec="microseconds"),
            memory.valid_from.isoformat(timespec="microseconds"),
            memory.valid_until.isoformat(timespec="microseconds") if memory.valid_until else None,
            memory.supersedes,
            memory.superseded_by,
        )

    def _save_provenance(self, memory: Memory) -> None:
        """Save provenance data for a memory.

        The caller (save/update) is responsible for the transaction context.
        """
        if memory.provenance.source_conversation_id is not None:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO memory_provenance (memory_id, conversation_id)
                VALUES (?, ?)
                """,
                (memory.id, str(memory.provenance.source_conversation_id)),
            )

            # Delete old message IDs
            self._conn.execute(
                "DELETE FROM memory_source_messages WHERE memory_id = ?", (memory.id,)
            )

            # Insert new message IDs with ordinals
            for i, msg_id in enumerate(memory.provenance.source_message_ids):
                self._conn.execute(
                    """
                    INSERT INTO memory_source_messages (memory_id, message_id, ordinal)
                    VALUES (?, ?, ?)
                    """,
                    (memory.id, str(msg_id), i),
                )
        else:
            # Remove provenance if none
            self._conn.execute(
                "DELETE FROM memory_provenance WHERE memory_id = ?", (memory.id,)
            )
            self._conn.execute(
                "DELETE FROM memory_source_messages WHERE memory_id = ?", (memory.id,)
            )

    def _load_provenance(self, memory_id: str) -> MemoryProvenance:
        """Load provenance data for a memory."""
        prov_row = self._conn.execute(
            "SELECT conversation_id FROM memory_provenance WHERE memory_id = ?", (memory_id,)
        ).fetchone()

        if prov_row is None:
            return MemoryProvenance()

        msg_rows = self._conn.execute(
            "SELECT message_id FROM memory_source_messages WHERE memory_id = ? ORDER BY ordinal",
            (memory_id,),
        ).fetchall()

        return MemoryProvenance(
            source_conversation_id=prov_row["conversation_id"],
            source_message_ids=tuple(row["message_id"] for row in msg_rows),
        )

    def _row_to_memory(self, row: sqlite3.Row) -> Memory:
        """Convert a database row to a Memory object."""
        try:
            return Memory(
                id=row["id"],
                type=MemoryType(row["type"]),
                scope=MemoryScope(row["scope"]),
                content=row["content"],
                status=MemoryStatus(row["status"]),
                confidence=MemoryConfidence(row["confidence"]),
                provenance=self._load_provenance(row["id"]),
                created_at=datetime.fromisoformat(row["created_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"]),
                valid_from=datetime.fromisoformat(row["valid_from"]),
                valid_until=datetime.fromisoformat(row["valid_until"]) if row["valid_until"] else None,
                supersedes=row["supersedes"],
                superseded_by=row["superseded_by"],
                project_id=row["project_id"],
            )
        except (ValueError, KeyError) as e:
            raise MemoryCorruptError(f"Invalid memory row {row['id']}: {e}") from e