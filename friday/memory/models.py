"""
Memory domain models.

These types define the durable-memory vocabulary used by future extraction,
resolution, and storage layers. They are intentionally independent from any
database, provider, or transport implementation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    return uuid4().hex


def _require_aware_timestamp(name: str, value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value


class MemoryScope(StrEnum):
    USER = "user"
    PROJECT = "project"
    CONVERSATION = "conversation"


class MemoryType(StrEnum):
    USER_FACT = "user_fact"
    PROJECT_FACT = "project_fact"
    PROJECT_CONSTRAINT = "project_constraint"
    PROJECT_DECISION = "project_decision"
    CONVERSATION_SUMMARY = "conversation_summary"

    @property
    def default_scope(self) -> MemoryScope:
        return _MEMORY_TYPE_SCOPES[self]


class MemoryStatus(StrEnum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    INVALIDATED = "invalidated"


class MemoryConfidence(StrEnum):
    EXPLICIT = "explicit"
    INFERRED = "inferred"
    TENTATIVE = "tentative"


@dataclass(frozen=True, slots=True)
class MemoryProvenance:
    """Provenance metadata for a memory item."""

    source_conversation_id: str | int | None = None
    source_message_ids: tuple[str | int, ...] = ()

    def __post_init__(self) -> None:
        if self.source_conversation_id is not None:
            conversation_id = str(self.source_conversation_id).strip()
            if not conversation_id:
                raise ValueError("source_conversation_id cannot be empty")
            object.__setattr__(self, "source_conversation_id", conversation_id)

        normalized_message_ids = tuple(
            str(message_id).strip() for message_id in self.source_message_ids
        )
        if any(not message_id for message_id in normalized_message_ids):
            raise ValueError("source_message_ids cannot contain empty values")
        object.__setattr__(self, "source_message_ids", normalized_message_ids)

        if self.source_message_ids and self.source_conversation_id is None:
            raise ValueError("source_message_ids require source_conversation_id")


_MEMORY_TYPE_SCOPES: dict[MemoryType, MemoryScope] = {
    MemoryType.USER_FACT: MemoryScope.USER,
    MemoryType.PROJECT_FACT: MemoryScope.PROJECT,
    MemoryType.PROJECT_CONSTRAINT: MemoryScope.PROJECT,
    MemoryType.PROJECT_DECISION: MemoryScope.PROJECT,
    MemoryType.CONVERSATION_SUMMARY: MemoryScope.CONVERSATION,
}


@dataclass(frozen=True, slots=True)
class Memory:
    """Durable memory record."""

    type: MemoryType
    scope: MemoryScope
    content: str
    id: str = field(default_factory=_new_id)
    status: MemoryStatus = MemoryStatus.ACTIVE
    confidence: MemoryConfidence = MemoryConfidence.EXPLICIT
    provenance: MemoryProvenance = field(default_factory=MemoryProvenance)
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    supersedes: str | None = None
    superseded_by: str | None = None
    project_id: str | None = None

    def __post_init__(self) -> None:
        self._validate_id()
        self._validate_content()
        self._validate_type_and_scope()
        self._validate_status_and_confidence()
        self._validate_provenance()
        self._validate_timestamps()
        self._validate_supersession()
        self._validate_project_id()

    def _validate_id(self) -> None:
        memory_id = str(self.id).strip()
        if not memory_id:
            raise ValueError("id cannot be empty")
        object.__setattr__(self, "id", memory_id)

    def _validate_content(self) -> None:
        if not isinstance(self.content, str) or not self.content.strip():
            raise ValueError("content cannot be empty")
        object.__setattr__(self, "content", self.content)

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

    def _validate_status_and_confidence(self) -> None:
        if not isinstance(self.status, MemoryStatus):
            raise TypeError(f"Invalid memory status: {self.status!r}")
        if not isinstance(self.confidence, MemoryConfidence):
            raise TypeError(f"Invalid memory confidence: {self.confidence!r}")

    def _validate_provenance(self) -> None:
        if not isinstance(self.provenance, MemoryProvenance):
            raise TypeError("provenance must be a MemoryProvenance instance")

    def _validate_timestamps(self) -> None:
        created_at = _require_aware_timestamp("created_at", self.created_at)
        object.__setattr__(self, "created_at", created_at)

        updated_at = (
            created_at
            if self.updated_at is None
            else _require_aware_timestamp("updated_at", self.updated_at)
        )
        if updated_at < created_at:
            raise ValueError("updated_at cannot be earlier than created_at")
        object.__setattr__(self, "updated_at", updated_at)

        valid_from = (
            created_at
            if self.valid_from is None
            else _require_aware_timestamp("valid_from", self.valid_from)
        )
        valid_until = (
            None
            if self.valid_until is None
            else _require_aware_timestamp("valid_until", self.valid_until)
        )
        if valid_until is not None and valid_until < valid_from:
            raise ValueError("valid_until cannot be earlier than valid_from")
        object.__setattr__(self, "valid_from", valid_from)
        object.__setattr__(self, "valid_until", valid_until)

    def _validate_supersession(self) -> None:
        supersedes = None if self.supersedes is None else str(self.supersedes).strip()
        superseded_by = None if self.superseded_by is None else str(self.superseded_by).strip()
        if supersedes == "":
            raise ValueError("supersedes cannot be empty")
        if superseded_by == "":
            raise ValueError("superseded_by cannot be empty")
        if supersedes == self.id:
            raise ValueError("supersedes cannot reference the same memory")
        if superseded_by == self.id:
            raise ValueError("superseded_by cannot reference the same memory")
        object.__setattr__(self, "supersedes", supersedes)
        object.__setattr__(self, "superseded_by", superseded_by)

    def _validate_project_id(self) -> None:
        project_id = None if self.project_id is None else str(self.project_id).strip()
        if project_id == "":
            raise ValueError("project_id cannot be empty")
        if self.scope is MemoryScope.PROJECT and not project_id:
            raise ValueError("PROJECT-scoped memories require project_id")
        if self.scope is not MemoryScope.PROJECT and project_id:
            raise ValueError("Only PROJECT-scoped memories may have project_id")
        object.__setattr__(self, "project_id", project_id)


__all__ = [
    "Memory",
    "MemoryConfidence",
    "MemoryProvenance",
    "MemoryScope",
    "MemoryStatus",
    "MemoryType",
]
