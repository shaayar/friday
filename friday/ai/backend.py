"""Provider-neutral LLM abstraction for memory and context subsystems.

Memory distillation and context compression must never depend on a specific
provider (OpenAI, Groq, Sarvam, LiveKit). This module defines the minimal
contract those subsystems depend on.

The actual runtime adapter is deliberately deferred: wiring an existing
LiveKit LLM into this interface is the responsibility of the future
assistant/session layer, not Phase 3.
"""

from __future__ import annotations

from typing import Protocol


class LLMBackend(Protocol):
    """Minimal text-completion contract used by extractors and shrinkers."""

    def complete(self, system: str, user: str) -> str:
        """Return a text completion for ``user`` given the ``system`` prompt."""
        ...


__all__ = ["LLMBackend"]