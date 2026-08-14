"""Memory Storage Exceptions."""

from __future__ import annotations


class MemoryStorageError(Exception):
    """Base exception for memory storage errors."""


class MemoryNotFoundError(MemoryStorageError):
    """Raised when a memory ID is not found in storage."""


class MemoryAlreadyExistsError(MemoryStorageError):
    """Raised when attempting to save a memory with an ID that already exists."""


class MemoryCorruptError(MemoryStorageError):
    """Raised when stored data fails validation on load."""