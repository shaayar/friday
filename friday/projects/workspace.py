"""
Project workspace — the private FRIDAY workspace for a project.

Each registered project gets a directory ``<workspace_root>/<project-id>/``
containing assistant-maintained files:

- ``context.md`` — current working context
- ``facts.md`` — durable verified facts
- ``decisions.md`` — recorded decisions (append-only)
- ``changelog.md`` — change history (append-only)
- ``state.json`` — machine-parseable current state

The workspace lives under the FRIDAY home directory, keyed by the
opaque project ID, and is never confused with the user's actual project
root. All I/O goes through the FileSystemManager capability layer; no
raw filesystem access.
"""

from __future__ import annotations

import contextlib
import json
from pathlib import Path

from friday.filesystem.exceptions import (
    AlreadyExistsError,
    FilesystemError,
    PathNotFoundError,
)
from friday.filesystem.manager import FileSystemManager

_CONTEXT = "context.md"
_FACTS = "facts.md"
_DECISIONS = "decisions.md"
_CHANGELOG = "changelog.md"
_STATE = "state.json"

_SEEDED_FILES = (_CONTEXT, _FACTS, _DECISIONS, _CHANGELOG, _STATE)


class ProjectWorkspace:
    """Manages the private FRIDAY workspace files of a project."""

    def __init__(self, filesystem: FileSystemManager, workspace_root: str | Path) -> None:
        self._fs = filesystem
        self._workspace_root = Path(workspace_root)

    @property
    def workspace_root(self) -> Path:
        return self._workspace_root

    def project_path(self, project_id: str) -> Path:
        """Absolute path of a project's private workspace directory."""
        return self._workspace_root / project_id

    def ensure(self, project_id: str) -> Path:
        """Create the workspace directory and seed its files if missing.

        Idempotent: never overwrites existing workspace content. This is
        the only operation that creates workspace state on disk.
        """
        project_path = self.project_path(project_id)
        with contextlib.suppress(AlreadyExistsError):
            self._fs.create_directory(project_path, parents=True)
        for filename, default in _seed_content():
            self._write_if_missing(project_path / filename, default)
        return project_path

    def read_context(self, project_id: str) -> str:
        return self._read_text(project_id, _CONTEXT)

    def write_context(self, project_id: str, content: str) -> None:
        self._write_text(project_id, _CONTEXT, content)

    def read_facts(self, project_id: str) -> str:
        return self._read_text(project_id, _FACTS)

    def append_fact(self, project_id: str, fact: str) -> None:
        self._append_text(project_id, _FACTS, fact)

    def read_decisions(self, project_id: str) -> str:
        return self._read_text(project_id, _DECISIONS)

    def append_decision(self, project_id: str, decision: str) -> None:
        self._append_text(project_id, _DECISIONS, decision)

    def read_changelog(self, project_id: str) -> str:
        return self._read_text(project_id, _CHANGELOG)

    def append_changelog(self, project_id: str, entry: str) -> None:
        self._append_text(project_id, _CHANGELOG, entry)

    def read_state(self, project_id: str) -> dict:
        raw = self._read_text(project_id, _STATE)
        return json.loads(raw)

    def write_state(self, project_id: str, data: dict) -> None:
        self._write_text(project_id, _STATE, json.dumps(data, indent=2))

    def _read_text(self, project_id: str, filename: str) -> str:
        result = self._fs.read_file(self.project_path(project_id) / filename)
        return result.content

    def _write_text(self, project_id: str, filename: str, content: str) -> None:
        self._fs.write_file(self.project_path(project_id) / filename, content, overwrite=True)

    def _append_text(self, project_id: str, filename: str, text: str) -> None:
        """Bounded append using the existing read/write capabilities."""
        target = self.project_path(project_id) / filename
        try:
            current = self._fs.read_file(target).content
        except PathNotFoundError:
            current = ""
        separator = "" if current == "" else "\n"
        self._fs.write_file(target, current + separator + text, overwrite=True)

    def _write_if_missing(self, path: Path, default: str) -> None:
        try:
            self._fs.read_file(path)
        except PathNotFoundError:
            self._fs.write_file(path, default)
        except FilesystemError:
            # Any other failure (denied, wrong type) is not ours to repair.
            raise


def _seed_content() -> tuple[tuple[str, str], ...]:
    return (
        (_CONTEXT, ""),
        (_FACTS, ""),
        (_DECISIONS, ""),
        (_CHANGELOG, ""),
        (_STATE, "{}"),
    )
