"""
Project registry — explicit, persistent project identity + authorization.

A registered project is both the durable project identity and an
explicit authorization grant for its external root. External project
directories are never accessible implicitly; a project must be
registered by the host before the filesystem capability may touch its
root. The assistant cannot register or revoke projects through MCP
tools; the registry only persists grants that the host authorizes.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

from friday.filesystem.exceptions import (
    GrantNotFoundError,
    RegistryCorruptError,
    RootNotFoundError,
)
from friday.filesystem.models import READ_PERMISSION, WRITE_PERMISSION, Project

_KNOWN_PERMISSIONS = frozenset({READ_PERMISSION, WRITE_PERMISSION})


def default_storage_path() -> Path:
    """Default registry file inside the trusted workspace."""
    return Path.home() / ".friday" / "project_roots.json"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


class ProjectRegistry:
    """Stores and persists registered projects and their authorized roots."""

    def __init__(self, storage_path: str | Path | None = None) -> None:
        self._storage_path = (
            Path(storage_path) if storage_path is not None else default_storage_path()
        )
        self._projects: dict[str, Project] = {}
        self._load()

    def register(
        self,
        root: str | Path,
        *,
        name: str | None = None,
        permissions: tuple[str, ...] | None = None,
        project_id: str | None = None,
    ) -> Project:
        """Register an existing directory as a project root."""
        try:
            resolved_root = Path(root).expanduser().resolve(strict=True)
        except OSError as exc:
            raise RootNotFoundError(f"Root does not exist or is not a directory: {root}") from exc
        if not resolved_root.is_dir():
            raise RootNotFoundError(f"Root does not exist or is not a directory: {resolved_root}")

        grant_permissions = (
            frozenset(permissions)
            if permissions is not None
            else frozenset({READ_PERMISSION, WRITE_PERMISSION})
        )
        unknown = grant_permissions - _KNOWN_PERMISSIONS
        if unknown:
            raise ValueError(f"Unknown permissions: {sorted(unknown)}")

        pid = project_id if project_id is not None else uuid.uuid4().hex[:12]
        project = Project(
            id=pid,
            root=resolved_root,
            name=name or str(resolved_root),
            permissions=frozenset(grant_permissions),
            created_at=_utc_now(),
        )
        self._projects[pid] = project
        self._save()
        return project

    def revoke(self, project_id: str) -> None:
        """Revoke a previously registered project."""
        if project_id not in self._projects:
            raise GrantNotFoundError(f"No project with id {project_id!r}")
        del self._projects[project_id]
        self._save()

    def rename(self, project_id: str, new_name: str) -> Project:
        """Change a project's display name without touching its identity
        or stored workspace."""
        project = self._projects.get(project_id)
        if project is None:
            raise GrantNotFoundError(f"No project with id {project_id!r}")
        renamed = Project(
            id=project.id,
            root=project.root,
            name=new_name,
            permissions=project.permissions,
            created_at=project.created_at,
        )
        self._projects[project_id] = renamed
        self._save()
        return renamed

    def get(self, project_id: str) -> Project | None:
        return self._projects.get(project_id)

    def contains(self, project_id: str) -> bool:
        return project_id in self._projects

    def list_projects(self) -> list[Project]:
        return list(self._projects.values())

    def project_containing(self, resolved_path: Path) -> Project | None:
        """Return the project whose root most specifically contains `resolved_path`.

        When multiple registered roots contain the path, the longest
        (most specific) root wins. This makes nested or overlapping
        project registrations resolve to the deepest match.
        """
        best: Project | None = None
        for project in self._projects.values():
            if not resolved_path.is_relative_to(project.root):
                continue
            if best is None or len(project.root.parts) > len(best.root.parts):
                best = project
        return best

    def _load(self) -> None:
        if not self._storage_path.exists():
            return
        try:
            payload = json.loads(self._storage_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RegistryCorruptError(
                f"Cannot read registry file {self._storage_path}: {exc}"
            ) from exc

        # Accept both the current ("projects") and legacy ("grants") payload keys.
        entries = payload.get("projects") or payload.get("grants") or {}
        for raw in entries.values():
            # Accept both the current ("name") and legacy ("label") display fields.
            project = Project(
                id=raw["id"],
                root=Path(raw["root"]),
                name=raw.get("name") or raw.get("label") or str(raw["root"]),
                permissions=frozenset(raw["permissions"]),
                created_at=raw["created_at"],
            )
            self._projects[project.id] = project

    def _save(self) -> None:
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "projects": {
                project.id: {
                    "id": project.id,
                    "root": str(project.root),
                    "name": project.name,
                    "permissions": sorted(project.permissions),
                    "created_at": project.created_at,
                }
                for project in self._projects.values()
            }
        }
        tmp = self._storage_path.with_name(self._storage_path.name + ".tmp")
        with tmp.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
        tmp.replace(self._storage_path)
