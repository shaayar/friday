"""
Memory Manager — High-level memory operations.

This module owns memory-level semantics and delegates storage concerns
to an injected storage backend.
"""

from __future__ import annotations

from typing import Protocol

from friday.memory.sqlite_store import Conversation, Message


class ConversationStorage(Protocol):
    """Protocol defining the storage operations required by MemoryManager."""

    def create_conversation(self) -> Conversation: ...

    def save_message(self, conversation_id: int, role: str, content: str) -> Message: ...

    def get_conversation(self, conversation_id: int) -> Conversation | None: ...

    def get_recent_messages(self, conversation_id: int, limit: int = 20) -> list[Message]: ...



class MemoryManager:
    """
    High-level memory operations for conversation history.

    Delegates storage to an injected backend implementing ConversationStorage.
    """

    def __init__(self, storage: ConversationStorage) -> None:
        self._storage = storage

    def create_conversation(self) -> Conversation:
        """Create a new conversation."""
        return self._storage.create_conversation()

    def save_message(self, conversation_id: int, role: str, content: str) -> Message:
        """Save a message to a conversation."""
        return self._storage.save_message(conversation_id, role, content)

    def get_conversation(self, conversation_id: int) -> Conversation | None:
        """Retrieve a conversation by ID."""
        return self._storage.get_conversation(conversation_id)

    def get_recent_messages(self, conversation_id: int, limit: int = 20) -> list[Message]:
        """Retrieve recent messages for a conversation."""
        return self._storage.get_recent_messages(conversation_id, limit)
