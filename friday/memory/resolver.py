"""MemoryResolver — the only component that decides memory mutations.

The resolver turns extracted candidates into concrete ``Resolution`` actions
(CREATE / SUPERSEDE / INVALIDATE / REJECT) using deterministic, conservative
heuristics. It never touches storage; ``DurableMemoryManager.apply_batch``
executes its decisions.

Conservative-by-design guarantees:

- Deduplication is strict: exact, containment, then fuzzy (difflib) matches
  reject a candidate outright.
- Contradictions and ambiguous overlaps NEVER supersede or invalidate an
  existing memory on weak evidence. When no advisory LLM is configured, the
  existing memory is preserved and the candidate is rejected.
- Confidence may only be lowered, never raised: hedged EXPLICIT statements
  are demoted to TENTATIVE.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable
from difflib import SequenceMatcher

from friday.ai.backend import LLMBackend
from friday.memory.candidates import MemoryCandidate, Resolution, ResolutionKind
from friday.memory.models import Memory, MemoryConfidence, MemoryScope
from friday.memory.text import (
    has_hedged_language,
    has_negation,
    has_transition_marker,
    normalize_text,
    significant_terms,
)

logger = logging.getLogger(__name__)


class MemoryResolver:
    """Deterministic, conservative candidate resolution."""

    def __init__(
        self,
        *,
        similarity_threshold: float = 0.85,
        llm: LLMBackend | None = None,
    ) -> None:
        self._threshold = similarity_threshold
        self._llm = llm

    def resolve(
        self,
        candidates: list[MemoryCandidate],
        *,
        existing_memories: list[Memory],
    ) -> list[Resolution]:
        """Resolve each candidate into exactly one Resolution.

        ``existing_memories`` must already be scoped/active-filtered by the
        caller (e.g. the current project's active memories).
        """
        resolutions: list[Resolution] = []
        accepted_contents: list[tuple[str, MemoryScope]] = []

        for candidate in candidates:
            candidate = self._apply_confidence_corrections(candidate)

            duplicate = self._find_duplicate(candidate, existing_memories)
            if duplicate is not None:
                resolutions.append(
                    Resolution(
                        kind=ResolutionKind.REJECT,
                        candidate=candidate,
                        existing_memory_id=duplicate.id,
                        reason=f"duplicate of existing memory {duplicate.id}",
                    )
                )
                continue

            in_batch_duplicate = self._find_duplicate_in_batch(candidate, accepted_contents)
            if in_batch_duplicate:
                resolutions.append(
                    Resolution(
                        kind=ResolutionKind.REJECT,
                        candidate=candidate,
                        reason="duplicate of candidate already accepted in this batch",
                    )
                )
                continue

            relevant = self._find_relevant(candidate, existing_memories)
            decision = self._classify(candidate, relevant)
            resolutions.append(decision)

            if decision.kind in (ResolutionKind.CREATE, ResolutionKind.SUPERSEDE):
                accepted_contents.append((normalize_text(candidate.content), candidate.scope))

        return resolutions

    # ------------------------------------------------------------------
    # Confidence corrections (lowering only)
    # ------------------------------------------------------------------

    def _apply_confidence_corrections(self, candidate: MemoryCandidate) -> MemoryCandidate:
        if (
            candidate.confidence is MemoryConfidence.EXPLICIT
            and has_hedged_language(candidate.content)
        ):
            return MemoryCandidate(
                type=candidate.type,
                scope=candidate.scope,
                content=candidate.content,
                confidence=MemoryConfidence.TENTATIVE,
                source_conversation_id=candidate.source_conversation_id,
                source_message_ids=candidate.source_message_ids,
                project_id=candidate.project_id,
                reasoning=candidate.reasoning,
            )
        return candidate

    # ------------------------------------------------------------------
    # Deduplication pipeline: exact -> containment -> fuzzy
    # ------------------------------------------------------------------

    def _same_context(self, memory: Memory, candidate: MemoryCandidate) -> bool:
        """A candidate may only interact with memories in the same scope+project."""
        return memory.scope is candidate.scope and (
            memory.scope is not MemoryScope.PROJECT or memory.project_id == candidate.project_id
        )

    def _find_duplicate(self, candidate: MemoryCandidate, existing: list[Memory]) -> Memory | None:
        normalized = normalize_text(candidate.content)
        same_context = [m for m in existing if self._same_context(m, candidate)]

        for memory in same_context:
            if normalized == normalize_text(memory.content):
                return memory

        for memory in same_context:
            other = normalize_text(memory.content)
            if normalized and (normalized in other or other in normalized):
                return memory

        for memory in same_context:
            ratio = SequenceMatcher(None, normalized, normalize_text(memory.content)).ratio()
            if ratio >= self._threshold:
                return memory

        return None

    def _find_duplicate_in_batch(
        self, candidate: MemoryCandidate, accepted: list[tuple[str, MemoryScope]]
    ) -> bool:
        normalized = normalize_text(candidate.content)
        for accepted_norm, scope in accepted:
            if scope is not candidate.scope:
                continue
            if normalized == accepted_norm or (
                normalized and (normalized in accepted_norm or accepted_norm in normalized)
            ):
                return True
            if SequenceMatcher(None, normalized, accepted_norm).ratio() >= self._threshold:
                return True
        return False

    # ------------------------------------------------------------------
    # Relevance and classification
    # ------------------------------------------------------------------

    def _find_relevant(self, candidate: MemoryCandidate, existing: list[Memory]) -> Memory | None:
        """Find the most topically related existing memory (same scope).

        Requires at least 2 shared significant terms to establish relevance.
        This prevents generic verbs/connectors (filtered in significant_terms)
        from creating false relevance between unrelated memories.
        """
        terms = significant_terms(candidate.content)
        if not terms:
            return None

        best: Memory | None = None
        best_overlap = 0.0
        for memory in existing:
            if not self._same_context(memory, candidate):
                continue
            memory_terms = significant_terms(memory.content)
            if not memory_terms:
                continue
            shared = terms & memory_terms
            # Require at least 2 shared meaningful terms for relevance.
            # Single-term overlaps (e.g., just "use") do not establish topical relatedness.
            if len(shared) < 2:
                continue
            overlap = len(shared) / len(memory_terms)
            if overlap > best_overlap:
                best_overlap = overlap
                best = memory
        return best if best_overlap > 0.0 else None

    def _classify(self, candidate: MemoryCandidate, relevant: Memory | None) -> Resolution:
        if has_transition_marker(candidate.content):
            if relevant is not None:
                return Resolution(
                    kind=ResolutionKind.SUPERSEDE,
                    candidate=candidate,
                    existing_memory_id=relevant.id,
                    reason="clear state-change update for a related memory",
                )
            return Resolution(
                kind=ResolutionKind.CREATE,
                candidate=candidate,
                reason="state change with no prior related memory",
            )

        if relevant is not None and has_negation(candidate.content):
            return self._contradiction_decision(candidate, relevant)

        if relevant is not None:
            return self._ambiguous_decision(candidate, relevant)

        return Resolution(
            kind=ResolutionKind.CREATE,
            candidate=candidate,
            reason="no related existing memory",
        )

    def _contradiction_decision(
        self, candidate: MemoryCandidate, relevant: Memory
    ) -> Resolution:
        if self._llm is not None:
            decision = self._ask_llm(candidate, relevant)
            if decision is not None:
                return decision
        return Resolution(
            kind=ResolutionKind.REJECT,
            candidate=candidate,
            existing_memory_id=relevant.id,
            reason="contradicts existing memory; preserving existing conservatively",
        )

    def _ambiguous_decision(self, candidate: MemoryCandidate, relevant: Memory) -> Resolution:
        if self._llm is not None:
            decision = self._ask_llm(candidate, relevant)
            if decision is not None:
                return decision
        return Resolution(
            kind=ResolutionKind.REJECT,
            candidate=candidate,
            existing_memory_id=relevant.id,
            reason="ambiguous relationship to existing memory; preserving existing conservatively",
        )

    # ------------------------------------------------------------------
    # Advisory LLM (optional, strictly best-effort)
    # ------------------------------------------------------------------

    def _ask_llm(self, candidate: MemoryCandidate, relevant: Memory) -> Resolution | None:
        system = (
            "You decide whether a proposed durable memory should supersede, "
            "coexist with, or be rejected relative to an existing memory. "
            "Reply with exactly one JSON object: {\"action\": "
            "\"supersede\"|\"create\"|\"reject\"}."
        )
        user = (
            f"Existing memory: {relevant.content}\n"
            f"Proposed memory: {candidate.content}\n"
            "Return {\"action\": ...}"
        )
        try:
            raw = self._llm.complete(system, user)
        except Exception:  # noqa: BLE001 - advisory path must never break extraction
            logger.warning("LLM advisory resolution failed; rejecting conservatively")
            return None
        if isinstance(raw, Awaitable):
            # The protocol is async, but this best-effort path is synchronous
            # and is never given an async backend in production. Close the
            # coroutine rather than leaking it.
            raw.close()
            logger.warning("LLM advisory backend is async; skipping advisory step")
            return None
        return self._parse_llm_decision(raw, candidate, relevant)

    def _parse_llm_decision(
        self, raw: str, candidate: MemoryCandidate, relevant: Memory
    ) -> Resolution | None:
        action = None
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                action = str(data.get("action", "")).lower()
        except json.JSONDecodeError:
            logger.warning("LLM advisory response was not JSON; rejecting conservatively")
            return None

        if action == "supersede":
            return Resolution(
                kind=ResolutionKind.SUPERSEDE,
                candidate=candidate,
                existing_memory_id=relevant.id,
                reason="advisory LLM confirmed supersession",
            )
        if action == "create":
            return Resolution(
                kind=ResolutionKind.CREATE,
                candidate=candidate,
                reason="advisory LLM confirmed coexistence",
            )
        logger.warning("LLM advisory response was unrecognized; rejecting conservatively")
        return None


__all__ = ["MemoryResolver"]