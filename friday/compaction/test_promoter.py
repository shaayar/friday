"""Tests for Phase 4 M6.3 ConversationMemoryPromoter orchestration (ADR-025)."""

from __future__ import annotations

import inspect
from datetime import UTC, datetime
from pathlib import Path

import pytest

from friday.compaction.exceptions import (
    PromotionAlreadyExistsError,
    PromotionNotFoundError,
)
from friday.compaction.models import CompactionItem, ConversationCompaction
from friday.compaction.promoter import ConversationMemoryPromoter, PromotionOutcome
from friday.compaction.promotion import (
    CompactionItemCategory,
    CompactionPromotion,
    PromotionResolutionKind,
    PromotionStatus,
)
from friday.compaction.promotion_store import SQLitePromotionStore
from friday.compaction.sqlite_store import SQLiteCompactionStore
from friday.memory.candidates import (
    MemoryCandidate,
    Resolution,
    ResolutionKind,
    candidate_to_memory,
)
from friday.memory.durable_manager import DurableMemoryManager
from friday.memory.models import (
    Memory,
    MemoryConfidence,
    MemoryProvenance,
    MemoryScope,
    MemoryStatus,
    MemoryType,
)
from friday.memory.resolver import MemoryResolver
from friday.memory.sqlite_memory_store import SQLiteMemoryStore
from friday.memory.sqlite_store import SQLiteConversationStore

FIXED_NOW = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)


# ----------------------------------------------------------------------
# Fakes
# ----------------------------------------------------------------------


class FakeLedgerStore:
    """In-memory PromotionLedgerStore satisfying the promoter protocol."""

    def __init__(self) -> None:
        self._entries: dict[str, CompactionPromotion] = {}
        self.saved: list[CompactionPromotion] = []
        self.replaced: list[CompactionPromotion] = []

    def get(self, item_id: str) -> CompactionPromotion | None:
        return self._entries.get(item_id)

    def save(self, promotion: CompactionPromotion) -> CompactionPromotion:
        if promotion.item_id in self._entries:
            raise PromotionAlreadyExistsError(
                f"Promotion with item_id {promotion.item_id} already exists"
            )
        self._entries[promotion.item_id] = promotion
        self.saved.append(promotion)
        return promotion

    def replace(self, promotion: CompactionPromotion) -> CompactionPromotion:
        if promotion.item_id not in self._entries:
            raise PromotionNotFoundError(
                f"Promotion with item_id {promotion.item_id} not found"
            )
        self._entries[promotion.item_id] = promotion
        self.replaced.append(promotion)
        return promotion

    def entry(self, item_id: str) -> CompactionPromotion | None:
        return self._entries.get(item_id)


class FakeMemoryManager:
    """In-memory memory manager: records batches, persists via candidate_to_memory."""

    def __init__(
        self,
        memories: list[Memory] | None = None,
        *,
        fail_apply: str | None = None,
        fail_get_active: str | None = None,
    ) -> None:
        self.memories = list(memories or [])
        self.batches: list[list[Resolution]] = []
        self.applied: list[Resolution] = []
        self.fail_apply = fail_apply
        self.fail_get_active = fail_get_active

    def get_active(
        self,
        *,
        scope: MemoryScope | None = None,
        project_id: str | None = None,
        valid_at=None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Memory]:
        if self.fail_get_active:
            raise RuntimeError(self.fail_get_active)
        result = [m for m in self.memories if m.status is MemoryStatus.ACTIVE]
        if scope is not None:
            result = [m for m in result if m.scope is scope]
        if project_id is not None:
            result = [m for m in result if m.project_id == project_id]
        return result[offset : offset + limit]

    def apply_batch(self, resolutions: list[Resolution]) -> list[Memory | None]:
        if self.fail_apply:
            raise RuntimeError(self.fail_apply)
        self.batches.append(list(resolutions))
        self.applied.extend(resolutions)
        results: list[Memory | None] = []
        for resolution in resolutions:
            if resolution.kind is ResolutionKind.REJECT or resolution.kind is ResolutionKind.INVALIDATE:
                results.append(None)
            elif resolution.kind in (ResolutionKind.CREATE, ResolutionKind.SUPERSEDE):
                memory = candidate_to_memory(resolution.candidate)
                self.memories.append(memory)
                results.append(memory)
            else:  # pragma: no cover - defensive
                results.append(None)
        return results


class FakeResolver:
    """Scripted resolver: per-index ResolutionKind, default CREATE."""

    def __init__(
        self,
        kinds: list[ResolutionKind] | None = None,
        *,
        fail: str | None = None,
    ) -> None:
        self.kinds = list(kinds or [])
        self.fail = fail
        self.calls: list[tuple[list[MemoryCandidate], list[Memory]]] = []

    def resolve(
        self,
        candidates: list[MemoryCandidate],
        *,
        existing_memories: list[Memory],
    ) -> list[Resolution]:
        self.calls.append((list(candidates), list(existing_memories)))
        if self.fail:
            raise RuntimeError(self.fail)
        resolutions: list[Resolution] = []
        for index, candidate in enumerate(candidates):
            kind = self.kinds[index] if index < len(self.kinds) else ResolutionKind.CREATE
            if kind is ResolutionKind.REJECT:
                resolutions.append(
                    Resolution(kind=kind, candidate=candidate, reason="fake_reject")
                )
            elif kind is ResolutionKind.INVALIDATE:
                resolutions.append(
                    Resolution(kind=kind, existing_memory_id="mem-0", reason="fake_invalidate")
                )
            elif kind is ResolutionKind.SUPERSEDE:
                resolutions.append(
                    Resolution(
                        kind=kind,
                        candidate=candidate,
                        existing_memory_id="mem-target",
                        reason="fake_supersede",
                    )
                )
            else:
                resolutions.append(
                    Resolution(kind=kind, candidate=candidate, reason="fake_resolve")
                )
        return resolutions


# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------


def make_item(item_id: str, content: str, source_message_ids: tuple[int, ...]) -> CompactionItem:
    return CompactionItem(item_id=item_id, content=content, source_message_ids=source_message_ids)


def make_compaction(**overrides) -> ConversationCompaction:
    base: dict = {
        "compaction_id": "compaction-1",
        "conversation_id": 42,
        "first_message_id": 1,
        "last_message_id": 10,
        "created_at": FIXED_NOW,
        "summary": "The conversation covered setup and design.",
        "facts": (
            make_item("fact-1", "I use Ubuntu on my desktop.", (1, 2)),
            make_item("fact-2", "FRIDAY uses Python 3.12.", (2, 3)),
        ),
        "decisions": (
            make_item("decision-1", "FRIDAY will persist durable memory in SQLite.", (3, 4)),
        ),
        "changes": (
            make_item("change-1", "Moved message storage to SQLite.", (4, 5)),
        ),
        "open_questions": (
            make_item("question-1", "Should promotion be automatic?", (6,)),
        ),
    }
    base.update(overrides)
    return ConversationCompaction(**base)


@pytest.fixture
def ledger() -> FakeLedgerStore:
    return FakeLedgerStore()


@pytest.fixture
def memories() -> FakeMemoryManager:
    return FakeMemoryManager()


@pytest.fixture
def resolver() -> FakeResolver:
    return FakeResolver()


@pytest.fixture
def promoter(ledger, memories, resolver) -> ConversationMemoryPromoter:
    return ConversationMemoryPromoter(ledger, memories, resolver)


def seeded_promoted(item_id: str, category: CompactionItemCategory) -> CompactionPromotion:
    return CompactionPromotion(
        item_id=item_id,
        compaction_id="compaction-1",
        category=category,
        status=PromotionStatus.PROMOTED,
        resolved_memory_ids=("mem-seeded",),
        resolution_kind=PromotionResolutionKind.CREATE,
        created_at=FIXED_NOW,
    )


def seeded_rejected(item_id: str, category: CompactionItemCategory) -> CompactionPromotion:
    return CompactionPromotion(
        item_id=item_id,
        compaction_id="compaction-1",
        category=category,
        status=PromotionStatus.REJECTED,
        resolution_reason="seeded_rejection",
        created_at=FIXED_NOW,
    )


# ----------------------------------------------------------------------
# 1-6: eligibility and candidate construction
# ----------------------------------------------------------------------


def test_fact_produces_candidate_and_promotes(promoter, resolver, memories) -> None:
    result = promoter.promote(make_compaction(), project_id="proj-1")

    assert result.compaction_id == "compaction-1"
    assert resolver.calls
    candidates = resolver.calls[0][0]
    assert len(candidates) == 3
    user_fact = next(c for c in candidates if c.type is MemoryType.USER_FACT)
    assert user_fact.scope is MemoryScope.USER
    assert user_fact.content == "I use Ubuntu on my desktop."
    outcome = next(r for r in result.items if r.item_id == "fact-1")
    assert outcome.outcome is PromotionOutcome.PROMOTED
    assert outcome.resolution_kind is PromotionResolutionKind.CREATE


def test_decision_becomes_project_decision(promoter, resolver) -> None:
    promoter.promote(make_compaction(), project_id="proj-1")

    candidates = resolver.calls[0][0]
    decision = next(c for c in candidates if c.source_message_ids == ("3", "4"))
    assert decision.type is MemoryType.PROJECT_DECISION
    assert decision.scope is MemoryScope.PROJECT
    assert decision.project_id == "proj-1"


def test_decision_without_project_id_rejected(promoter, resolver) -> None:
    result = promoter.promote(make_compaction())

    decision = next(r for r in result.items if r.item_id == "decision-1")
    assert decision.outcome is PromotionOutcome.REJECTED
    assert decision.reason == "decision_requires_project_id"
    assert all(
        c.source_message_ids != ("3", "4") for c in resolver.calls[0][0]
    )


def test_summary_never_promoted(promoter, resolver, memories) -> None:
    promoter.promote(make_compaction(), project_id="proj-1")

    for _candidates, _existing in resolver.calls:
        for candidate in _candidates:
            assert candidate.type is not MemoryType.CONVERSATION_SUMMARY
    assert all(m.type is not MemoryType.CONVERSATION_SUMMARY for m in memories.memories)


def test_open_questions_skipped(promoter, resolver) -> None:
    result = promoter.promote(make_compaction(), project_id="proj-1")

    question = next(r for r in result.items if r.item_id == "question-1")
    assert question.outcome is PromotionOutcome.SKIPPED
    assert question.reason == "open_questions_not_promotable"
    assert not resolver.calls or all(
        c.source_message_ids != ("6",) for c in resolver.calls[0][0]
    )


def test_changes_skipped(promoter, resolver) -> None:
    result = promoter.promote(make_compaction(), project_id="proj-1")

    change = next(r for r in result.items if r.item_id == "change-1")
    assert change.outcome is PromotionOutcome.SKIPPED
    assert change.reason == "changes_not_promotable"
    assert not resolver.calls or all(
        c.source_message_ids != ("4", "5") for c in resolver.calls[0][0]
    )


# ----------------------------------------------------------------------
# 7-13: project_id, confidence, provenance
# ----------------------------------------------------------------------


def test_user_fact_never_inherits_project_id(promoter, resolver) -> None:
    promoter.promote(make_compaction(), project_id="proj-1")

    candidates = resolver.calls[0][0]
    user_fact = next(c for c in candidates if c.type is MemoryType.USER_FACT)
    assert user_fact.project_id is None


def test_project_fact_requires_project_id(promoter, resolver, memories) -> None:
    result = promoter.promote(make_compaction())

    fact = next(r for r in result.items if r.item_id == "fact-2")
    assert fact.outcome is PromotionOutcome.REJECTED
    assert fact.reason == "project_fact_requires_project_id"
    assert all(m.content != "FRIDAY uses Python 3.12." for m in memories.memories)


def test_project_id_never_derived_from_item_content(promoter, resolver) -> None:
    content = "The project Phoenix uses Bazel."
    no_project_compaction = make_compaction(
        facts=(make_item("fact-a", content, (1, 2)),),
    )
    with_project_compaction = make_compaction(
        facts=(make_item("fact-b", content, (1, 2)),),
    )

    no_project = promoter.promote(no_project_compaction)
    assert next(r for r in no_project.items if r.item_id == "fact-a").reason == (
        "project_fact_requires_project_id"
    )

    promoter.promote(with_project_compaction, project_id="proj-9")
    candidates = resolver.calls[-1][0]
    fact = next(c for c in candidates if c.content == content)
    assert fact.project_id == "proj-9"


def test_confidence_always_explicit(promoter, resolver) -> None:
    promoter.promote(make_compaction(), project_id="proj-1")

    candidates = resolver.calls[0][0]
    assert candidates
    assert all(c.confidence is MemoryConfidence.EXPLICIT for c in candidates)


def test_inferred_never_assigned(promoter, resolver) -> None:
    promoter.promote(make_compaction(), project_id="proj-1")

    candidates = resolver.calls[0][0]
    assert all(c.confidence is not MemoryConfidence.INFERRED for c in candidates)


def test_provenance_copied_from_item(promoter, resolver) -> None:
    promoter.promote(make_compaction(), project_id="proj-1")

    candidates = resolver.calls[0][0]
    user_fact = next(c for c in candidates if c.type is MemoryType.USER_FACT)
    assert user_fact.source_conversation_id == "42"
    assert user_fact.source_message_ids == ("1", "2")


def test_conversation_id_copied(promoter, resolver) -> None:
    promoter.promote(make_compaction(), project_id="proj-1")

    candidates = resolver.calls[0][0]
    assert all(c.source_conversation_id == "42" for c in candidates)


# ----------------------------------------------------------------------
# 14-18: resolver interactions
# ----------------------------------------------------------------------


def test_candidates_pass_through_resolver(promoter, resolver) -> None:
    promoter.promote(make_compaction(), project_id="proj-1")

    assert len(resolver.calls) == 1
    candidates = resolver.calls[0][0]
    assert [c.source_message_ids for c in candidates] == [("1", "2"), ("2", "3"), ("3", "4")]


def test_resolver_create_persists_memory_and_marks_promoted(
    promoter, ledger, memories
) -> None:
    result = promoter.promote(make_compaction(), project_id="proj-1")

    outcome = next(r for r in result.items if r.item_id == "fact-1")
    assert outcome.outcome is PromotionOutcome.PROMOTED
    assert len(outcome.memory_ids) == 1
    entry = ledger.entry("fact-1")
    assert entry.status is PromotionStatus.PROMOTED
    assert entry.resolved_memory_ids == outcome.memory_ids
    assert entry.resolution_kind is PromotionResolutionKind.CREATE
    assert memories.memories


def test_resolver_supersede_marks_promoted(promoter, ledger, resolver) -> None:
    resolver.kinds = [ResolutionKind.SUPERSEDE, ResolutionKind.CREATE, ResolutionKind.CREATE]
    result = promoter.promote(make_compaction(), project_id="proj-1")

    outcome = next(r for r in result.items if r.item_id == "fact-1")
    assert outcome.outcome is PromotionOutcome.PROMOTED
    assert outcome.resolution_kind is PromotionResolutionKind.SUPERSEDE
    assert ledger.entry("fact-1").resolution_kind is PromotionResolutionKind.SUPERSEDE


def test_resolver_reject_marks_rejected(promoter, ledger, memories, resolver) -> None:
    resolver.kinds = [ResolutionKind.REJECT, ResolutionKind.CREATE, ResolutionKind.CREATE]
    result = promoter.promote(make_compaction(), project_id="proj-1")

    outcome = next(r for r in result.items if r.item_id == "fact-1")
    assert outcome.outcome is PromotionOutcome.REJECTED
    assert outcome.reason == "fake_reject"
    entry = ledger.entry("fact-1")
    assert entry.status is PromotionStatus.REJECTED
    assert entry.resolution_reason == "fake_reject"
    assert all(m.content != "I use Ubuntu on my desktop." for m in memories.memories)


def test_malformed_candidate_rejected(promoter, ledger, memories, monkeypatch) -> None:
    def boom(*_args, **_kwargs) -> MemoryCandidate:
        raise ValueError("boom")

    monkeypatch.setattr(ConversationMemoryPromoter, "_build_candidate", staticmethod(boom))
    result = promoter.promote(make_compaction(), project_id="proj-1")

    outcome = next(r for r in result.items if r.item_id == "fact-1")
    assert outcome.outcome is PromotionOutcome.REJECTED
    assert outcome.reason == "invalid_candidate: boom"
    entry = ledger.entry("fact-1")
    assert entry.status is PromotionStatus.REJECTED
    assert not memories.memories


# ----------------------------------------------------------------------
# 19-22: failure and terminal-state handling
# ----------------------------------------------------------------------


def test_memory_storage_failure_leaves_pending(promoter, ledger, memories) -> None:
    memories.fail_apply = "db down"
    result = promoter.promote(make_compaction(), project_id="proj-1")

    outcome = next(r for r in result.items if r.item_id == "fact-1")
    assert outcome.outcome is PromotionOutcome.FAILED
    assert outcome.reason.startswith("memory_application_failed")
    assert ledger.entry("fact-1").status is PromotionStatus.PENDING


def test_transient_failure_updates_retry_count_and_last_error(
    promoter, ledger, memories
) -> None:
    memories.fail_apply = "db down"
    promoter.promote(make_compaction(), project_id="proj-1")

    entry = ledger.entry("fact-1")
    assert entry.retry_count == 1
    assert entry.last_error == "memory_application_failed: db down"
    assert entry.status is PromotionStatus.PENDING


def test_already_promoted_is_noop(promoter, ledger, resolver, memories) -> None:
    compaction = make_compaction()
    for item_id, category in (
        ("fact-1", CompactionItemCategory.FACTS),
        ("fact-2", CompactionItemCategory.FACTS),
        ("decision-1", CompactionItemCategory.DECISIONS),
    ):
        ledger._entries[item_id] = seeded_promoted(item_id, category)

    result = promoter.promote(compaction, project_id="proj-1")

    fact = next(r for r in result.items if r.item_id == "fact-1")
    assert fact.outcome is PromotionOutcome.NOOP
    assert fact.reason == "already_promoted"
    assert resolver.calls == []


def test_already_rejected_is_noop(promoter, ledger, resolver, memories) -> None:
    compaction = make_compaction()
    for item_id, category in (
        ("fact-1", CompactionItemCategory.FACTS),
        ("fact-2", CompactionItemCategory.FACTS),
        ("decision-1", CompactionItemCategory.DECISIONS),
    ):
        ledger._entries[item_id] = seeded_rejected(item_id, category)

    result = promoter.promote(compaction, project_id="proj-1")

    fact = next(r for r in result.items if r.item_id == "fact-1")
    assert fact.outcome is PromotionOutcome.NOOP
    assert fact.reason == "already_rejected"
    assert resolver.calls == []


# ----------------------------------------------------------------------
# 23-28: batching, ordering, immutability
# ----------------------------------------------------------------------


def test_deterministic_result_order_and_candidate_order(promoter, resolver) -> None:
    result = promoter.promote(make_compaction(), project_id="proj-1")

    assert [r.item_id for r in result.items] == [
        "fact-1",
        "fact-2",
        "decision-1",
        "change-1",
        "question-1",
    ]
    assert [c.source_message_ids for c in resolver.calls[0][0]] == [
        ("1", "2"),
        ("2", "3"),
        ("3", "4"),
    ]


def test_mixed_resolution_outcomes_in_one_batch(
    promoter, ledger, memories, resolver
) -> None:
    resolver.kinds = [ResolutionKind.CREATE, ResolutionKind.REJECT, ResolutionKind.CREATE]
    result = promoter.promote(make_compaction(), project_id="proj-1")

    by_id = {r.item_id: r for r in result.items}
    assert by_id["fact-1"].outcome is PromotionOutcome.PROMOTED
    assert by_id["fact-2"].outcome is PromotionOutcome.REJECTED
    assert by_id["decision-1"].outcome is PromotionOutcome.PROMOTED
    assert len(memories.memories) == 2
    assert ledger.entry("fact-2").status is PromotionStatus.REJECTED


def test_single_coherent_batch(promoter, memories) -> None:
    promoter.promote(make_compaction(), project_id="proj-1")

    assert len(memories.batches) == 1
    assert len(memories.batches[0]) == 3


def test_batch_failure_persists_no_partial_memory(promoter, ledger, memories) -> None:
    memories.fail_apply = "db down"
    promoter.promote(make_compaction(), project_id="proj-1")

    assert memories.memories == []
    for item_id in ("fact-1", "fact-2", "decision-1"):
        assert ledger.entry(item_id).status is PromotionStatus.PENDING
        assert ledger.entry(item_id).retry_count == 1


def test_compaction_immutable_after_promote(promoter) -> None:
    compaction = make_compaction()
    before = compaction
    promoter.promote(compaction, project_id="proj-1")

    assert compaction == before
    assert compaction.facts == before.facts
    assert compaction.summary == "The conversation covered setup and design."


def test_raw_items_untouched_by_promote(promoter) -> None:
    compaction = make_compaction()
    items_before = {
        item.item_id: item for item in (*compaction.facts, *compaction.decisions)
    }
    promoter.promote(compaction, project_id="proj-1")

    for item in (*compaction.facts, *compaction.decisions):
        assert item == items_before[item.item_id]
        assert item.source_message_ids == items_before[item.item_id].source_message_ids


# ----------------------------------------------------------------------
# 29-32: isolation guarantees
# ----------------------------------------------------------------------


def test_no_context_manager_interaction() -> None:
    import friday.compaction.promoter as module

    source = inspect.getsource(module)
    assert "friday.context" not in source
    assert "ContextManager" not in source


def test_no_direct_memory_store_interaction() -> None:
    import friday.compaction.promoter as module

    source = inspect.getsource(module)
    assert "SQLiteMemoryStore" not in source
    assert "MemoryStorage" not in source


def test_no_llm_required() -> None:
    import friday.compaction.promoter as module

    source = inspect.getsource(module)
    assert "friday.ai" not in source
    assert "LLMBackend" not in source


def test_ineligible_only_never_touches_memory(promoter, resolver, memories) -> None:
    compaction = make_compaction(
        facts=(),
        decisions=(),
        changes=(make_item("change-1", "Moved storage to SQLite.", (1, 2)),),
        open_questions=(make_item("question-1", "Should it be automatic?", (3,)),),
    )
    result = promoter.promote(compaction, project_id="proj-1")

    assert [r.outcome for r in result.items] == [
        PromotionOutcome.SKIPPED,
        PromotionOutcome.SKIPPED,
    ]
    assert resolver.calls == []
    assert memories.batches == []
    assert memories.memories == []


# ----------------------------------------------------------------------
# 33-34: retry and reconciliation
# ----------------------------------------------------------------------


def test_retry_does_not_duplicate_memory(promoter, ledger, memories) -> None:
    first = promoter.promote(make_compaction(), project_id="proj-1")
    assert all(r.outcome is PromotionOutcome.PROMOTED for r in first.items[:3])
    memory_count_after_first = len(memories.memories)

    second = promoter.promote(make_compaction(), project_id="proj-1")

    by_id = {r.item_id: r for r in second.items}
    assert by_id["fact-1"].outcome is PromotionOutcome.NOOP
    assert by_id["fact-1"].reason == "already_promoted"
    assert by_id["fact-2"].outcome is PromotionOutcome.NOOP
    assert by_id["decision-1"].outcome is PromotionOutcome.NOOP
    assert len(memories.memories) == memory_count_after_first


def test_reconciles_externally_created_memory(promoter, ledger, memories) -> None:
    existing = Memory(
        type=MemoryType.USER_FACT,
        scope=MemoryScope.USER,
        content="I use Ubuntu on my desktop.",
        id="mem-ext",
        provenance=MemoryProvenance(
            source_conversation_id="42", source_message_ids=("1", "2")
        ),
        created_at=FIXED_NOW,
    )
    memories.memories.append(existing)

    result = promoter.promote(make_compaction(), project_id="proj-1")

    fact = next(r for r in result.items if r.item_id == "fact-1")
    assert fact.outcome is PromotionOutcome.RECONCILED
    assert fact.reason == "already_present_in_memory"
    assert fact.memory_ids == ("mem-ext",)
    assert ledger.entry("fact-1").status is PromotionStatus.PROMOTED
    assert len(memories.memories) == 3
    matching = [m for m in memories.memories if m.content == "I use Ubuntu on my desktop."]
    assert len(matching) == 1
    assert matching[0].id == "mem-ext"


# ----------------------------------------------------------------------
# Integration test with real stores
# ----------------------------------------------------------------------


def test_integration_real_stores(tmp_path: Path) -> None:
    conv_db = tmp_path / "conversations.db"
    mem_db = tmp_path / "memory.db"

    conversation_store = SQLiteConversationStore(conv_db)
    conversation = conversation_store.create_conversation()
    for index in range(1, 11):
        conversation_store.save_message(conversation.id, "user", f"Message {index}")
    conversation_store.close()

    compaction_store = SQLiteCompactionStore(conv_db)
    compaction = make_compaction(
        compaction_id="comp-1",
        conversation_id=conversation.id,
    )
    compaction_store.save(compaction)
    compaction_store.close()

    promotion_store = SQLitePromotionStore(conv_db)
    memory_store = SQLiteMemoryStore(mem_db)
    manager = DurableMemoryManager(memory_store)
    resolver = MemoryResolver()
    promoter = ConversationMemoryPromoter(promotion_store, manager, resolver)

    result = promoter.promote(compaction, project_id="proj-1")

    by_id = {r.item_id: r for r in result.items}
    assert by_id["fact-1"].outcome is PromotionOutcome.PROMOTED
    assert by_id["fact-2"].outcome is PromotionOutcome.PROMOTED
    assert by_id["decision-1"].outcome is PromotionOutcome.PROMOTED
    assert by_id["change-1"].outcome is PromotionOutcome.SKIPPED
    assert by_id["question-1"].outcome is PromotionOutcome.SKIPPED

    memories = manager.query(conversation_id=conversation.id)
    assert len(memories) == 3
    assert {m.scope for m in memories} == {MemoryScope.USER, MemoryScope.PROJECT}
    assert all(m.confidence is MemoryConfidence.EXPLICIT for m in memories)

    assert promotion_store.get("fact-1").status is PromotionStatus.PROMOTED
    assert promotion_store.get("fact-2").status is PromotionStatus.PROMOTED
    assert promotion_store.get("decision-1").status is PromotionStatus.PROMOTED

    promotion_store.close()
    memory_store.close()