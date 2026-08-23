"""Compaction extraction exceptions.

Small, explicit exception contract so callers can distinguish failure modes
and decide whether to retry:

- ``CompactionProviderError`` — the LLM/provider call itself failed (retryable).
- ``CompactionOutputError`` — the LLM returned output that could not be
  parsed into a valid compaction (malformed or schema-invalid).
"""

from __future__ import annotations


class CompactionError(Exception):
    """Base exception for compaction extraction failures."""


class CompactionProviderError(CompactionError):
    """Raised when the LLM call fails (provider error)."""


class CompactionOutputError(CompactionError):
    """Raised when LLM output cannot be parsed into a valid compaction."""


class CompactionStorageError(CompactionError):
    """Base exception for compaction storage errors."""


class CompactionAlreadyExistsError(CompactionStorageError):
    """Raised when saving a compaction with an ID that already exists."""


class CompactionNotFoundError(CompactionStorageError):
    """Raised when a compaction ID is not found in storage."""


class CompactionCorruptError(CompactionStorageError):
    """Raised when stored compaction data fails validation on load/save."""


class PromotionStorageError(CompactionStorageError):
    """Base exception for promotion-ledger storage errors."""


class PromotionAlreadyExistsError(PromotionStorageError):
    """Raised when saving a promotion whose item_id already exists."""


class PromotionNotFoundError(PromotionStorageError):
    """Raised when a promotion item_id is not found in storage."""


class PromotionCorruptError(PromotionStorageError):
    """Raised when stored promotion data fails validation on load/save."""


__all__ = [
    "CompactionAlreadyExistsError",
    "CompactionCorruptError",
    "CompactionError",
    "CompactionNotFoundError",
    "CompactionOutputError",
    "CompactionProviderError",
    "CompactionStorageError",
    "PromotionAlreadyExistsError",
    "PromotionCorruptError",
    "PromotionNotFoundError",
    "PromotionStorageError",
]
