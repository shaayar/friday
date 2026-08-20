"""SQLite storage for the promotion ledger (Phase 4 M6.2, ADR-025).

Promotion ledger entries live in the EXISTING conversation database
(``~/.friday/data/conversations.db``) alongside compactions and raw
conversation history. Durable cross-conversation memory stays in
``memory.db``; this module never touches it.

The store is deliberately dumb: it persists validated
``CompactionPromotion`` domain objects and never decides promotability,
candidate/memory creation, supersession, project scope, confidence, or
promotion timing. The domain model remains the source of truth for
validation and state transitions.

``save`` inserts a NEW ledger entry keyed by ``CompactionPromotion.item_id``;
``replace`` persists a new immutable state for an EXISTING entry after a
domain transition. There is deliberately no generic ``update`` and no public
``delete`` (promotion history is audit state; deletion happens only through
the parent compaction/item cascade).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Self

from friday.compaction.exceptions import (
    PromotionAlreadyExistsError,
    PromotionCorruptError,
    PromotionNotFoundError,
)
from friday.compaction.promotion import (
    CompactionItemCategory,
    CompactionPromotion,
    PromotionResolutionKind,
    PromotionStatus,
)
from friday.config import config


def _default_database_path() -> Path:
    return config.FRIDAY_HOME / "data" / "conversations.db"


class SQLitePromotionStore:
    """SQLite persistence for promotion-ledger entries in conversations.db.

    The ledger is keyed by ``CompactionPromotion.item_id``; the database
    uniqueness constraint on ``item_id`` is authoritative (no
    check-then-insert, so concurrent saves produce at most one row).
    """

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

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def _initialize_schema(self) -> None:
        """Create the promotion-ledger tables if they do not exist.

        Additive and idempotent, matching the compaction store's
        ``CREATE TABLE IF NOT EXISTS`` pattern. The base conversation,
        compaction, and item tables are (re)declared identically so a fresh
        database — or a database opened through this store alone — is
        self-contained and the promotion foreign keys are enforceable. Does
        not alter or version the existing schema.
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
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS compaction_promotions (
                    item_id            TEXT PRIMARY KEY,
                    compaction_id      TEXT NOT NULL,
                    category           TEXT NOT NULL,
                    status             TEXT NOT NULL,
                    resolution_kind    TEXT,
                    resolution_reason  TEXT,
                    retry_count        INTEGER NOT NULL DEFAULT 0,
                    last_error         TEXT,
                    created_at         TEXT NOT NULL,
                    updated_at         TEXT NOT NULL,
                    CHECK (category IN ('facts', 'decisions', 'changes', 'open_questions')),
                    CHECK (status IN ('pending', 'promoted', 'rejected')),
                    CHECK (resolution_kind IS NULL OR resolution_kind IN ('create', 'supersede')),
                    CHECK (retry_count >= 0),
                    CHECK (updated_at >= created_at),
                    FOREIGN KEY (item_id)
                        REFERENCES compaction_items(item_id)
                        ON DELETE CASCADE,
                    FOREIGN KEY (compaction_id)
                        REFERENCES conversation_compactions(compaction_id)
                        ON DELETE CASCADE
                )
                """
            )
            self._conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_compaction_promotions_compaction
                ON compaction_promotions (compaction_id)
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS promotion_resolved_memory_ids (
                    item_id    TEXT NOT NULL,
                    memory_id  TEXT NOT NULL,
                    ordinal    INTEGER NOT NULL,
                    PRIMARY KEY (item_id, memory_id),
                    CHECK (memory_id != ''),
                    FOREIGN KEY (item_id)
                        REFERENCES compaction_promotions(item_id)
                        ON DELETE CASCADE
                )
                """
            )

    # ------------------------------------------------------------------
    # Save / replace (atomic)
    # ------------------------------------------------------------------

    def save(self, promotion: CompactionPromotion) -> CompactionPromotion:
        """Insert a NEW promotion-ledger entry for a compaction item.

        Raises ``PromotionAlreadyExistsError`` when the ``item_id`` is
        already present (the uniqueness constraint is authoritative; this is
        never a check-then-insert race) and ``PromotionCorruptError`` when
        the item does not exist in ``compaction_items`` or a write fails.
        The supplied domain object is never mutated.
        """
        if not isinstance(promotion, CompactionPromotion):
            raise PromotionCorruptError("expected a CompactionPromotion")

        try:
            with self._conn:
                self._insert_promotion(promotion)
        except sqlite3.IntegrityError as exc:
            if "PRIMARY KEY" in str(exc) or "UNIQUE" in str(exc):
                raise PromotionAlreadyExistsError(
                    f"Promotion for item {promotion.item_id} already exists"
                ) from exc
            raise PromotionCorruptError(f"Failed to save promotion: {exc}") from exc

        return promotion

    def replace(self, promotion: CompactionPromotion) -> CompactionPromotion:
        """Persist a new immutable state for an EXISTING promotion entry.

        State changes happen through the domain model (``mark_promoted``,
        ``mark_rejected``, ``request_reconsideration``,
        ``record_transient_failure``); the resulting immutable object is
        persisted here. Raises ``PromotionNotFoundError`` when the item_id is
        absent. This narrow replace exists because the domain model is
        immutable and transitioned states share the item_id key; it is not a
        generic mutable update operation.
        """
        if not isinstance(promotion, CompactionPromotion):
            raise PromotionCorruptError("expected a CompactionPromotion")

        try:
            with self._conn:
                cursor = self._conn.execute(
                    """
                    UPDATE compaction_promotions SET
                        compaction_id = ?, category = ?, status = ?,
                        resolution_kind = ?, resolution_reason = ?,
                        retry_count = ?, last_error = ?,
                        created_at = ?, updated_at = ?
                    WHERE item_id = ?
                    """,
                    (
                        promotion.compaction_id,
                        promotion.category.value,
                        promotion.status.value,
                        promotion.resolution_kind.value if promotion.resolution_kind is not None else None,
                        promotion.resolution_reason,
                        promotion.retry_count,
                        promotion.last_error,
                        promotion.created_at.isoformat(timespec="microseconds"),
                        promotion.updated_at.isoformat(timespec="microseconds"),
                        promotion.item_id,
                    ),
                )
                if cursor.rowcount == 0:
                    raise PromotionNotFoundError(
                        f"Promotion for item {promotion.item_id} not found"
                    )
                self._conn.execute(
                    "DELETE FROM promotion_resolved_memory_ids WHERE item_id = ?",
                    (promotion.item_id,),
                )
                self._insert_memory_ids(promotion.item_id, promotion.resolved_memory_ids)
        except PromotionNotFoundError:
            raise
        except sqlite3.IntegrityError as exc:
            raise PromotionCorruptError(f"Failed to replace promotion: {exc}") from exc

        return promotion

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def get(self, item_id: str) -> CompactionPromotion | None:
        """Retrieve a promotion by item_id, or ``None`` when absent."""
        row = self._conn.execute(
            "SELECT * FROM compaction_promotions WHERE item_id = ?",
            (item_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_promotion(row)

    def list_for_compaction(self, compaction_id: str) -> list[CompactionPromotion]:
        """List all promotion-ledger entries for a compaction, deterministically ordered."""
        rows = self._conn.execute(
            """
            SELECT * FROM compaction_promotions
            WHERE compaction_id = ?
            ORDER BY created_at ASC, item_id ASC
            """,
            (compaction_id,),
        ).fetchall()
        return [self._row_to_promotion(row) for row in rows]

    # ------------------------------------------------------------------
    # Row mapping
    # ------------------------------------------------------------------

    def _insert_promotion(self, promotion: CompactionPromotion) -> None:
        self._conn.execute(
            """
            INSERT INTO compaction_promotions (
                item_id, compaction_id, category, status, resolution_kind,
                resolution_reason, retry_count, last_error, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                promotion.item_id,
                promotion.compaction_id,
                promotion.category.value,
                promotion.status.value,
                promotion.resolution_kind.value if promotion.resolution_kind is not None else None,
                promotion.resolution_reason,
                promotion.retry_count,
                promotion.last_error,
                promotion.created_at.isoformat(timespec="microseconds"),
                promotion.updated_at.isoformat(timespec="microseconds"),
            ),
        )
        self._insert_memory_ids(promotion.item_id, promotion.resolved_memory_ids)

    def _insert_memory_ids(self, item_id: str, memory_ids: tuple[str, ...]) -> None:
        for ordinal, memory_id in enumerate(memory_ids):
            self._conn.execute(
                """
                INSERT INTO promotion_resolved_memory_ids (item_id, memory_id, ordinal)
                VALUES (?, ?, ?)
                """,
                (item_id, memory_id, ordinal),
            )

    def _load_memory_ids(self, item_id: str) -> tuple[str, ...]:
        rows = self._conn.execute(
            """
            SELECT memory_id FROM promotion_resolved_memory_ids
            WHERE item_id = ?
            ORDER BY ordinal ASC
            """,
            (item_id,),
        ).fetchall()
        memory_ids = tuple(row["memory_id"] for row in rows)
        if any(not str(memory_id).strip() for memory_id in memory_ids):
            raise PromotionCorruptError(
                f"Invalid resolved memory ID for item {item_id}"
            )
        return memory_ids

    def _row_to_promotion(self, row: sqlite3.Row) -> CompactionPromotion:
        memory_ids = self._load_memory_ids(row["item_id"])
        try:
            return CompactionPromotion(
                item_id=row["item_id"],
                compaction_id=row["compaction_id"],
                category=CompactionItemCategory(row["category"]),
                status=PromotionStatus(row["status"]),
                resolved_memory_ids=memory_ids,
                resolution_kind=(
                    None
                    if row["resolution_kind"] is None
                    else PromotionResolutionKind(row["resolution_kind"])
                ),
                resolution_reason=row["resolution_reason"],
                retry_count=row["retry_count"],
                last_error=row["last_error"],
                created_at=datetime.fromisoformat(row["created_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"]),
            )
        except (ValueError, TypeError, KeyError) as exc:
            raise PromotionCorruptError(
                f"Invalid promotion row {row['item_id']}: {exc}"
            ) from exc


__all__ = ["SQLitePromotionStore"]
