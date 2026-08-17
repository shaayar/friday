"""
Tests for SQLiteConversationStore implementation.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from friday.memory.sqlite_store import Conversation, Message, SQLiteConversationStore


class TestSQLiteConversationStore:
    """Test suite for SQLiteConversationStore."""

    @pytest.fixture
    def temp_db_path(self) -> Path:
        """Create a temporary database path for testing."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            return Path(f.name)

    @pytest.fixture
    def store(self, temp_db_path: Path) -> SQLiteConversationStore:
        """Create a store instance with temporary database."""
        store = SQLiteConversationStore(temp_db_path)
        yield store
        store.close()
        # Clean up temp file
        temp_db_path.unlink(missing_ok=True)

    def test_create_conversation(self, store: SQLiteConversationStore) -> None:
        """Test creating a new conversation."""
        conversation = store.create_conversation()

        assert isinstance(conversation, Conversation)
        assert conversation.id > 0
        assert conversation.created_at == conversation.updated_at
        assert "T" in conversation.created_at  # ISO format

    def test_create_multiple_conversations(self, store: SQLiteConversationStore) -> None:
        """Test creating multiple conversations gets unique IDs."""
        conv1 = store.create_conversation()
        conv2 = store.create_conversation()
        conv3 = store.create_conversation()

        assert conv1.id < conv2.id < conv3.id
        assert conv1.id > 0 and conv2.id > 0 and conv3.id > 0

    def test_get_conversation(self, store: SQLiteConversationStore) -> None:
        """Test retrieving a conversation by ID."""
        created = store.create_conversation()
        retrieved = store.get_conversation(created.id)

        assert retrieved is not None
        assert retrieved.id == created.id
        assert retrieved.created_at == created.created_at
        assert retrieved.updated_at == created.updated_at

    def test_get_nonexistent_conversation(self, store: SQLiteConversationStore) -> None:
        """Test retrieving a non-existent conversation returns None."""
        result = store.get_conversation(99999)
        assert result is None

    def test_save_message(self, store: SQLiteConversationStore) -> None:
        """Test saving a message to a conversation."""
        conversation = store.create_conversation()
        message = store.save_message(conversation.id, "user", "Hello, world!")

        assert isinstance(message, Message)
        assert message.id > 0
        assert message.conversation_id == conversation.id
        assert message.role == "user"
        assert message.content == "Hello, world!"
        assert "T" in message.created_at  # ISO format

    def test_save_multiple_messages(self, store: SQLiteConversationStore) -> None:
        """Test saving multiple messages to a conversation."""
        conversation = store.create_conversation()

        msg1 = store.save_message(conversation.id, "user", "First message")
        msg2 = store.save_message(conversation.id, "assistant", "Second message")
        msg3 = store.save_message(conversation.id, "user", "Third message")

        assert msg1.id < msg2.id < msg3.id
        assert all(m.conversation_id == conversation.id for m in [msg1, msg2, msg3])

    def test_get_recent_messages(self, store: SQLiteConversationStore) -> None:
        """Test retrieving recent messages for a conversation."""
        conversation = store.create_conversation()

        # Save 5 messages
        for i in range(5):
            store.save_message(conversation.id, "user" if i % 2 == 0 else "assistant", f"Message {i}")

        messages = store.get_recent_messages(conversation.id, limit=3)

        assert len(messages) == 3
        # Should return in chronological order (oldest first after reversing)
        assert messages[0].content == "Message 2"
        assert messages[1].content == "Message 3"
        assert messages[2].content == "Message 4"

    def test_get_recent_messages_default_limit(self, store: SQLiteConversationStore) -> None:
        """Test default limit of 20 messages."""
        conversation = store.create_conversation()

        # Save 25 messages
        for i in range(25):
            store.save_message(conversation.id, "user", f"Message {i}")

        messages = store.get_recent_messages(conversation.id)

        # Should return only 20 (default limit)
        assert len(messages) == 20
        # Should be the last 20 messages (5-24)
        assert messages[0].content == "Message 5"
        assert messages[-1].content == "Message 24"

    def test_get_recent_messages_empty_conversation(self, store: SQLiteConversationStore) -> None:
        """Test retrieving messages from empty conversation."""
        conversation = store.create_conversation()
        messages = store.get_recent_messages(conversation.id)

        assert messages == []

    def test_get_recent_messages_nonexistent_conversation(self, store: SQLiteConversationStore) -> None:
        """Test retrieving messages from non-existent conversation."""
        messages = store.get_recent_messages(99999)
        assert messages == []

    def test_message_updates_conversation_timestamp(self, store: SQLiteConversationStore) -> None:
        """Test that saving a message updates the conversation's updated_at."""
        conversation = store.create_conversation()
        original_updated_at = conversation.updated_at

        # Small delay to ensure timestamp difference
        import time
        time.sleep(0.01)

        store.save_message(conversation.id, "user", "Test message")
        updated_conversation = store.get_conversation(conversation.id)

        assert updated_conversation is not None
        assert updated_conversation.updated_at > original_updated_at
        assert updated_conversation.created_at == original_updated_at  # created_at unchanged

    def test_foreign_key_cascade_delete(self, store: SQLiteConversationStore) -> None:
        """Test that deleting a conversation cascades to messages."""
        conversation = store.create_conversation()
        store.save_message(conversation.id, "user", "Test message")
        store.save_message(conversation.id, "assistant", "Response")

        # Verify messages exist
        messages = store.get_recent_messages(conversation.id)
        assert len(messages) == 2

        # Delete conversation directly via SQL
        with store._conn:
            store._conn.execute("DELETE FROM conversations WHERE id = ?", (conversation.id,))

        # Messages should be gone due to CASCADE
        messages = store.get_recent_messages(conversation.id)
        assert messages == []

    def test_context_manager(self, temp_db_path: Path) -> None:
        """Test using store as context manager."""
        with SQLiteConversationStore(temp_db_path) as store:
            conversation = store.create_conversation()
            store.save_message(conversation.id, "user", "Hello")

        # Store should be closed, but data persists
        with SQLiteConversationStore(temp_db_path) as store2:
            retrieved = store2.get_conversation(conversation.id)
            assert retrieved is not None
            assert retrieved.id == conversation.id

            messages = store2.get_recent_messages(conversation.id)
            assert len(messages) == 1
            assert messages[0].content == "Hello"

        temp_db_path.unlink(missing_ok=True)

    def test_concurrent_stores_same_db(self, temp_db_path: Path) -> None:
        """Test multiple store instances sharing the same database."""
        store1 = SQLiteConversationStore(temp_db_path)
        store2 = SQLiteConversationStore(temp_db_path)

        try:
            conv = store1.create_conversation()
            store1.save_message(conv.id, "user", "From store1")

            # Should be visible in store2
            messages = store2.get_recent_messages(conv.id)
            assert len(messages) == 1
            assert messages[0].content == "From store1"

            store2.save_message(conv.id, "assistant", "From store2")
            messages = store1.get_recent_messages(conv.id)
            assert len(messages) == 2
        finally:
            store1.close()
            store2.close()
            temp_db_path.unlink(missing_ok=True)

    def test_default_database_path(self) -> None:
        """Test that default database path works."""
        # Use a custom path to avoid polluting user's home
        import os
        original_home = os.environ.get("HOME")
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["HOME"] = tmpdir
            try:
                store = SQLiteConversationStore()
                conversation = store.create_conversation()
                assert conversation.id > 0
                store.close()
            finally:
                if original_home:
                    os.environ["HOME"] = original_home
                else:
                    del os.environ["HOME"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])