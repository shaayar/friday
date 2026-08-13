"""
Path policy — resolution and authorization of filesystem access.

Every filesystem operation must pass through this policy before any I/O.

Authorization is deny-by-default: a path is allowed only if its resolved
location is contained within the trusted workspace root or within a
registered external root whose grant permits the requested operation.

Relative paths are accepted when they resolve to a location inside an
authorized root; resolution is anchored at the current working directory.

Guarantee: the requested path is resolved exactly once. The manager
performs I/O on that same resolved Path, which reliably prevents ``..``
traversal and symlink escapes in the normal case. This does NOT protect
against a TOCTOU race in which the filesystem is mutated between
authorization and I/O. For a local, single-user assistant this is an
accepted limitation; fully race-proof access would require OS-level
sandboxing.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from friday.filesystem.exceptions import PathDeniedError, PermissionDeniedError

if TYPE_CHECKING:
    from friday.filesystem.registry import ProjectRootRegistry


@dataclass(frozen=True, slots=True)
class ResolvedAccess:
    """The outcome of an authorization decision."""

    path: Path
    root: Path
    permission: str


def resolve_path(path: str | Path) -> Path:
    """Normalize a requested path to an absolute, symlink-resolved Path."""
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    return candidate.resolve(strict=False)


class PathPolicy:
    """Resolves and authorizes paths against permitted roots."""

    def __init__(self, workspace_root: str | Path, registry: ProjectRootRegistry) -> None:
        self._workspace_root = resolve_path(workspace_root)
        self._registry = registry

    @property
    def workspace_root(self) -> Path:
        return self._workspace_root

    def authorize(self, requested: str | Path, permission: str) -> ResolvedAccess:
        """Resolve `requested` and return a ResolvedAccess, or raise."""
        resolved = resolve_path(requested)

        if resolved.is_relative_to(self._workspace_root):
            return ResolvedAccess(path=resolved, root=self._workspace_root, permission=permission)

        grant = self._registry.grant_containing(resolved)
        if grant is None:
            raise PathDeniedError(f"Path is not contained within any authorized root: {resolved}")
        if not grant.allows(permission):
            raise PermissionDeniedError(
                f"Root {grant.root} does not grant permission {permission!r} for path {resolved}"
            )
        return ResolvedAccess(path=resolved, root=grant.root, permission=permission)
