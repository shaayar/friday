"""Memory Storage Protocol — Primitive persistence operations for durable memories."""

from __future__ import annotations

from contextlib import AbstractContextManager
from datetime import datetime
from typing import Protocol

from friday.memory.models import Memory, MemoryScope, MemoryStatus, MemoryType


class MemoryStorage(Protocol):
    """Primitive persistence operations for durable memories.

    This protocol defines the low-level storage interface. It operates on
    Memory domain objects and knows nothing about memory semantics such as
    supersession cascades, invalidation policies, or distillation.
    """

    def save(self, memory: Memory) -> Memory:
        """Persist a memory.

        The memory must have a valid ID (assigned at domain construction time).
        If a memory with the same ID already exists, raises MemoryAlreadyExistsError.

        Returns the persisted memory (may have normalized timestamps).
        """
        ...

    def get(self, memory_id: str) -> Memory | None:
        """Retrieve a memory by ID. Returns None if not found."""
        ...

    def update(self, memory: Memory) -> Memory:
        """Update an existing memory.

        The memory must have an ID that exists in storage.
        Raises MemoryNotFoundError if the ID does not exist.
        Returns the updated memory.
        """
        ...

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
        """Query memories with deterministic filters.

        No semantic/vector search. All filters are optional and combine with AND.
        """
        ...

    def transaction(self) -> AbstractContextManager[None]:
        """Context manager for atomic multi-operation batches.

        Usage:
            with storage.transaction():
                storage.save(memory1)
                storage.update(memory2)
        """
        ...
