"""
Tests for memory domain models.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta

import pytest

from friday.memory.models import (
    Memory,
    MemoryConfidence,
    MemoryProvenance,
    MemoryScope,
    MemoryStatus,
    MemoryType,
)


@pytest.mark.parametrize(
    ("memory_type", "scope"),
    [
        (MemoryType.USER_FACT, MemoryScope.USER),
        (MemoryType.PROJECT_FACT, MemoryScope.PROJECT),
        (MemoryType.PROJECT_CONSTRAINT, MemoryScope.PROJECT),
        (MemoryType.PROJECT_DECISION, MemoryScope.PROJECT),
        (MemoryType.CONVERSATION_SUMMARY, MemoryScope.CONVERSATION),
    ],
)
def test_valid_memory_types(memory_type: MemoryType, scope: MemoryScope) -> None:
    kwargs = {"type": memory_type, "scope": scope, "content": "A durable memory."}
    if scope is MemoryScope.PROJECT:
        kwargs["project_id"] = "test-project"
    memory = Memory(**kwargs)

    assert memory.type is memory_type
    assert memory.scope is scope
    assert memory.status is MemoryStatus.ACTIVE
    assert memory.confidence is MemoryConfidence.EXPLICIT
    assert memory.valid_from == memory.created_at
    assert memory.updated_at == memory.created_at


def test_invalid_type_scope_combination() -> None:
    with pytest.raises(ValueError, match="must use scope"):
        Memory(type=MemoryType.PROJECT_FACT, scope=MemoryScope.USER, content="Invalid scope")


@pytest.mark.parametrize("content", ["", "   "])
def test_invalid_empty_content(content: str) -> None:
    with pytest.raises(ValueError, match="content cannot be empty"):
        Memory(type=MemoryType.USER_FACT, scope=MemoryScope.USER, content=content)


@pytest.mark.parametrize(
    "status",
    [MemoryStatus.ACTIVE, MemoryStatus.SUPERSEDED, MemoryStatus.INVALIDATED],
)
def test_memory_status_values(status: MemoryStatus) -> None:
    memory = Memory(type=MemoryType.USER_FACT, scope=MemoryScope.USER, content="Status test", status=status)

    assert memory.status is status


@pytest.mark.parametrize(
    "confidence",
    [MemoryConfidence.EXPLICIT, MemoryConfidence.INFERRED, MemoryConfidence.TENTATIVE],
)
def test_confidence_representation(confidence: MemoryConfidence) -> None:
    memory = Memory(
        type=MemoryType.PROJECT_FACT,
        scope=MemoryScope.PROJECT,
        content="Confidence test",
        confidence=confidence,
        project_id="test-project",
    )

    assert memory.confidence is confidence


def test_provenance_representation() -> None:
    provenance = MemoryProvenance(source_conversation_id=42, source_message_ids=(7, 8))
    memory = Memory(
        type=MemoryType.CONVERSATION_SUMMARY,
        scope=MemoryScope.CONVERSATION,
        content="Provenance test",
        provenance=provenance,
    )

    assert memory.provenance.source_conversation_id == "42"
    assert memory.provenance.source_message_ids == ("7", "8")


def test_provenance_requires_conversation_for_message_ids() -> None:
    with pytest.raises(ValueError, match="require source_conversation_id"):
        MemoryProvenance(source_message_ids=(1,))


def test_supersession_representation() -> None:
    old_memory = Memory(
        type=MemoryType.PROJECT_DECISION,
        scope=MemoryScope.PROJECT,
        content="Use Sarvam TTS.",
        project_id="test-project",
    )
    new_memory = Memory(
        type=MemoryType.PROJECT_DECISION,
        scope=MemoryScope.PROJECT,
        content="Use Sarvam TTS with WAV output.",
        supersedes=old_memory.id,
        project_id="test-project",
    )
    superseded_old = replace(old_memory, superseded_by=new_memory.id, status=MemoryStatus.SUPERSEDED)

    assert new_memory.supersedes == old_memory.id
    assert superseded_old.superseded_by == new_memory.id
    assert superseded_old.status is MemoryStatus.SUPERSEDED


def test_timestamp_behavior() -> None:
    created_at = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)
    valid_until = created_at + timedelta(days=7)

    memory = Memory(
        type=MemoryType.USER_FACT,
        scope=MemoryScope.USER,
        content="Time test",
        created_at=created_at,
        valid_until=valid_until,
    )

    assert memory.created_at == created_at
    assert memory.updated_at == created_at
    assert memory.valid_from == created_at
    assert memory.valid_until == valid_until


def test_stable_identity_behavior() -> None:
    first = Memory(type=MemoryType.USER_FACT, scope=MemoryScope.USER, content="First")
    second = Memory(type=MemoryType.USER_FACT, scope=MemoryScope.USER, content="Second")
    explicit = Memory(type=MemoryType.USER_FACT, scope=MemoryScope.USER, content="Explicit", id="memory-123")

    assert first.id
    assert second.id
    assert first.id != second.id
    assert explicit.id == "memory-123"


def test_memory_is_immutable() -> None:
    memory = Memory(type=MemoryType.USER_FACT, scope=MemoryScope.USER, content="Immutable")

    with pytest.raises(FrozenInstanceError):
        memory.content = "Changed"  # type: ignore[misc]


def test_project_scope_requires_project_id() -> None:
    with pytest.raises(ValueError, match="PROJECT-scoped memories require project_id"):
        Memory(type=MemoryType.PROJECT_FACT, scope=MemoryScope.PROJECT, content="Project fact")


def test_non_project_scope_rejects_project_id() -> None:
    with pytest.raises(ValueError, match="Only PROJECT-scoped memories may have project_id"):
        Memory(
            type=MemoryType.USER_FACT,
            scope=MemoryScope.USER,
            content="User fact",
            project_id="project-123",
        )


def test_empty_project_id_rejected() -> None:
    with pytest.raises(ValueError, match="project_id cannot be empty"):
        Memory(
            type=MemoryType.PROJECT_FACT,
            scope=MemoryScope.PROJECT,
            content="Project fact",
            project_id="   ",
        )


def test_valid_project_memory_with_project_id() -> None:
    memory = Memory(
        type=MemoryType.PROJECT_FACT,
        scope=MemoryScope.PROJECT,
        content="Project fact",
        project_id="project-123",
    )
    assert memory.project_id == "project-123"
