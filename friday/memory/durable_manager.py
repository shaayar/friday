"""Durable Memory Manager — High-level memory semantics for durable memory.

This manager owns durable-memory business logic (supersession, invalidation)
and delegates persistence to a MemoryStorage implementation.
"""

from __future__ import annotations

from datetime import UTC, datetime

from friday.memory.candidates import Resolution, ResolutionKind, candidate_to_memory
from friday.memory.exceptions import MemoryNotFoundError
from friday.memory.models import (
    Memory,
    MemoryScope,
    MemoryStatus,
    MemoryType,
)
from friday.memory.storage import MemoryStorage


def _utc_now() -> datetime:
    return datetime.now(UTC)


class DurableMemoryManager:
    """High-level operations for durable memory.

    Encapsulates memory semantics such as supersession and invalidation.
    Delegates primitive persistence to an injected MemoryStorage backend.
    """

    def __init__(self, storage: MemoryStorage) -> None:
        self._storage = storage

    def save(self, memory: Memory) -> Memory:
        """Persist a new memory."""
        return self._storage.save(memory)

    def get(self, memory_id: str) -> Memory | None:
        """Retrieve a memory by ID."""
        return self._storage.get(memory_id)

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
        return self._storage.query(
            scope=scope,
            memory_type=memory_type,
            status=status,
            project_id=project_id,
            conversation_id=conversation_id,
            valid_at=valid_at,
            created_after=created_after,
            created_before=created_before,
            limit=limit,
            offset=offset,
        )

    def invalidate(self, memory_id: str) -> Memory:
        """Mark a memory as invalidated.

        This is a semantic status transition — the memory remains in storage
        with status INVALIDATED and updated_at advanced.
        """
        with self._storage.transaction():
            return self._apply_invalidate(memory_id)

    def _apply_invalidate(self, memory_id: str) -> Memory:
        """Invalidate ``memory_id``. Assumes the caller holds a transaction."""
        memory = self._storage.get(memory_id)
        if memory is None:
            raise MemoryNotFoundError(f"Memory {memory_id} not found")

        invalidated = Memory(
            id=memory.id,
            type=memory.type,
            scope=memory.scope,
            content=memory.content,
            status=MemoryStatus.INVALIDATED,
            confidence=memory.confidence,
            provenance=memory.provenance,
            created_at=memory.created_at,
            updated_at=_utc_now(),
            valid_from=memory.valid_from,
            valid_until=memory.valid_until,
            supersedes=memory.supersedes,
            superseded_by=memory.superseded_by,
            project_id=memory.project_id,
        )

        return self._storage.update(invalidated)

    def supersede(self, old_memory_id: str, new_memory: Memory) -> tuple[Memory, Memory]:
        """Replace an existing memory with a new version.

        Atomically:
        1. Persist the new memory with supersedes = old_memory_id
        2. Mark the old memory as SUPERSEDED with superseded_by = new_memory.id

        Both operations succeed or both fail (transactional).
        """
        with self._storage.transaction():
            return self._apply_supersede(old_memory_id, new_memory)

    def _apply_supersede(self, old_memory_id: str, new_memory: Memory) -> tuple[Memory, Memory]:
        """Replace ``old_memory_id`` with ``new_memory``.

        Assumes the caller holds a transaction.
        """
        old_memory = self._storage.get(old_memory_id)
        if old_memory is None:
            raise MemoryNotFoundError(f"Memory {old_memory_id} not found")

        # Construct the new memory with supersedes link
        now = _utc_now()
        linked_new = Memory(
            id=new_memory.id,
            type=new_memory.type,
            scope=new_memory.scope,
            content=new_memory.content,
            status=MemoryStatus.ACTIVE,
            confidence=new_memory.confidence,
            provenance=new_memory.provenance,
            created_at=new_memory.created_at,
            updated_at=now,
            valid_from=new_memory.valid_from,
            valid_until=new_memory.valid_until,
            supersedes=old_memory_id,
            superseded_by=None,
            project_id=new_memory.project_id,
        )

        # Construct the old memory as superseded
        superseded_old = Memory(
            id=old_memory.id,
            type=old_memory.type,
            scope=old_memory.scope,
            content=old_memory.content,
            status=MemoryStatus.SUPERSEDED,
            confidence=old_memory.confidence,
            provenance=old_memory.provenance,
            created_at=old_memory.created_at,
            updated_at=now,
            valid_from=old_memory.valid_from,
            valid_until=old_memory.valid_until,
            supersedes=old_memory.supersedes,
            superseded_by=linked_new.id,
            project_id=old_memory.project_id,
        )

        # Atomic: both updates or neither
        saved_new = self._storage.save(linked_new)
        saved_old = self._storage.update(superseded_old)

        return saved_new, saved_old

    def apply_batch(self, resolutions: list[Resolution]) -> list[Memory | None]:
        """Apply a batch of resolutions atomically.

        Either the entire batch commits or the entire batch rolls back.
        Supported operations:

        - CREATE     → persist the candidate as a new memory.
        - SUPERSEDE  → replace ``existing_memory_id`` with the candidate.
        - INVALIDATE → mark ``existing_memory_id`` invalidated.
        - REJECT     → no-op (skipped).

        Returns one entry per resolution (persisted memory for CREATE/SUPERSEDE,
        the invalidated memory for INVALIDATE, None for REJECT).
        """
        if not resolutions:
            return []

        results: list[Memory | None] = []
        with self._storage.transaction():
            for resolution in resolutions:
                kind = resolution.kind
                candidate = resolution.candidate
                if kind is ResolutionKind.REJECT:
                    results.append(None)
                elif kind is ResolutionKind.INVALIDATE:
                    # existing_memory_id is guaranteed non-None by Resolution.__post_init__
                    assert resolution.existing_memory_id is not None
                    results.append(self._apply_invalidate(resolution.existing_memory_id))
                elif kind is ResolutionKind.CREATE:
                    # candidate is guaranteed non-None by Resolution.__post_init__
                    assert candidate is not None
                    memory = candidate_to_memory(candidate)
                    results.append(self._storage.save(memory))
                elif kind is ResolutionKind.SUPERSEDE:
                    # candidate and existing_memory_id are guaranteed
                    # non-None by Resolution.__post_init__
                    assert candidate is not None
                    assert resolution.existing_memory_id is not None
                    memory = candidate_to_memory(candidate)
                    saved_new, _ = self._apply_supersede(resolution.existing_memory_id, memory)
                    results.append(saved_new)
        return results

    def get_active(
        self,
        *,
        scope: MemoryScope | None = None,
        project_id: str | None = None,
        valid_at: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Memory]:
        """Convenience query for active memories.

        Defaults to ACTIVE status with optional scope/project/time filters.
        """
        return self.query(
            status=MemoryStatus.ACTIVE,
            scope=scope,
            project_id=project_id,
            valid_at=valid_at,
            limit=limit,
            offset=offset,
        )
