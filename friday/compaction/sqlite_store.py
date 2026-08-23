"""SQLite storage for persistent conversation compactions.

Compaction records live in the EXISTING conversation database
(``~/.friday/data/conversations.db``) alongside raw conversation history.
Durable cross-conversation memory stays in ``memory.db``; this module never
touches it.

The store is deliberately dumb: it persists validated
``ConversationCompaction`` domain objects and never calls the LLM, computes
boundaries, selects windows, resolves memories, or decides whether a
compaction should happen.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Self

from friday.compaction.exceptions import (
    CompactionAlreadyExistsError,
    CompactionCorruptError,
)
from friday.compaction.models import CompactionItem, ConversationCompaction
from friday.config import config

# The compaction domain version this store understands. Compactions with a
# different version are persisted (storage is version-agnostic) but fail
# explicitly on read, following the repository's "unknown schema/domain
# version" convention.
SUPPORTED_COMPACTION_VERSION = 1

_CATEGORIES = ("facts", "decisions", "changes", "open_questions")


def _default_database_path() -> Path:
    return config.FRIDAY_HOME / "data" / "conversations.db"


class SQLiteCompactionStore:
    """SQLite persistence for compaction records in conversations.db."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._db_path = Path(db_path) if db_path is not None else _default_database_path()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._initialize_schema()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object | None,
    ) -> None:
        self.close()

    def _initialize_schema(self) -> None:
        """Create the compaction tables if they do not exist.

        Additive and idempotent, matching the conversation store's
        ``CREATE TABLE IF NOT EXISTS`` pattern. The base conversations/messages
        tables are (re)declared identically so a fresh database — or a
        database opened through this store alone — is self-contained. Does not
        alter or version the raw conversation/message schema.
        """
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (conversation_id)
                        REFERENCES conversations (id)
                        ON DELETE CASCADE
                )
                """
            )
            self._conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_messages_conversation_id_id
                ON messages (conversation_id, id)
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS conversation_compactions (
                    compaction_id        TEXT PRIMARY KEY,
                    conversation_id      INTEGER NOT NULL,
                    first_message_id     INTEGER NOT NULL,
                    last_message_id      INTEGER NOT NULL,
                    created_at           TEXT NOT NULL,
                    compaction_version   INTEGER NOT NULL,
                    summary              TEXT NOT NULL DEFAULT '',
                    CHECK (first_message_id <= last_message_id),
                    CHECK (compaction_version >= 1),
                    FOREIGN KEY (conversation_id)
                        REFERENCES conversations(id)
                        ON DELETE CASCADE
                )
                """
            )
            self._conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_compactions_conversation
                ON conversation_compactions (conversation_id, last_message_id)
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS compaction_items (
                    item_id            TEXT PRIMARY KEY,
                    compaction_id      TEXT NOT NULL,
                    category           TEXT NOT NULL,
                    content            TEXT NOT NULL,
                    ordinal            INTEGER NOT NULL,
                    CHECK (category IN ('facts', 'decisions', 'changes', 'open_questions')),
                    FOREIGN KEY (compaction_id)
                        REFERENCES conversation_compactions(compaction_id)
                        ON DELETE CASCADE
                )
                """
            )
            self._conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_compaction_items_compaction
                ON compaction_items (compaction_id, ordinal)
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS compaction_provenance (
                    item_id            TEXT NOT NULL,
                    source_message_id  INTEGER NOT NULL,
                    ordinal            INTEGER NOT NULL,
                    PRIMARY KEY (item_id, source_message_id),
                    FOREIGN KEY (item_id)
                        REFERENCES compaction_items(item_id)
                        ON DELETE CASCADE
                )
                """
            )

    def _validate_category(self, category: str) -> None:
        if category not in _CATEGORIES:
            raise CompactionCorruptError(f"Invalid compaction category: {category!r}")

    # ------------------------------------------------------------------
    # Save (atomic)
    # ------------------------------------------------------------------

    def save(self, compaction: ConversationCompaction) -> ConversationCompaction:
        """Persist a compaction atomically (record + items + provenance).

        Raises ``CompactionAlreadyExistsError`` when the compaction ID is
        already present, and ``CompactionCorruptError`` when the compaction
        references a missing conversation or nonexistent source messages.
        The supplied domain object is never mutated.
        """
        if not isinstance(compaction, ConversationCompaction):
            raise CompactionCorruptError("expected a ConversationCompaction")

        self._check_source_messages_exist(compaction)

        try:
            with self._conn:
                self._conn.execute(
                    """
                    INSERT INTO conversation_compactions (
                        compaction_id, conversation_id, first_message_id,
                        last_message_id, created_at, compaction_version, summary
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        compaction.compaction_id,
                        compaction.conversation_id,
                        compaction.first_message_id,
                        compaction.last_message_id,
                        compaction.created_at.isoformat(timespec="microseconds"),
                        compaction.compaction_version,
                        compaction.summary,
                    ),
                )
                for category in _CATEGORIES:
                    for ordinal, item in enumerate(getattr(compaction, category)):
                        self._insert_item(compaction.compaction_id, category, ordinal, item)
        except sqlite3.IntegrityError as exc:
            if "PRIMARY KEY" in str(exc) or "UNIQUE" in str(exc):
                raise CompactionAlreadyExistsError(
                    f"Compaction with ID {compaction.compaction_id} already exists"
                ) from exc
            raise CompactionCorruptError(f"Failed to save compaction: {exc}") from exc

        return compaction

    def _insert_item(
        self, compaction_id: str, category: str, ordinal: int, item: CompactionItem
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO compaction_items (item_id, compaction_id, category, content, ordinal)
            VALUES (?, ?, ?, ?, ?)
            """,
            (item.item_id, compaction_id, category, item.content, ordinal),
        )
        for prov_ordinal, message_id in enumerate(item.source_message_ids):
            self._conn.execute(
                """
                INSERT INTO compaction_provenance (item_id, source_message_id, ordinal)
                VALUES (?, ?, ?)
                """,
                (item.item_id, message_id, prov_ordinal),
            )

    def _check_source_messages_exist(self, compaction: ConversationCompaction) -> None:
        """Reject compactions whose provenance references nonexistent messages.

        Message existence is verified against the existing ``messages`` table
        for the compaction's conversation. Missing messages are never
        invented; the save fails instead of creating invalid provenance.
        """
        referenced: set[int] = set()
        for category in _CATEGORIES:
            for item in getattr(compaction, category):
                referenced.update(item.source_message_ids)
        if not referenced:
            return

        placeholders = ",".join("?" for _ in referenced)
        rows = self._conn.execute(
            f"SELECT id FROM messages WHERE conversation_id = ? AND id IN ({placeholders})",
            (compaction.conversation_id, *sorted(referenced)),
        ).fetchall()
        existing = {row["id"] for row in rows}
        missing = sorted(referenced - existing)
        if missing:
            raise CompactionCorruptError(
                "Compaction references source messages that do not exist "
                f"in conversation {compaction.conversation_id}: {missing}"
            )

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def get(self, compaction_id: str) -> ConversationCompaction | None:
        """Retrieve a compaction by ID, or ``None`` when absent."""
        row = self._conn.execute(
            "SELECT * FROM conversation_compactions WHERE compaction_id = ?",
            (compaction_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_compaction(row)

    def list_for_conversation(self, conversation_id: int) -> list[ConversationCompaction]:
        """List compactions for a conversation, in deterministic order."""
        rows = self._conn.execute(
            """
            SELECT * FROM conversation_compactions
            WHERE conversation_id = ?
            ORDER BY first_message_id ASC, compaction_id ASC
            """,
            (conversation_id,),
        ).fetchall()
        return [self._row_to_compaction(row) for row in rows]

    def get_latest_for_conversation(self, conversation_id: int) -> ConversationCompaction | None:
        """Return the compaction covering the greatest boundary, or ``None``.

        "Latest" is determined by ``last_message_id`` (the covered boundary)
        descending, with ``first_message_id`` then ``compaction_id`` as
        deterministic tie-breakers — never by insertion order or ``created_at``.
        """
        row = self._conn.execute(
            """
            SELECT * FROM conversation_compactions
            WHERE conversation_id = ?
            ORDER BY last_message_id DESC, first_message_id DESC, compaction_id ASC
            LIMIT 1
            """,
            (conversation_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_compaction(row)

    # ------------------------------------------------------------------
    # Row mapping
    # ------------------------------------------------------------------

    def _load_items(self, compaction_id: str) -> dict[str, tuple[CompactionItem, ...]]:
        item_rows = self._conn.execute(
            """
            SELECT * FROM compaction_items
            WHERE compaction_id = ?
            ORDER BY ordinal ASC
            """,
            (compaction_id,),
        ).fetchall()

        grouped: dict[str, list[CompactionItem]] = {category: [] for category in _CATEGORIES}
        for row in item_rows:
            category = row["category"]
            if category not in grouped:
                raise CompactionCorruptError(
                    f"Compaction {compaction_id} contains invalid category {category!r}"
                )
            source_ids = tuple(
                prov_row["source_message_id"]
                for prov_row in self._conn.execute(
                    """
                    SELECT source_message_id FROM compaction_provenance
                    WHERE item_id = ?
                    ORDER BY ordinal ASC
                    """,
                    (row["item_id"],),
                ).fetchall()
            )
            grouped[category].append(
                CompactionItem(
                    item_id=row["item_id"],
                    content=row["content"],
                    source_message_ids=source_ids,
                )
            )
        return {category: tuple(items) for category, items in grouped.items()}

    def _row_to_compaction(self, row: sqlite3.Row) -> ConversationCompaction:
        if row["compaction_version"] != SUPPORTED_COMPACTION_VERSION:
            raise CompactionCorruptError(
                f"Unsupported compaction version {row['compaction_version']} "
                f"for compaction {row['compaction_id']}"
            )
        items = self._load_items(row["compaction_id"])
        try:
            return ConversationCompaction(
                compaction_id=row["compaction_id"],
                conversation_id=row["conversation_id"],
                first_message_id=row["first_message_id"],
                last_message_id=row["last_message_id"],
                created_at=datetime.fromisoformat(row["created_at"]),
                compaction_version=row["compaction_version"],
                summary=row["summary"],
                facts=items["facts"],
                decisions=items["decisions"],
                changes=items["changes"],
                open_questions=items["open_questions"],
            )
        except (ValueError, TypeError, KeyError) as exc:
            raise CompactionCorruptError(
                f"Invalid compaction row {row['compaction_id']}: {exc}"
            ) from exc


__all__ = ["SUPPORTED_COMPACTION_VERSION", "SQLiteCompactionStore"]
