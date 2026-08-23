"""
Tests for MemoryManager implementation.
"""

from __future__ import annotations

import tempfile
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock

import pytest

from friday.memory.manager import ConversationStorage, MemoryManager
from friday.memory.sqlite_store import Conversation, Message, SQLiteConversationStore


class TestMemoryManager:
    """Test suite for MemoryManager."""

    @pytest.fixture
    def mock_storage(self) -> Mock:
        """Create a mock storage implementing ConversationStorage."""
        # Use spec_set=True to only allow methods defined in the Protocol
        return Mock(spec_set=ConversationStorage)

    @pytest.fixture
    def memory_manager(self, mock_storage: Mock) -> MemoryManager:
        """Create a MemoryManager with mock storage."""
        return MemoryManager(mock_storage)

    def test_create_conversation_delegates(
        self, memory_manager: MemoryManager, mock_storage: Mock
    ) -> None:
        """Test that create_conversation delegates to storage."""
        expected = Conversation(
            id=1,
            created_at="2024-01-01T00:00:00.000000+00:00",
            updated_at="2024-01-01T00:00:00.000000+00:00",
        )
        mock_storage.create_conversation.return_value = expected

        result = memory_manager.create_conversation()

        assert result is expected
        mock_storage.create_conversation.assert_called_once()

    def test_save_message_delegates(
        self, memory_manager: MemoryManager, mock_storage: Mock
    ) -> None:
        """Test that save_message delegates to storage."""
        expected = Message(
            id=1,
            conversation_id=1,
            role="user",
            content="Hello",
            created_at="2024-01-01T00:00:00.000000+00:00",
        )
        mock_storage.save_message.return_value = expected

        result = memory_manager.save_message(1, "user", "Hello")

        assert result is expected
        mock_storage.save_message.assert_called_once_with(1, "user", "Hello")

    def test_get_conversation_delegates(
        self, memory_manager: MemoryManager, mock_storage: Mock
    ) -> None:
        """Test that get_conversation delegates to storage."""
        expected = Conversation(
            id=1,
            created_at="2024-01-01T00:00:00.000000+00:00",
            updated_at="2024-01-01T00:00:00.000000+00:00",
        )
        mock_storage.get_conversation.return_value = expected

        result = memory_manager.get_conversation(1)

        assert result is expected
        mock_storage.get_conversation.assert_called_once_with(1)

    def test_get_recent_messages_delegates(
        self, memory_manager: MemoryManager, mock_storage: Mock
    ) -> None:
        """Test that get_recent_messages delegates to storage."""
        expected = [
            Message(
                id=1,
                conversation_id=1,
                role="user",
                content="Hello",
                created_at="2024-01-01T00:00:00.000000+00:00",
            )
        ]
        mock_storage.get_recent_messages.return_value = expected

        result = memory_manager.get_recent_messages(1, limit=10)

        assert result is expected
        mock_storage.get_recent_messages.assert_called_once_with(1, 10)

    def test_get_recent_messages_default_limit(
        self, memory_manager: MemoryManager, mock_storage: Mock
    ) -> None:
        """Test that get_recent_messages uses default limit."""
        mock_storage.get_recent_messages.return_value = []

        memory_manager.get_recent_messages(1)

        mock_storage.get_recent_messages.assert_called_once_with(1, 20)


class FakeConversationStore:
    """Fake in-memory implementation of ConversationStorage for testing Protocol boundary."""

    def __init__(self) -> None:
        self._conversations: dict[int, Conversation] = {}
        self._messages: dict[int, list[Message]] = {}
        self._next_conv_id = 1
        self._next_msg_id = 1

    def _utc_now(self) -> str:
        return datetime.now(UTC).isoformat(timespec="microseconds")

    def create_conversation(self) -> Conversation:
        now = self._utc_now()
        conv = Conversation(id=self._next_conv_id, created_at=now, updated_at=now)
        self._conversations[self._next_conv_id] = conv
        self._messages[self._next_conv_id] = []
        self._next_conv_id += 1
        return conv

    def save_message(self, conversation_id: int, role: str, content: str) -> Message:
        if conversation_id not in self._conversations:
            raise ValueError(f"Conversation {conversation_id} does not exist")
        now = self._utc_now()
        msg = Message(
            id=self._next_msg_id,
            conversation_id=conversation_id,
            role=role,
            content=content,
            created_at=now,
        )
        self._messages[conversation_id].append(msg)
        # Update conversation timestamp
        conv = self._conversations[conversation_id]
        self._conversations[conversation_id] = Conversation(
            id=conv.id,
            created_at=conv.created_at,
            updated_at=now,
        )
        self._next_msg_id += 1
        return msg

    def get_conversation(self, conversation_id: int) -> Conversation | None:
        return self._conversations.get(conversation_id)

    def get_recent_messages(
        self, conversation_id: int, limit: int = 20
    ) -> list[Message]:
        messages = self._messages.get(conversation_id, [])
        return messages[-limit:]


class TestMemoryManagerWithFakeStore:
    """Integration tests with FakeConversationStore to prove Protocol boundary works."""

    @pytest.fixture
    def store(self) -> FakeConversationStore:
        """Create a fake store instance."""
        return FakeConversationStore()

    @pytest.fixture
    def memory(self, store: FakeConversationStore) -> MemoryManager:
        """Create a MemoryManager with fake storage."""
        return MemoryManager(store)

    def test_create_conversation_fake_store(self, memory: MemoryManager) -> None:
        """Test creating a conversation through MemoryManager with fake store."""
        conversation = memory.create_conversation()

        assert isinstance(conversation, Conversation)
        assert conversation.id > 0
        assert conversation.created_at == conversation.updated_at

    def test_save_message_fake_store(self, memory: MemoryManager) -> None:
        """Test saving a message through MemoryManager with fake store."""
        conversation = memory.create_conversation()
        message = memory.save_message(conversation.id, "user", "Hello, world!")

        assert isinstance(message, Message)
        assert message.id > 0
        assert message.conversation_id == conversation.id
        assert message.role == "user"
        assert message.content == "Hello, world!"

    def test_get_conversation_fake_store(self, memory: MemoryManager) -> None:
        """Test retrieving a conversation through MemoryManager with fake store."""
        created = memory.create_conversation()
        retrieved = memory.get_conversation(created.id)

        assert retrieved is not None
        assert retrieved.id == created.id
        assert retrieved.created_at == created.created_at
        assert retrieved.updated_at == created.updated_at

    def test_get_nonexistent_conversation_fake_store(
        self, memory: MemoryManager
    ) -> None:
        """Test retrieving a non-existent conversation with fake store."""
        result = memory.get_conversation(99999)
        assert result is None

    def test_get_recent_messages_fake_store(self, memory: MemoryManager) -> None:
        """Test retrieving recent messages through MemoryManager with fake store."""
        conversation = memory.create_conversation()

        for i in range(5):
            memory.save_message(
                conversation.id, "user" if i % 2 == 0 else "assistant", f"Message {i}"
            )

        messages = memory.get_recent_messages(conversation.id, limit=3)

        assert len(messages) == 3
        assert messages[0].content == "Message 2"
        assert messages[1].content == "Message 3"
        assert messages[2].content == "Message 4"

    def test_get_recent_messages_default_limit_fake_store(
        self, memory: MemoryManager
    ) -> None:
        """Test default limit of 20 messages with fake store."""
        conversation = memory.create_conversation()

        for i in range(25):
            memory.save_message(conversation.id, "user", f"Message {i}")

        messages = memory.get_recent_messages(conversation.id)

        assert len(messages) == 20
        assert messages[0].content == "Message 5"
        assert messages[-1].content == "Message 24"

    def test_message_updates_conversation_timestamp_fake_store(
        self, memory: MemoryManager
    ) -> None:
        """Test that saving a message updates conversation's updated_at with fake store."""
        conversation = memory.create_conversation()
        original_updated_at = conversation.updated_at

        import time

        time.sleep(0.01)

        memory.save_message(conversation.id, "user", "Test message")
        updated_conversation = memory.get_conversation(conversation.id)

        assert updated_conversation is not None
        assert updated_conversation.updated_at > original_updated_at
        assert updated_conversation.created_at == original_updated_at

    def test_multiple_conversations_isolated_fake_store(
        self, memory: MemoryManager
    ) -> None:
        """Test that multiple conversations are isolated in fake store."""
        conv1 = memory.create_conversation()
        conv2 = memory.create_conversation()

        memory.save_message(conv1.id, "user", "Conv1 message")
        memory.save_message(conv2.id, "user", "Conv2 message")

        messages1 = memory.get_recent_messages(conv1.id)
        messages2 = memory.get_recent_messages(conv2.id)

        assert len(messages1) == 1
        assert messages1[0].content == "Conv1 message"
        assert len(messages2) == 1
        assert messages2[0].content == "Conv2 message"


class TestMemoryManagerWithSQLiteStore:
    """Integration tests with SQLiteConversationStore."""

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
        temp_db_path.unlink(missing_ok=True)

    @pytest.fixture
    def memory(self, store: SQLiteConversationStore) -> MemoryManager:
        """Create a MemoryManager with SQLite storage."""
        return MemoryManager(store)

    def test_create_conversation_integration(self, memory: MemoryManager) -> None:
        """Test creating a conversation through MemoryManager."""
        conversation = memory.create_conversation()

        assert isinstance(conversation, Conversation)
        assert conversation.id > 0
        assert conversation.created_at == conversation.updated_at

    def test_save_message_integration(self, memory: MemoryManager) -> None:
        """Test saving a message through MemoryManager."""
        conversation = memory.create_conversation()
        message = memory.save_message(conversation.id, "user", "Hello, world!")

        assert isinstance(message, Message)
        assert message.id > 0
        assert message.conversation_id == conversation.id
        assert message.role == "user"
        assert message.content == "Hello, world!"

    def test_get_conversation_integration(self, memory: MemoryManager) -> None:
        """Test retrieving a conversation through MemoryManager."""
        created = memory.create_conversation()
        retrieved = memory.get_conversation(created.id)

        assert retrieved is not None
        assert retrieved.id == created.id
        assert retrieved.created_at == created.created_at
        assert retrieved.updated_at == created.updated_at

    def test_get_nonexistent_conversation_integration(
        self, memory: MemoryManager
    ) -> None:
        """Test retrieving a non-existent conversation."""
        result = memory.get_conversation(99999)
        assert result is None

    def test_get_recent_messages_integration(self, memory: MemoryManager) -> None:
        """Test retrieving recent messages through MemoryManager."""
        conversation = memory.create_conversation()

        for i in range(5):
            memory.save_message(
                conversation.id, "user" if i % 2 == 0 else "assistant", f"Message {i}"
            )

        messages = memory.get_recent_messages(conversation.id, limit=3)

        assert len(messages) == 3
        assert messages[0].content == "Message 2"
        assert messages[1].content == "Message 3"
        assert messages[2].content == "Message 4"

    def test_get_recent_messages_default_limit_integration(
        self, memory: MemoryManager
    ) -> None:
        """Test default limit of 20 messages."""
        conversation = memory.create_conversation()

        for i in range(25):
            memory.save_message(conversation.id, "user", f"Message {i}")

        messages = memory.get_recent_messages(conversation.id)

        assert len(messages) == 20
        assert messages[0].content == "Message 5"
        assert messages[-1].content == "Message 24"

    def test_message_updates_conversation_timestamp_integration(
        self, memory: MemoryManager
    ) -> None:
        """Test that saving a message updates conversation's updated_at."""
        conversation = memory.create_conversation()
        original_updated_at = conversation.updated_at

        import time

        time.sleep(0.01)

        memory.save_message(conversation.id, "user", "Test message")
        updated_conversation = memory.get_conversation(conversation.id)

        assert updated_conversation is not None
        assert updated_conversation.updated_at > original_updated_at
        assert updated_conversation.created_at == original_updated_at

    def test_context_manager_integration(self, temp_db_path: Path) -> None:
        """Test using MemoryManager as context manager with SQLite store."""
        with SQLiteConversationStore(temp_db_path) as store:
            memory = MemoryManager(store)
            conversation = memory.create_conversation()
            memory.save_message(conversation.id, "user", "Hello")

        # Data should persist
        with SQLiteConversationStore(temp_db_path) as store2:
            memory2 = MemoryManager(store2)
            retrieved = memory2.get_conversation(conversation.id)
            assert retrieved is not None
            assert retrieved.id == conversation.id

            messages = memory2.get_recent_messages(conversation.id)
            assert len(messages) == 1
            assert messages[0].content == "Hello"

        temp_db_path.unlink(missing_ok=True)

    def test_memory_manager_no_sqlite_knowledge(self, memory: MemoryManager) -> None:
        """Test that MemoryManager doesn't expose SQLite internals."""
        conversation = memory.create_conversation()
        message = memory.save_message(conversation.id, "user", "Test")

        # Should return domain objects, not sqlite3.Row or cursors
        assert type(conversation).__name__ == "Conversation"
        assert type(message).__name__ == "Message"
        assert not hasattr(conversation, "_conn")
        assert not hasattr(message, "_conn")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
