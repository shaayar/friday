"""
Active project — the persisted current-focus pointer and its reconcile
rules.

Precedence: an explicitly activated project is authoritative and
survives CWD changes. CWD detection only drives the active project when
there is no explicit pointer. ``clear()`` drops any explicit pointer and
immediately falls back to CWD detection. An explicitly active project
that is unregistered becomes invalid and is cleared, then falls back to
detection.

The pointer is persisted atomically to ``<storage_path>``.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from friday.filesystem.registry import ProjectRegistry
from friday.projects.detector import ProjectDetector
from friday.projects.exceptions import ProjectNotFoundError
from friday.projects.models import DETECTED, EXPLICIT, ActiveProject


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


class ActiveProjectManager:
    """Owns the persisted active-project pointer and its transitions."""

    def __init__(
        self,
        storage_path: str | Path,
        registry: ProjectRegistry,
        detector: ProjectDetector,
    ) -> None:
        self._storage_path = Path(storage_path)
        self._registry = registry
        self._detector = detector

    def get(self) -> ActiveProject | None:
        """Return the persisted pointer without recomputing it."""
        return self._load()

    def activate(self, project_id: str) -> ActiveProject:
        """Explicitly activate a registered project."""
        if self._registry.get(project_id) is None:
            raise ProjectNotFoundError(f"No registered project with id {project_id!r}")
        return self._set(project_id, EXPLICIT)

    def clear(self, cwd: str | Path | None = None) -> ActiveProject | None:
        """Clear the explicit pointer, then fall back to CWD detection."""
        self._save(None)
        return self._reconcile_detected(cwd)

    def reconcile(self, cwd: str | Path | None = None) -> ActiveProject | None:
        """Recompute the active project per the precedence rules."""
        active = self._load()
        if active is not None and active.source == EXPLICIT:
            if self._registry.contains(active.project_id):
                return active
            # Explicit project became invalid: clear, fall through.
            active = None
        return self._reconcile_detected(cwd)

    def _reconcile_detected(self, cwd: str | Path | None) -> ActiveProject | None:
        detected = self._detector.detect(cwd)
        if detected is None:
            self._save(None)
            return None
        return self._set(detected.project.id, DETECTED)

    def _set(self, project_id: str, source: str) -> ActiveProject:
        active = ActiveProject(project_id=project_id, source=source, updated_at=_utc_now())
        self._save(active)
        return active

    def _load(self) -> ActiveProject | None:
        if not self._storage_path.exists():
            return None
        try:
            raw = json.loads(self._storage_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not raw:
            return None
        return ActiveProject(
            project_id=raw["project_id"],
            source=raw["source"],
            updated_at=raw["updated_at"],
        )

    def _save(self, active: ActiveProject | None) -> None:
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        payload = (
            {
                "project_id": active.project_id,
                "source": active.source,
                "updated_at": active.updated_at,
            }
            if active is not None
            else {}
        )
        tmp = self._storage_path.with_name(self._storage_path.name + ".tmp")
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
        os.replace(tmp, self._storage_path)