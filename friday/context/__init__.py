"""Context Management — runtime context assembly for the LLM.

Public API:
- ContextBudget / estimate_units / Message
- ContextSnapshot
- ContextManager
- ContextShrinker

Implementation internals (protocols, provider contracts) are unexported.
"""

from friday.context.manager import ContextManager
from friday.context.models import (
    ContextBudget,
    ContextSnapshot,
    Message,
    estimate_units,
)
from friday.context.shrinker import ContextShrinker

__all__ = [
    "ContextBudget",
    "ContextManager",
    "ContextShrinker",
    "ContextSnapshot",
    "Message",
    "estimate_units",
]
