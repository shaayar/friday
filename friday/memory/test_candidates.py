"""Tests for MemoryCandidate and Resolution domain objects."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest

from friday.memory.candidates import (
    MemoryCandidate,
    Resolution,
    ResolutionKind,
    candidate_to_memory,
)
from friday.memory.models import (
    Memory,
    MemoryConfidence,
    MemoryScope,
    MemoryStatus,
    MemoryType,
)


class TestMemoryCandidateValidation:
    def test_valid_user_candidate(self) -> None:
        candidate = MemoryCandidate(
            type=MemoryType.USER_FACT,
            scope=MemoryScope.USER,
            content="User uses Ubuntu.",
            confidence=MemoryConfidence.EXPLICIT,
            source_conversation_id="conv-1",
            source_message_ids=("msg-1",),
        )
        assert candidate.type is MemoryType.USER_FACT
        assert candidate.scope is MemoryScope.USER
        assert candidate.project_id is None

    def test_valid_project_candidate(self) -> None:
        candidate = MemoryCandidate(
            type=MemoryType.PROJECT_FACT,
            scope=MemoryScope.PROJECT,
            content="The project uses Next.js.",
            confidence=MemoryConfidence.EXPLICIT,
            source_conversation_id="conv-1",
            source_message_ids=("msg-1",),
            project_id="proj-1",
        )
        assert candidate.project_id == "proj-1"

    def test_type_scope_mismatch_rejected(self) -> None:
        with pytest.raises(ValueError, match="must use scope"):
            MemoryCandidate(
                type=MemoryType.PROJECT_FACT,
                scope=MemoryScope.USER,
                content="Wrong scope",
                confidence=MemoryConfidence.EXPLICIT,
                source_conversation_id="conv-1",
                source_message_ids=("msg-1",),
            )

    def test_project_scope_requires_project_id(self) -> None:
        with pytest.raises(ValueError, match="require project_id"):
            MemoryCandidate(
                type=MemoryType.PROJECT_FACT,
                scope=MemoryScope.PROJECT,
                content="Project fact",
                confidence=MemoryConfidence.EXPLICIT,
                source_conversation_id="conv-1",
                source_message_ids=("msg-1",),
            )

    def test_non_project_rejects_project_id(self) -> None:
        with pytest.raises(ValueError, match="Only PROJECT-scoped"):
            MemoryCandidate(
                type=MemoryType.USER_FACT,
                scope=MemoryScope.USER,
                content="User fact",
                confidence=MemoryConfidence.EXPLICIT,
                source_conversation_id="conv-1",
                source_message_ids=("msg-1",),
                project_id="proj-1",
            )

    def test_empty_content_rejected(self) -> None:
        with pytest.raises(ValueError, match="content cannot be empty"):
            MemoryCandidate(
                type=MemoryType.USER_FACT,
                scope=MemoryScope.USER,
                content="   ",
                confidence=MemoryConfidence.EXPLICIT,
                source_conversation_id="conv-1",
                source_message_ids=("msg-1",),
            )

    def test_missing_conversation_rejected(self) -> None:
        with pytest.raises(ValueError, match="source_conversation_id"):
            MemoryCandidate(
                type=MemoryType.USER_FACT,
                scope=MemoryScope.USER,
                content="Fact",
                confidence=MemoryConfidence.EXPLICIT,
                source_conversation_id="",
                source_message_ids=("msg-1",),
            )

    def test_missing_message_ids_rejected(self) -> None:
        with pytest.raises(ValueError, match="at least one source message"):
            MemoryCandidate(
                type=MemoryType.USER_FACT,
                scope=MemoryScope.USER,
                content="Fact",
                confidence=MemoryConfidence.EXPLICIT,
                source_conversation_id="conv-1",
                source_message_ids=(),
            )

    def test_inferred_requires_two_messages(self) -> None:
        with pytest.raises(ValueError, match="two distinct"):
            MemoryCandidate(
                type=MemoryType.USER_FACT,
                scope=MemoryScope.USER,
                content="Repeated behavior",
                confidence=MemoryConfidence.INFERRED,
                source_conversation_id="conv-1",
                source_message_ids=("msg-1",),
            )

    def test_inferred_accepts_two_distinct_messages(self) -> None:
        candidate = MemoryCandidate(
            type=MemoryType.USER_FACT,
            scope=MemoryScope.USER,
            content="Repeated behavior",
            confidence=MemoryConfidence.INFERRED,
            source_conversation_id="conv-1",
            source_message_ids=("msg-1", "msg-2"),
        )
        assert candidate.source_message_ids == ("msg-1", "msg-2")

    def test_inferred_rejects_duplicate_message_ids(self) -> None:
        with pytest.raises(ValueError, match="two distinct"):
            MemoryCandidate(
                type=MemoryType.USER_FACT,
                scope=MemoryScope.USER,
                content="Repeated behavior",
                confidence=MemoryConfidence.INFERRED,
                source_conversation_id="conv-1",
                source_message_ids=("msg-1", "msg-1"),
            )

    def test_invalid_confidence_rejected(self) -> None:
        with pytest.raises(TypeError, match="Invalid confidence"):
            MemoryCandidate(
                type=MemoryType.USER_FACT,
                scope=MemoryScope.USER,
                content="Fact",
                confidence="very-sure",  # type: ignore[arg-type]
                source_conversation_id="conv-1",
                source_message_ids=("msg-1",),
            )

    def test_candidate_is_immutable(self) -> None:
        candidate = MemoryCandidate(
            type=MemoryType.USER_FACT,
            scope=MemoryScope.USER,
            content="Fact",
            confidence=MemoryConfidence.EXPLICIT,
            source_conversation_id="conv-1",
            source_message_ids=("msg-1",),
        )
        with pytest.raises(FrozenInstanceError):
            candidate.content = "changed"  # type: ignore[misc]


class TestResolution:
    def test_resolution_create(self) -> None:
        candidate = MemoryCandidate(
            type=MemoryType.USER_FACT,
            scope=MemoryScope.USER,
            content="Fact",
            confidence=MemoryConfidence.EXPLICIT,
            source_conversation_id="conv-1",
            source_message_ids=("msg-1",),
        )
        resolution = Resolution(kind=ResolutionKind.CREATE, candidate=candidate)
        assert resolution.kind is ResolutionKind.CREATE
        assert resolution.existing_memory_id is None

    def test_resolution_supersede(self) -> None:
        candidate = MemoryCandidate(
            type=MemoryType.USER_FACT,
            scope=MemoryScope.USER,
            content="Fact",
            confidence=MemoryConfidence.EXPLICIT,
            source_conversation_id="conv-1",
            source_message_ids=("msg-1",),
        )
        resolution = Resolution(
            kind=ResolutionKind.SUPERSEDE,
            candidate=candidate,
            existing_memory_id="old-id",
            reason="clear update",
        )
        assert resolution.existing_memory_id == "old-id"
        assert resolution.reason == "clear update"

    def test_resolution_invalidate(self) -> None:
        resolution = Resolution(
            kind=ResolutionKind.INVALIDATE,
            existing_memory_id="old-id",
            reason="obsolete",
        )
        assert resolution.kind is ResolutionKind.INVALIDATE
        assert resolution.candidate is None
        assert resolution.existing_memory_id == "old-id"

    def test_invalidate_with_candidate_rejected(self) -> None:
        candidate = MemoryCandidate(
            type=MemoryType.USER_FACT,
            scope=MemoryScope.USER,
            content="Fact",
            confidence=MemoryConfidence.EXPLICIT,
            source_conversation_id="conv-1",
            source_message_ids=("msg-1",),
        )
        with pytest.raises(ValueError, match="must not carry a candidate"):
            Resolution(
                kind=ResolutionKind.INVALIDATE,
                candidate=candidate,
                existing_memory_id="old-id",
            )

    def test_invalidate_requires_existing_memory_id(self) -> None:
        with pytest.raises(ValueError, match="require existing_memory_id"):
            Resolution(kind=ResolutionKind.INVALIDATE)

    def test_create_requires_candidate(self) -> None:
        with pytest.raises(ValueError, match="require a candidate"):
            Resolution(kind=ResolutionKind.CREATE)


class TestCandidateToMemory:
    def test_maps_candidate_to_memory(self) -> None:
        candidate = MemoryCandidate(
            type=MemoryType.PROJECT_FACT,
            scope=MemoryScope.PROJECT,
            content="The project uses Next.js.",
            confidence=MemoryConfidence.EXPLICIT,
            source_conversation_id="conv-1",
            source_message_ids=("msg-1", "msg-2"),
            project_id="proj-1",
        )
        memory = candidate_to_memory(candidate)

        assert isinstance(memory, Memory)
        assert memory.type is candidate.type
        assert memory.scope is candidate.scope
        assert memory.content == candidate.content
        assert memory.confidence is candidate.confidence
        assert memory.project_id == "proj-1"
        assert memory.status is MemoryStatus.ACTIVE
        assert memory.id  # identity assigned at persistence time
        assert memory.provenance.source_conversation_id == "conv-1"
        assert memory.provenance.source_message_ids == ("msg-1", "msg-2")
        assert memory.created_at is not None
        assert memory.updated_at == memory.created_at
        assert memory.valid_from == memory.created_at

    def test_maps_tentative_confirmation(self) -> None:
        candidate = MemoryCandidate(
            type=MemoryType.USER_FACT,
            scope=MemoryScope.USER,
            content="User maybe prefers dark mode.",
            confidence=MemoryConfidence.TENTATIVE,
            source_conversation_id="conv-1",
            source_message_ids=("msg-1",),
        )
        memory = candidate_to_memory(candidate)
        assert memory.confidence is MemoryConfidence.TENTATIVE
        assert memory.status is MemoryStatus.ACTIVE

    def test_explicit_created_at(self) -> None:
        candidate = MemoryCandidate(
            type=MemoryType.USER_FACT,
            scope=MemoryScope.USER,
            content="Fact",
            confidence=MemoryConfidence.EXPLICIT,
            source_conversation_id="conv-1",
            source_message_ids=("msg-1",),
        )
        now = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)
        memory = candidate_to_memory(candidate, now=now)
        assert memory.created_at == now
        assert memory.updated_at == now
        assert memory.valid_from == now


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
