"""Deterministic text utilities for memory distillation and retrieval.

These helpers are intentionally simple and conservative. No embeddings,
no NLP libraries, no FTS5 — just normalization, stopword filtering, and a
small trivia gate used to avoid turning conversational filler into durable
memory.
"""

from __future__ import annotations

import re

_TRIVIAL_PHRASES = {
    "okay",
    "ok",
    "thanks",
    "thank you",
    "thx",
    "sure",
    "fine",
    "yes",
    "yeah",
    "yep",
    "no",
    "nope",
    "got it",
    "understood",
    "right",
    "alright",
    "perfect",
    "awesome",
    "cool",
    "great",
    "good",
    "nice",
    "let's do that",
    "lets do that",
    "let's do it",
    "lets do it",
    "let's go",
    "lets go",
    "of course",
    "no problem",
}

_TRIVIAL_RE = re.compile(
    r"^(ok|okay|thanks|thank you|thx|sure|fine|yes|yeah|yep|no|nope|"
    r"got it|understood|right|alright|perfect|awesome|cool|great|good|"
    r"nice)[,.\s!?]*$",
    re.IGNORECASE,
)

_STOPWORDS = {
    "the",
    "a",
    "an",
    "and",
    "or",
    "but",
    "for",
    "of",
    "to",
    "in",
    "on",
    "at",
    "with",
    "by",
    "from",
    "as",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "being",
    "it",
    "its",
    "this",
    "that",
    "these",
    "those",
    "i",
    "me",
    "my",
    "we",
    "our",
    "you",
    "your",
    "they",
    "them",
    "their",
    "he",
    "him",
    "his",
    "she",
    "her",
    "do",
    "does",
    "did",
    "have",
    "has",
    "had",
    "will",
    "would",
    "can",
    "could",
    "should",
    "shall",
    "may",
    "might",
    "user",
    "users",
    "the user",
}

_HEDGE_MARKERS = (
    "probably",
    "maybe",
    "perhaps",
    "likely",
    "seems",
    "seem",
    "might",
    "possibly",
    "i think",
    "i believe",
    "not sure",
)

_TRANSITION_MARKERS = (
    "switched from",
    "switched to",
    "moved from",
    "moved to",
    "changed to",
    "replaced",
    "no longer uses",
    "no longer",
    "now uses",
    "stopped using",
)

# Generic verbs/connectors that do not establish topical relevance on their own.
# These are filtered from significant_terms so that memories sharing only
# generic verbs (e.g., "I use X" vs "I use Y") are not considered related.
_GENERIC_VERBS = {
    "use",
    "uses",
    "using",
    "used",
    "like",
    "likes",
    "liked",
    "have",
    "has",
    "had",
    "having",
    "need",
    "needs",
    "needed",
    "want",
    "wants",
    "wanted",
    "prefer",
    "prefers",
    "preferred",
}

_NEGATION_MARKERS = (
    "not",
    "don't",
    "doesn't",
    "never",
    "no longer",
    "stopped",
)


def normalize_text(text: str) -> str:
    """Normalize text for exact/containment comparison.

    Lowercases, strips punctuation and collapses whitespace.
    """
    lowered = text.lower()
    stripped = re.sub(r"[^a-z0-9\s]", " ", lowered)
    return re.sub(r"\s+", " ", stripped).strip()


def significant_terms(text: str) -> set[str]:
    """Return significant terms from text.

    Terms are normalized, lowercased, and filtered against a small stopword
    list. Short terms (length < 3) are excluded. Generic verbs/connectors
    (e.g., use, like, have) are also excluded because they do not establish
    topical relevance on their own.
    """
    normalized = normalize_text(text)
    terms: set[str] = set()
    for token in normalized.split():
        if len(token) < 3:
            continue
        if token in _STOPWORDS:
            continue
        if token in _GENERIC_VERBS:
            continue
        terms.add(token)
    return terms


def is_trivial_content(text: str) -> bool:
    """Return True when ``text`` is conversational filler or near-empty.

    Used as a conservative relevance gate: trivial statements must never
    become durable memory.
    """
    if text is None:
        return True
    stripped = text.strip()
    if not stripped:
        return True
    lowered = stripped.lower()
    if lowered in _TRIVIAL_PHRASES:
        return True
    if _TRIVIAL_RE.match(stripped):
        return True
    core = normalize_text(stripped)
    if not core:
        return True
    return core in _TRIVIAL_PHRASES


def has_hedged_language(text: str) -> bool:
    """Return True when ``text`` contains hedging/speculative language."""
    lowered = text.lower()
    return any(marker in lowered for marker in _HEDGE_MARKERS)


def has_transition_marker(text: str) -> bool:
    """Return True when ``text`` describes a change of state (switched, moved)."""
    lowered = text.lower()
    return any(marker in lowered for marker in _TRANSITION_MARKERS)


def has_negation(text: str) -> bool:
    """Return True when ``text`` contains a negation marker."""
    lowered = text.lower()
    return any(marker in lowered for marker in _NEGATION_MARKERS)


__all__ = [
    "has_hedged_language",
    "has_negation",
    "has_transition_marker",
    "is_trivial_content",
    "normalize_text",
    "significant_terms",
]
