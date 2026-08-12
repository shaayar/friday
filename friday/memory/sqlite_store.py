"""
SQLite storage for conversation history.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

def _default_database_path() -> Path:
    return Path.home() / ".friday" / "data" / "conversations.db"


@dataclass(frozen=True, slots=True)
class Conversation:
    id: int
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class Message:
    id: int
    conversation_id: int
    role: str
    content: str
    created_at: str


class SQLiteConversationStore:
    def __init__(self, db_path: str | Path | None = None) -> None:
        self._db_path = Path(db_path) if db_path is not None else _default_database_path()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._initialize_schema()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "SQLiteConversationStore":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def create_conversation(self) -> Conversation:
        now = self._utc_now()
        with self._conn:
            cursor = self._conn.execute(
                """
                INSERT INTO conversations (created_at, updated_at)
                VALUES (?, ?)
                """,
                (now, now),
            )
        conversation_id = int(cursor.lastrowid)
        return Conversation(id=conversation_id, created_at=now, updated_at=now)

    def save_message(self, conversation_id: int, role: str, content: str) -> Message:
        now = self._utc_now()
        with self._conn:
            self._conn.execute(
                """
                UPDATE conversations
                SET updated_at = ?
                WHERE id = ?
                """,
                (now, conversation_id),
            )
            cursor = self._conn.execute(
                """
                INSERT INTO messages (conversation_id, role, content, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (conversation_id, role, content, now),
            )
        message_id = int(cursor.lastrowid)
        return Message(
            id=message_id,
            conversation_id=conversation_id,
            role=role,
            content=content,
            created_at=now,
        )

    def get_conversation(self, conversation_id: int) -> Conversation | None:
        row = self._conn.execute(
            """
            SELECT id, created_at, updated_at
            FROM conversations
            WHERE id = ?
            """,
            (conversation_id,),
        ).fetchone()
        if row is None:
            return None
        return Conversation(
            id=int(row["id"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def get_recent_messages(self, conversation_id: int, limit: int = 20) -> list[Message]:
        rows = self._conn.execute(
            """
            SELECT id, conversation_id, role, content, created_at
            FROM messages
            WHERE conversation_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (conversation_id, limit),
        ).fetchall()
        messages = [
            Message(
                id=int(row["id"]),
                conversation_id=int(row["conversation_id"]),
                role=row["role"],
                content=row["content"],
                created_at=row["created_at"],
            )
            for row in reversed(rows)
        ]
        return messages

    def _initialize_schema(self) -> None:
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

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="microseconds")
