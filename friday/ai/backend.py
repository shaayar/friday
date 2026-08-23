"""Provider-neutral LLM abstraction for memory and context subsystems.

Memory distillation and context compression must never depend on a specific
provider (OpenAI, Groq, Sarvam, LiveKit). This module defines the minimal
contract those subsystems depend on.

The production adapter is wired in :mod:`friday.ai.providers`: it wraps a
configured LiveKit LLM behind this interface. The contract is asynchronous
because every LiveKit LLM plugin exposes ``chat()`` as an async operation.
"""

from __future__ import annotations

from typing import Protocol


class LLMBackend(Protocol):
    """Minimal text-completion contract used by extractors and shrinkers."""

    async def complete(self, system: str, user: str) -> str:
        """Return a text completion for ``user`` given the ``system`` prompt."""
        ...


__all__ = ["LLMBackend"]
