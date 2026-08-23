"""MemoryCandidate — the temporary, pre-identity proposal for durable memory.

A candidate is what the extractor proposes and the resolver disposes. It is
deliberately NOT a ``Memory``: it carries no identity, no lifecycle fields,
and no storage concerns. Evidence and reasoning are attached so the resolver
can validate, deduplicate, and decide without touching storage.

``Resolution`` describes what the resolver decided to do with a candidate.
``candidate_to_memory`` maps a candidate into a durable ``Memory`` at the
moment the ``DurableMemoryManager`` executes a resolution.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from friday.memory.models import (
    Memory,
    MemoryConfidence,
    MemoryProvenance,
    MemoryScope,
    MemoryStatus,
    MemoryType,
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class ResolutionKind(StrEnum):
    CREATE = "create"
    SUPERSEDE = "supersede"
    INVALIDATE = "invalidate"
    REJECT = "reject"


@dataclass(frozen=True, slots=True)
class MemoryCandidate:
    """A proposed durable memory, before validation and resolution.

    Temporary by construction: it is never persisted and carries no durable
    identity. All fields must be validated before any resolution is formed.
    """

    type: MemoryType
    scope: MemoryScope
    content: str
    confidence: MemoryConfidence
    source_conversation_id: str | int
    source_message_ids: tuple[str | int, ...]
    project_id: str | None = None
    reasoning: str | None = None

    def __post_init__(self) -> None:
        self._validate_type_and_scope()
        self._validate_content()
        self._validate_confidence()
        self._validate_conversation_id()
        self._validate_message_ids()
        self._validate_project_id()

    def _validate_type_and_scope(self) -> None:
        if not isinstance(self.type, MemoryType):
            raise TypeError(f"Invalid memory type: {self.type!r}")
        if not isinstance(self.scope, MemoryScope):
            raise TypeError(f"Invalid memory scope: {self.scope!r}")
        expected_scope = self.type.default_scope
        if self.scope is not expected_scope:
            raise ValueError(
                f"Memory type {self.type.value!r} must use scope {expected_scope.value!r}"
            )

    def _validate_content(self) -> None:
        if not isinstance(self.content, str) or not self.content.strip():
            raise ValueError("content cannot be empty")
        object.__setattr__(self, "content", self.content)

    def _validate_confidence(self) -> None:
        if not isinstance(self.confidence, MemoryConfidence):
            raise TypeError(f"Invalid confidence: {self.confidence!r}")

    def _validate_conversation_id(self) -> None:
        conversation_id = str(self.source_conversation_id).strip()
        if not conversation_id:
            raise ValueError("source_conversation_id cannot be empty")
        object.__setattr__(self, "source_conversation_id", conversation_id)

    def _validate_message_ids(self) -> None:
        message_ids = tuple(str(message_id).strip() for message_id in self.source_message_ids)
        if any(not message_id for message_id in message_ids):
            raise ValueError("source_message_ids cannot contain empty values")
        if not message_ids:
            raise ValueError("at least one source message ID is required")

        if self.confidence is MemoryConfidence.INFERRED and len(set(message_ids)) < 2:
            raise ValueError("INFERRED candidates require at least two distinct source message IDs")

        if len(set(message_ids)) != len(message_ids):
            raise ValueError("source_message_ids must be distinct")
        object.__setattr__(self, "source_message_ids", message_ids)

    def _validate_project_id(self) -> None:
        project_id = None if self.project_id is None else str(self.project_id).strip()
        if project_id == "":
            raise ValueError("project_id cannot be empty")
        if self.scope is MemoryScope.PROJECT and not project_id:
            raise ValueError("PROJECT-scoped candidates require project_id")
        if self.scope is not MemoryScope.PROJECT and project_id:
            raise ValueError("Only PROJECT-scoped candidates may have project_id")
        object.__setattr__(self, "project_id", project_id)


@dataclass(frozen=True, slots=True)
class Resolution:
    """The resolver's decision about a single candidate (or existing memory).

    ``kind`` selects what the DurableMemoryManager executes:

    - CREATE     → persist ``candidate`` as a new memory.
    - SUPERSEDE  → replace ``existing_memory_id`` with ``candidate``.
    - INVALIDATE → mark ``existing_memory_id`` invalidated (no candidate).
    - REJECT     → do nothing with ``candidate``.

    ``reason`` is the human-readable justification (mandatory for REJECT,
    optional otherwise).
    """

    kind: ResolutionKind
    candidate: MemoryCandidate | None = None
    existing_memory_id: str | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ResolutionKind):
            raise TypeError(f"Invalid resolution kind: {self.kind!r}")
        if self.kind is ResolutionKind.INVALIDATE and self.candidate is not None:
            raise ValueError("INVALIDATE resolutions must not carry a candidate")
        if (
            self.kind in (ResolutionKind.SUPERSEDE, ResolutionKind.INVALIDATE)
            and not self.existing_memory_id
        ):
            raise ValueError(f"{self.kind.value.upper()} resolutions require existing_memory_id")
        if self.kind in (ResolutionKind.CREATE, ResolutionKind.REJECT) and self.candidate is None:
            raise ValueError(f"{self.kind.value.upper()} resolutions require a candidate")


def candidate_to_memory(candidate: MemoryCandidate, *, now: datetime | None = None) -> Memory:
    """Map a validated candidate into a durable ``Memory``.

    Identity and audit timestamps are assigned here, at execution time — never
    earlier. The candidate itself remains pre-identity.
    """
    timestamp = now if now is not None else _utc_now()
    return Memory(
        type=candidate.type,
        scope=candidate.scope,
        content=candidate.content,
        confidence=candidate.confidence,
        provenance=MemoryProvenance(
            source_conversation_id=candidate.source_conversation_id,
            source_message_ids=candidate.source_message_ids,
        ),
        created_at=timestamp,
        updated_at=timestamp,
        project_id=candidate.project_id,
        status=MemoryStatus.ACTIVE,
    )


__all__ = [
    "MemoryCandidate",
    "Resolution",
    "ResolutionKind",
    "candidate_to_memory",
]
