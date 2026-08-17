"""ContextShrinker — LLM-backed compression of older conversation history.

When the assembled context exceeds the budget, the manager calls the
shrinker to condense the older (non-recent) portion of the conversation into
a short factual summary. This module has no storage dependencies; the
manager isolates any failure.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from friday.ai.backend import LLMBackend
from friday.context.models import Message

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are given an older portion of a conversation between a user and an "
    "AI assistant. Compress it into a concise factual summary that preserves "
    "everything still useful: decisions, preferences, personal or project "
    "facts, names, choices, and unresolved open questions. Drop greetings, "
    "small talk, and transient detail. Target at most {max_units} context "
    "units (about 4 characters each). Reply with plain text only — no "
    "preamble, no markdown, no bullet numbering."
)


class ContextShrinker:
    """Compress a bounded, chronological message sequence into a summary."""

    def __init__(self, llm: LLMBackend) -> None:
        self._llm = llm

    def shrink(self, messages: Sequence[Message], *, max_units: int) -> str:
        """Return a compressed summary of ``messages``.

        Raises RuntimeError if the LLM call fails or returns empty output —
        the caller must isolate this.
        """
        transcript = "\n".join(
            f"[{message_id}] {role}: {content}" for message_id, role, content in messages
        )
        system = _SYSTEM_PROMPT.format(max_units=max_units)

        try:
            raw = self._llm.complete(system, transcript)
        except Exception as exc:
            logger.warning("Context compression failed: %s", exc)
            raise RuntimeError(f"context compression failed: {exc}") from exc

        result = raw.strip() if raw else ""
        if not result:
            logger.warning("Context compression returned empty output")
            raise RuntimeError("context compression returned empty output")
        return result


__all__ = ["ContextShrinker"]