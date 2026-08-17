"""MemoryExtractor — proposes durable-memory candidates from a bounded transcript.

The extractor is a pure proposer. It never persists, never reads durable
storage, and never calls the resolver. Given the most recent ``window_size``
messages of a conversation, it asks an LLM for structured, factual statements,
then validates and normalizes them into ``MemoryCandidate`` objects.

Every failure mode is isolated: malformed JSON, unknown types, invalid
scopes, and missing evidence all produce logged skips rather than errors.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Sequence

from friday.ai.backend import LLMBackend
from friday.memory.candidates import MemoryCandidate
from friday.memory.models import MemoryConfidence, MemoryType
from friday.memory.text import is_trivial_content

logger = logging.getLogger(__name__)

# A transcript message as (message_id, role, content).
Message = tuple[str, str, str]

_TYPE_MAP: dict[str, MemoryType] = {
    "user_fact": MemoryType.USER_FACT,
    "project_fact": MemoryType.PROJECT_FACT,
    "project_constraint": MemoryType.PROJECT_CONSTRAINT,
    "project_decision": MemoryType.PROJECT_DECISION,
    "conversation_summary": MemoryType.CONVERSATION_SUMMARY,
}

_CONFIDENCE_MAP: dict[str, MemoryConfidence] = {
    "explicit": MemoryConfidence.EXPLICIT,
    "inferred": MemoryConfidence.INFERRED,
    "tentative": MemoryConfidence.TENTATIVE,
}

_SYSTEM_PROMPT = (
    "You extract durable, factual statements from a conversation transcript. "
    "The user is talking to an AI assistant. Extract ONLY facts that will be "
    "useful beyond this single conversation: stable preferences, personal "
    "details, project facts, project decisions, constraints, and a concise "
    "summary of what the conversation was about. "
    "Rules:\n"
    "- Never extract greetings, thanks, small talk, or transient instructions.\n"
    "- Content must be a self-contained statement in third person, e.g. "
    "'User prefers dark mode.' or 'The project uses Next.js.'.\n"
    "- Prefer 'explicit' confidence when the user stated it directly; use "
    "'inferred' only when it follows clearly from multiple statements; use "
    "'tentative' for hedged or uncertain statements.\n"
    "- Use 'message_ids' to cite the transcript line IDs that support the "
    "fact. Cite the user's own messages whenever possible.\n"
    "Reply with ONLY a JSON array. Each element is an object with optional "
    "fields: content (string), type ('user_fact'|'project_fact'|"
    "'project_constraint'|'project_decision'|'conversation_summary'), "
    "confidence ('explicit'|'inferred'|'tentative'), message_ids (array of "
    "line IDs), reasoning (string)."
)


class MemoryExtractor:
    """Propose memory candidates from a bounded, chronological transcript."""

    def __init__(
        self,
        llm: LLMBackend,
        *,
        window_size: int = 20,
        min_messages: int = 1,
    ) -> None:
        self._llm = llm
        self._window_size = window_size
        self._min_messages = min_messages

    def extract(
        self,
        messages: Sequence[Message],
        *,
        conversation_id: str | int,
        project_id: str | None = None,
    ) -> list[MemoryCandidate]:
        """Extract validated candidates from the most recent messages.

        ``messages`` must be in chronological order. Only the trailing
        ``window_size`` messages are considered. Project-scoped candidates
        are only produced when ``project_id`` is supplied.
        """
        if not messages:
            return []

        window = list(messages)[-self._window_size :]
        if len(window) < self._min_messages:
            return []

        transcript = self._build_transcript(window)
        user_ids = tuple(str(mid) for mid, role, _ in window if role == "user")
        all_ids = tuple(str(mid) for mid, _, _ in window)

        raw_items = self._ask_llm(transcript)
        if raw_items is None:
            return []

        candidates: list[MemoryCandidate] = []
        for item in raw_items:
            candidate = self._to_candidate(
                item,
                conversation_id=conversation_id,
                project_id=project_id,
                user_ids=user_ids,
                all_ids=all_ids,
            )
            if candidate is not None:
                candidates.append(candidate)

        return candidates

    # ------------------------------------------------------------------
    # Transcript + LLM interaction
    # ------------------------------------------------------------------

    def _build_transcript(self, window: list[Message]) -> str:
        lines = [f"[{message_id}] {role}: {content}" for message_id, role, content in window]
        return "\n".join(lines)

    def _ask_llm(self, transcript: str) -> list[dict] | None:
        try:
            raw = self._llm.complete(_SYSTEM_PROMPT, transcript)
        except Exception:  # noqa: BLE001 - extraction must never break the conversation
            logger.warning("Memory extraction LLM call failed; skipping this round")
            return None
        items = self._parse_candidates(raw)
        if items is None:
            logger.warning("Memory extraction returned unparseable output; skipping")
        return items

    # ------------------------------------------------------------------
    # Parsing (tolerant)
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_candidates(raw: str) -> list[dict] | None:
        """Parse a JSON array from LLM output, tolerating fences/noise."""
        if not raw:
            return None
        text = raw.strip()
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        if not text:
            return None

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            start = text.find("[")
            end = text.rfind("]")
            if start == -1 or end == -1 or end <= start:
                return None
            try:
                data = json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                return None

        if isinstance(data, dict):
            for key in ("facts", "candidates", "memories"):
                if isinstance(data.get(key), list):
                    data = data[key]
                    break

        if not isinstance(data, list):
            return None

        items = [item for item in data if isinstance(item, dict)]
        return items or None

    # ------------------------------------------------------------------
    # Candidate construction (validated)
    # ------------------------------------------------------------------

    def _to_candidate(
        self,
        item: dict,
        *,
        conversation_id: str | int,
        project_id: str | None,
        user_ids: tuple[str, ...],
        all_ids: tuple[str, ...],
    ) -> MemoryCandidate | None:
        content = item.get("content")
        if not isinstance(content, str) or not content.strip():
            return None
        if is_trivial_content(content):
            return None

        memory_type = _TYPE_MAP.get(str(item.get("type", "")).strip())
        if memory_type is None:
            logger.warning("Skipping candidate with unknown type %r", item.get("type"))
            return None

        confidence = _CONFIDENCE_MAP.get(
            str(item.get("confidence", "explicit")).strip(),
            MemoryConfidence.EXPLICIT,
        )

        message_ids = self._resolve_message_ids(item, user_ids, all_ids, memory_type)

        try:
            return MemoryCandidate(
                type=memory_type,
                scope=memory_type.default_scope,
                content=content.strip(),
                confidence=confidence,
                source_conversation_id=conversation_id,
                source_message_ids=message_ids,
                project_id=project_id,
                reasoning=(
                    str(item["reasoning"]).strip()
                    if isinstance(item.get("reasoning"), str) and item["reasoning"].strip()
                    else None
                ),
            )
        except ValueError as exc:
            logger.warning("Skipping invalid candidate: %s", exc)
            return None

    def _resolve_message_ids(
        self,
        item: dict,
        user_ids: tuple[str, ...],
        all_ids: tuple[str, ...],
        memory_type: MemoryType,
    ) -> tuple[str, ...]:
        """Determine the candidate's source message IDs.

        Prefers LLM-supplied IDs (filtered to known transcript IDs); falls
        back to all user message IDs, or all message IDs for summaries.
        """
        supplied = item.get("message_ids")
        if isinstance(supplied, list):
            known = {*all_ids}
            resolved = tuple(
                dict.fromkeys(
                    str(mid)
                    for mid in supplied
                    if str(mid).strip() in known
                )
            )
            if resolved:
                return resolved

        if memory_type is MemoryType.CONVERSATION_SUMMARY:
            return all_ids
        return user_ids or all_ids


__all__ = ["MemoryExtractor", "Message"]