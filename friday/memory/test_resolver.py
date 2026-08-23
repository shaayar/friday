"""Tests for MemoryResolver: deduplication, classification, confidence demotion."""

from __future__ import annotations

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
    MemoryProvenance,
    MemoryScope,
    MemoryStatus,
    MemoryType,
)
from friday.memory.resolver import MemoryResolver

NOW = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)


def make_candidate(
    content: str,
    *,
    type: MemoryType = MemoryType.USER_FACT,
    scope: MemoryScope = MemoryScope.USER,
    confidence: MemoryConfidence = MemoryConfidence.EXPLICIT,
    source_message_ids: tuple[str, ...] = ("msg-1",),
    project_id: str | None = None,
) -> MemoryCandidate:
    return MemoryCandidate(
        type=type,
        scope=scope,
        content=content,
        confidence=confidence,
        source_conversation_id="conv-1",
        source_message_ids=source_message_ids,
        project_id=project_id,
    )


def make_memory(
    content: str,
    memory_id: str,
    *,
    type: MemoryType = MemoryType.USER_FACT,
    scope: MemoryScope = MemoryScope.USER,
    project_id: str | None = None,
) -> Memory:
    return Memory(
        id=memory_id,
        type=type,
        scope=scope,
        content=content,
        confidence=MemoryConfidence.EXPLICIT,
        provenance=MemoryProvenance(
            source_conversation_id="conv-0",
            source_message_ids=("old-1",),
        ),
        created_at=NOW,
        updated_at=NOW,
        status=MemoryStatus.ACTIVE,
        project_id=project_id,
    )


def create_resolution(
    candidate: MemoryCandidate, existing: Memory | None = None
) -> Resolution:
    """Helper: classify a single candidate against a single existing memory."""
    resolver = MemoryResolver()
    existing_memories = [existing] if existing is not None else []
    return resolver.resolve([candidate], existing_memories=existing_memories)[0]


class TestDeduplication:
    def test_exact_duplicate_rejected(self) -> None:
        candidate = make_candidate("User prefers dark mode in the IDE.")
        existing = make_memory("User prefers dark mode in the IDE.", "m-1")
        resolution = create_resolution(candidate, existing)
        assert resolution.kind is ResolutionKind.REJECT
        assert "duplicate" in resolution.reason.lower()

    def test_containment_duplicate_rejected(self) -> None:
        candidate = make_candidate("User prefers dark mode")
        existing = make_memory("User prefers dark mode in the IDE.", "m-1")
        resolution = create_resolution(candidate, existing)
        assert resolution.kind is ResolutionKind.REJECT

    def test_fuzzy_duplicate_rejected(self) -> None:
        # Ratio of these two strings is >= 0.85 (threshold).
        candidate = make_candidate("User prefers dark mode in the ide")
        existing = make_memory("User prefers dark mode in ide", "m-1")
        resolution = create_resolution(candidate, existing)
        assert resolution.kind is ResolutionKind.REJECT

    def test_below_threshold_not_rejected(self) -> None:
        candidate = make_candidate("User prefers dark mode in the ide")
        existing = make_memory("User is allergic to peanuts", "m-1")
        resolution = create_resolution(candidate, existing)
        assert resolution.kind is not ResolutionKind.REJECT

    def test_cross_project_same_content_never_deduped(self) -> None:
        candidate = make_candidate(
            "The project uses dark mode.",
            type=MemoryType.PROJECT_FACT,
            scope=MemoryScope.PROJECT,
            project_id="proj-1",
        )
        # Unrelated memory in the candidate's own project.
        proj1_memory = make_memory(
            "The team meets on Fridays.",
            "m-1",
            type=MemoryType.PROJECT_FACT,
            scope=MemoryScope.PROJECT,
            project_id="proj-1",
        )
        # Identical content, but belongs to a different project.
        other_project = make_memory(
            "The project uses dark mode.",
            "m-2",
            type=MemoryType.PROJECT_FACT,
            scope=MemoryScope.PROJECT,
            project_id="proj-2",
        )
        resolutions = MemoryResolver().resolve(
            [candidate], existing_memories=[proj1_memory, other_project]
        )
        assert resolutions[0].kind is ResolutionKind.CREATE

    def test_same_project_duplicate_rejected(self) -> None:
        candidate = make_candidate(
            "The project uses dark mode.",
            type=MemoryType.PROJECT_FACT,
            scope=MemoryScope.PROJECT,
            project_id="proj-1",
        )
        existing = make_memory(
            "The project uses dark mode.",
            "m-1",
            type=MemoryType.PROJECT_FACT,
            scope=MemoryScope.PROJECT,
            project_id="proj-1",
        )
        resolution = create_resolution(candidate, existing)
        assert resolution.kind is ResolutionKind.REJECT

    def test_duplicate_within_batch_rejected(self) -> None:
        first = make_candidate("User uses Neovim.")
        second = make_candidate("User uses Neovim.")
        resolutions = MemoryResolver().resolve([first, second], existing_memories=[])
        assert [r.kind for r in resolutions] == [
            ResolutionKind.CREATE,
            ResolutionKind.REJECT,
        ]


class TestClassification:
    def test_no_match_creates(self) -> None:
        candidate = make_candidate("User enjoys coffee.")
        resolution = create_resolution(candidate)
        assert resolution.kind is ResolutionKind.CREATE
        assert resolution.candidate.content == "User enjoys coffee."

    def test_transition_marker_supersedes_relevant(self) -> None:
        candidate = make_candidate("User switched from Vim to Neovim as editor.")
        existing = make_memory("User uses Vim as editor.", "m-1")
        resolution = create_resolution(candidate, existing)
        assert resolution.kind is ResolutionKind.SUPERSEDE
        assert resolution.existing_memory_id == "m-1"

    def test_transition_marker_without_match_creates(self) -> None:
        candidate = make_candidate("User switched from Vim to Neovim.")
        existing = make_memory("User is allergic to peanuts.", "m-1")
        resolution = create_resolution(candidate, existing)
        assert resolution.kind is ResolutionKind.CREATE

    def test_negation_with_existing_preserves_existing(self) -> None:
        candidate = make_candidate("User does not use Vim as editor anymore.")
        existing = make_memory("User uses Vim as editor.", "m-1")
        resolution = create_resolution(candidate, existing)
        # Conservative: never invalidate/supersede on a bare negation.
        assert resolution.kind is ResolutionKind.REJECT
        assert "preserving existing" in resolution.reason.lower()

    def test_ambiguous_shared_terms_preserves_existing(self) -> None:
        candidate = make_candidate("User uses Vim and Neovim as code editors.")
        existing = make_memory("User uses Vim as code editor.", "m-1")
        resolution = create_resolution(candidate, existing)
        assert resolution.kind is ResolutionKind.REJECT
        assert "preserving existing" in resolution.reason.lower()

    def test_unrelated_existing_memory_creates(self) -> None:
        candidate = make_candidate("User enjoys hiking.")
        existing = make_memory("User uses Vim as editor.", "m-1")
        resolution = create_resolution(candidate, existing)
        assert resolution.kind is ResolutionKind.CREATE


class TestConfidenceDemotion:
    def test_hedged_explicit_demoted_to_tentative(self) -> None:
        candidate = make_candidate(
            "User probably prefers dark mode.",
            confidence=MemoryConfidence.EXPLICIT,
        )
        resolution = create_resolution(candidate)
        assert resolution.kind is ResolutionKind.CREATE
        assert resolution.candidate.confidence is MemoryConfidence.TENTATIVE

    def test_confidence_never_increases(self) -> None:
        candidate = make_candidate(
            "User prefers dark mode.",
            confidence=MemoryConfidence.TENTATIVE,
        )
        resolution = create_resolution(candidate)
        assert resolution.candidate.confidence is MemoryConfidence.TENTATIVE

    def test_explicit_unhedged_unchanged(self) -> None:
        candidate = make_candidate(
            "User prefers dark mode.",
            confidence=MemoryConfidence.EXPLICIT,
        )
        resolution = create_resolution(candidate)
        assert resolution.candidate.confidence is MemoryConfidence.EXPLICIT

    def test_demoted_candidate_maps_to_tentative_memory(self) -> None:
        candidate = make_candidate(
            "User maybe likes Rust.", confidence=MemoryConfidence.EXPLICIT
        )
        resolution = create_resolution(candidate)
        memory = candidate_to_memory(resolution.candidate)
        assert memory.confidence is MemoryConfidence.TENTATIVE


class FakeLLM:
    """Configurable fake LLM backend for advisory resolution tests."""

    def __init__(self, response: str) -> None:
        self._response = response

    def complete(self, system: str, user: str) -> str:
        return self._response


class TestAdvisoryResolution:
    def test_llm_says_supersede(self) -> None:
        candidate = make_candidate("User does not use Vim as editor anymore.")
        existing = make_memory("User uses Vim as editor.", "m-1")
        resolver = MemoryResolver(llm=FakeLLM('{"action": "supersede"}'))
        resolution = resolver.resolve([candidate], existing_memories=[existing])[0]
        assert resolution.kind is ResolutionKind.SUPERSEDE
        assert resolution.existing_memory_id == "m-1"

    def test_llm_says_reject(self) -> None:
        candidate = make_candidate("User does not use Vim as editor anymore.")
        existing = make_memory("User uses Vim as editor.", "m-1")
        resolver = MemoryResolver(llm=FakeLLM('{"action": "reject"}'))
        resolution = resolver.resolve([candidate], existing_memories=[existing])[0]
        assert resolution.kind is ResolutionKind.REJECT

    def test_malformed_llm_response_falls_back_to_reject(self) -> None:
        candidate = make_candidate("User does not use Vim as editor anymore.")
        existing = make_memory("User uses Vim as editor.", "m-1")
        resolver = MemoryResolver(llm=FakeLLM("not json at all"))
        resolution = resolver.resolve([candidate], existing_memories=[existing])[0]
        assert resolution.kind is ResolutionKind.REJECT

    def test_llm_says_create_when_llm_available(self) -> None:
        candidate = make_candidate("User does not use Vim anymore.")
        existing = make_memory("User uses Vim as editor.", "m-1")
        resolver = MemoryResolver(llm=FakeLLM('{"action": "create"}'))
        resolution = resolver.resolve([candidate], existing_memories=[existing])[0]
        assert resolution.kind is ResolutionKind.CREATE

    def test_no_llm_without_ambiguity_never_queries(self) -> None:
        candidate = make_candidate("User enjoys hiking.")
        existing = make_memory("User uses Vim as editor.", "m-1")
        resolution = create_resolution(candidate, existing)
        assert resolution.kind is ResolutionKind.CREATE


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
