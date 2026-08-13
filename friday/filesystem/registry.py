"""
Project-root registry — explicit, persistent grants for external roots.

External project directories are never accessible implicitly. A root must
be registered by the host before the filesystem capability may touch it.
The assistant cannot register or revoke grants through MCP tools; the
registry only persists grants that the host authorizes.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

from friday.filesystem.exceptions import (
    GrantNotFoundError,
    RegistryCorruptError,
    RootNotFoundError,
)
from friday.filesystem.models import READ_PERMISSION, WRITE_PERMISSION, Grant

_KNOWN_PERMISSIONS = frozenset({READ_PERMISSION, WRITE_PERMISSION})


def default_storage_path() -> Path:
    """Default registry file inside the trusted workspace."""
    return Path.home() / ".friday" / "project_roots.json"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


class ProjectRootRegistry:
    """Stores and persists grants for authorized external project roots."""

    def __init__(self, storage_path: str | Path | None = None) -> None:
        self._storage_path = Path(storage_path) if storage_path is not None else default_storage_path()
        self._grants: dict[str, Grant] = {}
        self._load()

    def register(
        self,
        root: str | Path,
        *,
        label: str | None = None,
        permissions: tuple[str, ...] | None = None,
        grant_id: str | None = None,
    ) -> Grant:
        """Register an existing directory as an authorized root."""
        try:
            resolved_root = Path(root).expanduser().resolve(strict=True)
        except OSError as exc:
            raise RootNotFoundError(f"Root does not exist or is not a directory: {root}") from exc
        if not resolved_root.is_dir():
            raise RootNotFoundError(f"Root does not exist or is not a directory: {resolved_root}")

        grant_permissions = (
            frozenset(permissions) if permissions is not None else frozenset({READ_PERMISSION, WRITE_PERMISSION})
        )
        unknown = grant_permissions - _KNOWN_PERMISSIONS
        if unknown:
            raise ValueError(f"Unknown permissions: {sorted(unknown)}")

        gid = grant_id if grant_id is not None else uuid.uuid4().hex[:12]
        grant = Grant(
            id=gid,
            root=resolved_root,
            label=label or str(resolved_root),
            permissions=frozenset(grant_permissions),
            created_at=_utc_now(),
        )
        self._grants[gid] = grant
        self._save()
        return grant

    def revoke(self, grant_id: str) -> None:
        """Revoke a previously registered grant."""
        if grant_id not in self._grants:
            raise GrantNotFoundError(f"No grant with id {grant_id!r}")
        del self._grants[grant_id]
        self._save()

    def get(self, grant_id: str) -> Grant | None:
        return self._grants.get(grant_id)

    def list_grants(self) -> list[Grant]:
        return list(self._grants.values())

    def grant_containing(self, resolved_path: Path) -> Grant | None:
        """Return the first grant whose resolved root contains `resolved_path`."""
        for grant in self._grants.values():
            if resolved_path.is_relative_to(grant.root):
                return grant
        return None

    def _load(self) -> None:
        if not self._storage_path.exists():
            return
        try:
            payload = json.loads(self._storage_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RegistryCorruptError(f"Cannot read registry file {self._storage_path}: {exc}") from exc

        for raw in payload.get("grants", {}).values():
            grant = Grant(
                id=raw["id"],
                root=Path(raw["root"]),
                label=raw["label"],
                permissions=frozenset(raw["permissions"]),
                created_at=raw["created_at"],
            )
            self._grants[grant.id] = grant

    def _save(self) -> None:
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "grants": {
                grant.id: {
                    "id": grant.id,
                    "root": str(grant.root),
                    "label": grant.label,
                    "permissions": sorted(grant.permissions),
                    "created_at": grant.created_at,
                }
                for grant in self._grants.values()
            }
        }
        tmp = self._storage_path.with_name(self._storage_path.name + ".tmp")
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
        os.replace(tmp, self._storage_path)
