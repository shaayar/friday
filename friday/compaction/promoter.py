"""ConversationMemoryPromoter — explicit downstream promotion (Phase 4 M6.3, ADR-025).

Wires the compaction promotion pipeline into one explicitly invocable
operation:

    ConversationCompaction
        ↓
    CompactionItem
        ↓
    promotion eligibility (FACTS, DECISIONS only)
        ↓
    MemoryCandidate
        ↓
    MemoryResolver
        ↓
    DurableMemoryManager.apply_batch()
        ↓
    memory.db

The promotion ledger in conversations.db tracks per-item state
(PENDING / PROMOTED / REJECTED). The compaction itself remains immutable;
the compactor remains unaware of memory.db.

The orchestrator is the ONLY component allowed to coordinate compaction,
the promotion ledger, the memory resolver, and the durable memory manager.
It owns category eligibility and the CompactionItem → MemoryCandidate
conversion. Everything else stays dumb/single-purpose.

M6.3 introduces NO new LLM call and NO automatic/background promotion.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from friday.compaction.exceptions import PromotionStorageError
from friday.compaction.models import CompactionItem, ConversationCompaction
from friday.compaction.promotion import (
    CompactionItemCategory,
    CompactionPromotion,
    PromotionResolutionKind,
    PromotionStatus,
)
from friday.memory.candidates import MemoryCandidate, Resolution, ResolutionKind
from friday.memory.models import (
    Memory,
    MemoryConfidence,
    MemoryScope,
    MemoryType,
)
from friday.memory.text import normalize_text

logger = logging.getLogger(__name__)

_ELIGIBLE_CATEGORIES = (
    CompactionItemCategory.FACTS,
    CompactionItemCategory.DECISIONS,
)

_INELIGIBLE_REASONS = {
    CompactionItemCategory.CHANGES: "changes_not_promotable",
    CompactionItemCategory.OPEN_QUESTIONS: "open_questions_not_promotable",
}

# ----------------------------------------------------------------------
# Deterministic fact-subject classification (USER vs PROJECT scope).
#
# Scope is determined by the SUBJECT of the fact, never by the presence of
# an active project. When the subject cannot be determined safely, the fact
# is skipped conservatively rather than guessed.
# ----------------------------------------------------------------------

_USER_SUBJECT_RE = re.compile(r"^\s*(i|i'm|i am|i've|my|mine|me)\b", re.IGNORECASE)
_USER_MENTION_RE = re.compile(r"\b(the user|user)\b", re.IGNORECASE)
_PROJECT_SUBJECT_RE = re.compile(
    r"^\s*(the project|this project|our project|project|friday|"
    r"the system|this system|the app|this app|the application|"
    r"this application|the assistant|the agent|the tool|the codebase)\b",
    re.IGNORECASE,
)
_PROJECT_MENTION_RE = re.compile(r"\b(the project|this project|project)\b", re.IGNORECASE)


def _classify_fact_type(content: str) -> MemoryType | None:
    """Return USER_FACT / PROJECT_FACT, or None when the subject is unclear."""
    text = content.strip()
    if _USER_SUBJECT_RE.match(text):
        return MemoryType.USER_FACT
    if _PROJECT_SUBJECT_RE.match(text):
        return MemoryType.PROJECT_FACT
    if _USER_MENTION_RE.search(text):
        return MemoryType.USER_FACT
    if _PROJECT_MENTION_RE.search(text):
        return MemoryType.PROJECT_FACT
    return None


class PromotionOutcome(str, Enum):
    """Outcome of promotion for a single compaction item."""

    SKIPPED = "skipped"
    PROMOTED = "promoted"
    REJECTED = "rejected"
    RECONCILED = "reconciled"
    NOOP = "noop"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class PromotionItemResult:
    """Per-item outcome of one promotion attempt."""

    item_id: str
    category: CompactionItemCategory
    outcome: PromotionOutcome
    memory_ids: tuple[str, ...] = ()
    resolution_kind: PromotionResolutionKind | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class PromotionResult:
    """Outcome of one ``promote`` invocation.

    ``items`` is in deterministic order: facts (tuple order), then decisions
    (tuple order), then changes, then open_questions.
    """

    compaction_id: str
    items: tuple[PromotionItemResult, ...]


class PromotionLedgerStore(Protocol):
    """Ledger operations the promoter requires (satisfied by ``SQLitePromotionStore``)."""

    def get(self, item_id: str) -> CompactionPromotion | None: ...

    def save(self, promotion: CompactionPromotion) -> CompactionPromotion: ...

    def replace(self, promotion: CompactionPromotion) -> CompactionPromotion: ...


class MemoryManager(Protocol):
    """Durable-memory operations the promoter requires (satisfied by ``DurableMemoryManager``)."""

    def get_active(
        self,
        *,
        scope: MemoryScope | None = None,
        project_id: str | None = None,
        valid_at=None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Memory]: ...

    def apply_batch(self, resolutions: list[Resolution]) -> list[Memory | None]: ...


class PromotionResolver(Protocol):
    """Candidate resolution (satisfied by ``MemoryResolver``)."""

    def resolve(
        self,
        candidates: list[MemoryCandidate],
        *,
        existing_memories: list[Memory],
    ) -> list[Resolution]: ...


@dataclass(frozen=True, slots=True)
class _Plan:
    """Internal plan for one compaction item during a promotion attempt."""

    result: PromotionItemResult | None
    ledger: CompactionPromotion | None = None
    item: CompactionItem | None = None
    category: CompactionItemCategory | None = None
    candidate: MemoryCandidate | None = None


class ConversationMemoryPromoter:
    """Explicitly invocable compaction → durable-memory promotion orchestrator."""

    def __init__(
        self,
        promotion_store: PromotionLedgerStore,
        memory_manager: MemoryManager,
        resolver: PromotionResolver,
    ) -> None:
        self._promotion_store = promotion_store
        self._memory_manager = memory_manager
        self._resolver = resolver

    def promote(
        self,
        compaction: ConversationCompaction,
        *,
        project_id: str | None = None,
    ) -> PromotionResult:
        """Promote eligible compaction items into durable memory.

        ``project_id`` may ONLY come from the deterministic caller; it is
        never derived from compaction/item content or LLM reasoning. Ineligible
        categories are reported as explicit skipped results, never errors and
        never silently discarded.
        """
        if not isinstance(compaction, ConversationCompaction):
            raise TypeError("expected a ConversationCompaction")
        if project_id is not None:
            project_id = project_id.strip() or None

        plans: list[_Plan] = []
        for category in (
            CompactionItemCategory.FACTS,
            CompactionItemCategory.DECISIONS,
            CompactionItemCategory.CHANGES,
            CompactionItemCategory.OPEN_QUESTIONS,
        ):
            for item in getattr(compaction, category.value):
                plans.append(self._plan_item(compaction, category, item, project_id))

        batch_outcomes: dict[str, PromotionItemResult] = {}
        pending = [plan for plan in plans if plan.candidate is not None]
        if pending:
            batch_outcomes.update(
                self._process_batch(pending, compaction_id=compaction.compaction_id)
            )

        results = [
            plan.result if plan.result is not None else batch_outcomes[plan.item.item_id]
            for plan in plans
        ]
        return PromotionResult(compaction.compaction_id, tuple(results))

    # ------------------------------------------------------------------
    # Planning
    # ------------------------------------------------------------------

    def _plan_item(
        self,
        compaction: ConversationCompaction,
        category: CompactionItemCategory,
        item: CompactionItem,
        project_id: str | None,
    ) -> _Plan:
        if category in _INELIGIBLE_REASONS:
            return _Plan(
                result=PromotionItemResult(
                    item.item_id,
                    category,
                    PromotionOutcome.SKIPPED,
                    reason=_INELIGIBLE_REASONS[category],
                )
            )

        ledger = self._promotion_store.get(item.item_id)
        if ledger is None:
            ledger = self._promotion_store.save(
                CompactionPromotion.pending(
                    item_id=item.item_id,
                    compaction_id=compaction.compaction_id,
                    category=category,
                )
            )
        if ledger.status is PromotionStatus.PROMOTED:
            return _Plan(
                result=PromotionItemResult(
                    item.item_id, category, PromotionOutcome.NOOP, reason="already_promoted"
                )
            )
        if ledger.status is PromotionStatus.REJECTED:
            return _Plan(
                result=PromotionItemResult(
                    item.item_id, category, PromotionOutcome.NOOP, reason="already_rejected"
                )
            )

        matching = self._find_matching_memory(compaction, item)
        if matching is not None:
            promoted = ledger.mark_promoted((matching.id,))
            self._promotion_store.replace(promoted)
            return _Plan(
                result=PromotionItemResult(
                    item.item_id,
                    category,
                    PromotionOutcome.RECONCILED,
                    memory_ids=(matching.id,),
                    reason="already_present_in_memory",
                )
            )

        memory_type = self._determine_memory_type(category, item, project_id)
        if memory_type is None:
            reason = self._determine_skip_reason(category, item, project_id)
            self._promotion_store.replace(ledger.mark_rejected(reason))
            return _Plan(
                result=PromotionItemResult(
                    item.item_id, category, PromotionOutcome.REJECTED, reason=reason
                )
            )

        try:
            candidate = self._build_candidate(item, memory_type, compaction.conversation_id, project_id)
        except (TypeError, ValueError) as exc:
            reason = f"invalid_candidate: {exc}"
            self._promotion_store.replace(ledger.mark_rejected(reason))
            return _Plan(
                result=PromotionItemResult(
                    item.item_id, category, PromotionOutcome.REJECTED, reason=reason
                )
            )

        return _Plan(result=None, ledger=ledger, item=item, category=category, candidate=candidate)

    def _determine_memory_type(
        self,
        category: CompactionItemCategory,
        item: CompactionItem,
        project_id: str | None,
    ) -> MemoryType | None:
        if category is CompactionItemCategory.FACTS:
            memory_type = _classify_fact_type(item.content)
            if memory_type is MemoryType.PROJECT_FACT and project_id is None:
                return None
            return memory_type
        if project_id is None:
            return None
        return MemoryType.PROJECT_DECISION

    def _determine_skip_reason(
        self,
        category: CompactionItemCategory,
        item: CompactionItem,
        project_id: str | None,
    ) -> str:
        if category is CompactionItemCategory.FACTS:
            if _classify_fact_type(item.content) is MemoryType.PROJECT_FACT:
                return "project_fact_requires_project_id"
            return "fact_subject_unclear"
        return "decision_requires_project_id"

    @staticmethod
    def _build_candidate(
        item: CompactionItem,
        memory_type: MemoryType,
        conversation_id: int,
        project_id: str | None,
    ) -> MemoryCandidate:
        """Construct a validated candidate; content is data, not instructions.

        Promotion always assigns ``MemoryConfidence.EXPLICIT``; the resolver
        remains authoritative and may demote it. ``reasoning`` is left None
        (the compaction item carries no LLM reasoning to copy).
        """
        candidate_project_id = project_id if memory_type.default_scope is MemoryScope.PROJECT else None
        return MemoryCandidate(
            type=memory_type,
            scope=memory_type.default_scope,
            content=item.content,
            confidence=MemoryConfidence.EXPLICIT,
            source_conversation_id=conversation_id,
            source_message_ids=tuple(str(message_id) for message_id in item.source_message_ids),
            project_id=candidate_project_id,
            reasoning=None,
        )

    def _find_matching_memory(
        self, compaction: ConversationCompaction, item: CompactionItem
    ) -> Memory | None:
        """Reconcile a PENDING item whose memory already exists.

        Used to make retry/reconciliation safe: a memory write that succeeded
        while the ledger update failed is recognized by identical content and
        provenance, so a retry never blindly duplicates a memory.
        """
        conversation_id = str(compaction.conversation_id)
        item_ids = {str(message_id) for message_id in item.source_message_ids}
        item_norm = normalize_text(item.content)
        for memory in self._memory_manager.get_active():
            if memory.provenance.source_conversation_id != conversation_id:
                continue
            if set(memory.provenance.source_message_ids) != item_ids:
                continue
            if normalize_text(memory.content) != item_norm:
                continue
            return memory
        return None

    # ------------------------------------------------------------------
    # Batch resolution + application
    # ------------------------------------------------------------------

    def _load_existing(self, candidates: list[MemoryCandidate]) -> list[Memory]:
        contexts: set[tuple[MemoryScope, str | None]] = set()
        for candidate in candidates:
            if candidate.scope is MemoryScope.USER:
                contexts.add((MemoryScope.USER, None))
            else:
                contexts.add((MemoryScope.PROJECT, candidate.project_id))
        existing: list[Memory] = []
        for scope, project_id in contexts:
            existing.extend(self._memory_manager.get_active(scope=scope, project_id=project_id))
        return existing

    def _process_batch(
        self, pending: list[_Plan], *, compaction_id: str
    ) -> dict[str, PromotionItemResult]:
        candidates = [plan.candidate for plan in pending]

        try:
            resolutions = self._resolver.resolve(
                candidates, existing_memories=self._load_existing(candidates)
            )
        except Exception as exc:  # noqa: BLE001 - transient infrastructure failure
            logger.warning("Promotion resolution failed for compaction %s: %s", compaction_id, exc)
            return {
                plan.item.item_id: self._transient(plan, f"resolution_failed: {exc}")
                for plan in pending
            }

        try:
            applied = self._memory_manager.apply_batch(resolutions)
        except Exception as exc:  # noqa: BLE001 - transient infrastructure failure
            logger.warning("Memory application failed for compaction %s: %s", compaction_id, exc)
            return {
                plan.item.item_id: self._transient(plan, f"memory_application_failed: {exc}")
                for plan in pending
            }

        outcomes: dict[str, PromotionItemResult] = {}
        for plan, resolution, memory in zip(pending, resolutions, applied):
            outcomes[plan.item.item_id] = self._apply_resolution(plan, resolution, memory)
        return outcomes

    def _apply_resolution(
        self,
        plan: _Plan,
        resolution: Resolution,
        memory: Memory | None,
    ) -> PromotionItemResult:
        item_id = plan.item.item_id
        category = plan.category
        ledger = plan.ledger

        if resolution.kind is ResolutionKind.REJECT:
            reason = resolution.reason or "rejected_by_resolver"
            self._promotion_store.replace(ledger.mark_rejected(reason))
            return PromotionItemResult(item_id, category, PromotionOutcome.REJECTED, reason=reason)

        if resolution.kind is ResolutionKind.CREATE:
            kind = PromotionResolutionKind.CREATE
        elif resolution.kind is ResolutionKind.SUPERSEDE:
            kind = PromotionResolutionKind.SUPERSEDE
        else:
            reason = f"unsupported_resolution_kind: {resolution.kind.value}"
            self._promotion_store.replace(ledger.mark_rejected(reason))
            return PromotionItemResult(item_id, category, PromotionOutcome.REJECTED, reason=reason)

        memory_ids = (memory.id,) if memory is not None else ()
        try:
            promoted = ledger.mark_promoted(memory_ids, resolution_kind=kind)
            self._promotion_store.replace(promoted)
        except (PromotionStorageError, OSError, ValueError) as exc:
            # Memory succeeded but the ledger update failed: keep PENDING and
            # record the failure; a retry reconciles via provenance/content.
            logger.warning("Ledger update failed for item %s: %s", item_id, exc)
            try:
                self._promotion_store.replace(ledger.record_transient_failure(f"ledger_update_failed: {exc}"))
            except Exception:  # noqa: BLE001
                logger.warning("Could not record transient ledger failure for item %s", item_id)
            return PromotionItemResult(
                item_id,
                category,
                PromotionOutcome.FAILED,
                memory_ids=memory_ids,
                resolution_kind=kind,
                reason="ledger_update_failed",
            )

        return PromotionItemResult(
            item_id,
            category,
            PromotionOutcome.PROMOTED,
            memory_ids=memory_ids,
            resolution_kind=kind,
            reason=resolution.reason,
        )

    def _transient(self, plan: _Plan, error: str) -> PromotionItemResult:
        """Record a transient failure: stay PENDING, increment retry, keep reason."""
        self._promotion_store.replace(plan.ledger.record_transient_failure(error))
        return PromotionItemResult(
            plan.item.item_id,
            plan.category,
            PromotionOutcome.FAILED,
            reason=error,
        )


__all__ = [
    "ConversationMemoryPromoter",
    "PromotionItemResult",
    "PromotionOutcome",
    "PromotionResult",
]