"""
Filesystem manager — deterministic filesystem operations behind the policy
boundary.

The manager is transport-free. It orchestrates authorization through the
PathPolicy and performs I/O on the exact resolved path returned by the
policy. It never touches MCP, LiveKit, or any LLM code.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from friday.filesystem.exceptions import (
    AlreadyExistsError,
    IsDirectoryError,
    LimitError,
    NotDirectoryError,
    PathNotFoundError,
)
from friday.filesystem.models import (
    READ_PERMISSION,
    WRITE_PERMISSION,
    CreateDirectoryResult,
    DirectoryListing,
    FileEntry,
    ReadResult,
    SearchResult,
    WriteResult,
)
from friday.filesystem.policy import PathPolicy

DEFAULT_READ_LIMIT_BYTES = 1_000_000
DEFAULT_WRITE_LIMIT_BYTES = 1_000_000
DEFAULT_LIST_LIMIT = 500
DEFAULT_SEARCH_MAX_RESULTS = 100
DEFAULT_SEARCH_MAX_DEPTH = 5


def _format_timestamp(value: float) -> str:
    return datetime.fromtimestamp(value, tz=UTC).isoformat(timespec="seconds")


class FileSystemManager:
    """Authorized filesystem operations."""

    def __init__(
        self,
        policy: PathPolicy,
        *,
        read_limit_bytes: int = DEFAULT_READ_LIMIT_BYTES,
        write_limit_bytes: int = DEFAULT_WRITE_LIMIT_BYTES,
        list_limit: int = DEFAULT_LIST_LIMIT,
        search_max_results: int = DEFAULT_SEARCH_MAX_RESULTS,
        search_max_depth: int = DEFAULT_SEARCH_MAX_DEPTH,
    ) -> None:
        self._policy = policy
        self._read_limit_bytes = read_limit_bytes
        self._write_limit_bytes = write_limit_bytes
        self._list_limit = list_limit
        self._search_max_results = search_max_results
        self._search_max_depth = search_max_depth

    def read_file(self, path: str | Path, *, encoding: str = "utf-8") -> ReadResult:
        """Read a text file inside an authorized root."""
        access = self._policy.authorize(path, READ_PERMISSION)
        target = access.path
        if not target.exists():
            raise PathNotFoundError(f"No such file: {target}")
        if target.is_dir():
            raise IsDirectoryError(f"Path is a directory, not a file: {target}")

        stat = target.stat()
        if stat.st_size > self._read_limit_bytes:
            raise LimitError(
                f"File exceeds read limit of {self._read_limit_bytes} bytes: "
                f"{target} ({stat.st_size} bytes)"
            )

        content = target.read_text(encoding=encoding)
        return ReadResult(path=target, content=content, bytes_read=len(content.encode(encoding)))

    def write_file(
        self,
        path: str | Path,
        content: str,
        *,
        overwrite: bool = False,
        encoding: str = "utf-8",
    ) -> WriteResult:
        """Write a text file inside an authorized root.

        Never overwrites an existing file unless `overwrite` is True.
        Never creates parent directories; the parent must already exist.
        """
        access = self._policy.authorize(path, WRITE_PERMISSION)
        target = access.path

        existed = target.exists()
        if existed and not overwrite:
            raise AlreadyExistsError(f"File already exists and overwrite is disabled: {target}")
        if target.is_dir():
            raise IsDirectoryError(f"Path is a directory, not a file: {target}")

        data = content.encode(encoding)
        if len(data) > self._write_limit_bytes:
            raise LimitError(
                f"Content exceeds write limit of {self._write_limit_bytes} bytes "
                f"({len(data)} bytes)"
            )

        parent = target.parent
        if not parent.is_dir():
            raise NotDirectoryError(f"Parent directory does not exist: {parent}")

        target.write_bytes(data)
        return WriteResult(path=target, bytes_written=len(data), existed=existed)

    def create_directory(self, path: str | Path, *, parents: bool = False) -> CreateDirectoryResult:
        """Create a directory inside an authorized root.

        Requires write permission on the matched root. Like ``write_file``,
        the parent must already exist unless ``parents`` is True. Never
        overwrites an existing directory.
        """
        access = self._policy.authorize(path, WRITE_PERMISSION)
        target = access.path

        if target.exists():
            if target.is_dir():
                raise AlreadyExistsError(f"Directory already exists: {target}")
            raise NotDirectoryError(f"Path exists but is not a directory: {target}")
        if not parents and not target.parent.is_dir():
            raise NotDirectoryError(f"Parent directory does not exist: {target.parent}")

        target.mkdir(parents=parents)
        return CreateDirectoryResult(path=target)

    def list_directory(self, path: str | Path) -> DirectoryListing:
        """List entries inside an authorized directory."""
        access = self._policy.authorize(path, READ_PERMISSION)
        target = access.path
        if not target.exists():
            raise PathNotFoundError(f"No such directory: {target}")
        if not target.is_dir():
            raise NotDirectoryError(f"Path is not a directory: {target}")

        entries: list[FileEntry] = []
        for child in sorted(target.iterdir(), key=lambda p: p.name):
            try:
                stat = child.stat()
            except OSError:
                continue
            entries.append(
                FileEntry(
                    name=child.name,
                    path=child,
                    is_dir=child.is_dir(),
                    size=stat.st_size,
                    modified=_format_timestamp(stat.st_mtime),
                )
            )
            if len(entries) > self._list_limit:
                raise LimitError(
                    f"Directory exceeds listing limit of {self._list_limit} entries: {target}"
                )
        return DirectoryListing(path=target, entries=tuple(entries))

    def search_files(
        self,
        path: str | Path,
        pattern: str,
        *,
        max_depth: int | None = None,
        max_results: int | None = None,
    ) -> SearchResult:
        """Search file names by regex within an authorized root.

        The search requires read permission, is bounded by the configured
        depth and result limits, and never follows directory symlinks that
        resolve outside the authorized root.
        """
        access = self._policy.authorize(path, READ_PERMISSION)
        root = access.path
        if not root.exists():
            raise PathNotFoundError(f"No such directory: {root}")
        if not root.is_dir():
            raise NotDirectoryError(f"Path is not a directory: {root}")

        depth_limit = (
            self._search_max_depth if max_depth is None else min(max_depth, self._search_max_depth)
        )
        result_limit = (
            self._search_max_results
            if max_results is None
            else min(max_results, self._search_max_results)
        )

        regex = re.compile(pattern)
        matches: list[Path] = []
        self._walk(root, root, regex, 0, depth_limit, result_limit, matches)
        return SearchResult(query=pattern, root=root, matches=tuple(matches))

    def _walk(
        self,
        root: Path,
        directory: Path,
        regex: re.Pattern[str],
        depth: int,
        depth_limit: int,
        result_limit: int,
        matches: list[Path],
    ) -> None:
        if depth > depth_limit:
            return
        try:
            children = sorted(directory.iterdir(), key=lambda p: p.name)
        except OSError:
            return
        for child in children:
            try:
                real = child.resolve(strict=False)
            except OSError:
                continue
            if not real.is_relative_to(root):
                continue
            try:
                if real.is_dir():
                    self._walk(root, real, regex, depth + 1, depth_limit, result_limit, matches)
                elif real.is_file() and regex.search(real.name):
                    matches.append(real)
                    if len(matches) > result_limit:
                        raise LimitError(f"Search exceeded result limit of {result_limit} matches")
            except OSError:
                continue
