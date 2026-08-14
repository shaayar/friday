"""
Filesystem domain models.

These dataclasses form the vocabulary of the filesystem capability layer.
They are transport-independent: the MCP adapter converts them to
JSON-serializable dictionaries only at the tool boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

READ_PERMISSION = "read"
WRITE_PERMISSION = "write"


@dataclass(frozen=True, slots=True)
class Project:
    """A registered project: an explicit authorization for an external
    project root combined with its durable project identity.

    ``id`` is the stable internal project ID, independent of the display
    ``name``. The ID keys the private FRIDAY workspace
    (``~/.friday/projects/<id>/``) so renaming never breaks stored state.
    """

    id: str
    root: Path
    name: str
    permissions: frozenset[str]
    created_at: str

    def allows(self, permission: str) -> bool:
        return permission in self.permissions


@dataclass(frozen=True, slots=True)
class FileEntry:
    """A single entry in a directory listing."""

    name: str
    path: Path
    is_dir: bool
    size: int
    modified: str


@dataclass(frozen=True, slots=True)
class DirectoryListing:
    """Result of listing a directory."""

    path: Path
    entries: tuple[FileEntry, ...]


@dataclass(frozen=True, slots=True)
class ReadResult:
    """Result of reading a file."""

    path: Path
    content: str
    bytes_read: int


@dataclass(frozen=True, slots=True)
class WriteResult:
    """Result of writing a file."""

    path: Path
    bytes_written: int
    existed: bool


@dataclass(frozen=True, slots=True)
class CreateDirectoryResult:
    """Result of creating a directory."""

    path: Path


@dataclass(frozen=True, slots=True)
class SearchResult:
    """Result of a filename search within an authorized root."""

    query: str
    root: Path
    matches: tuple[Path, ...]
