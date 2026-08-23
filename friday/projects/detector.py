"""
Project detector — read-only current-working-directory detection.

Detection determines whether the current working directory belongs to a
registered project using the most specific (longest) matching root.
It is a convenience/discovery mechanism only: it never registers unknown
directories and never creates any workspace state.
"""

from __future__ import annotations

from pathlib import Path

from friday.filesystem.registry import ProjectRegistry
from friday.projects.models import DetectedProject


class ProjectDetector:
    """Resolves a working directory to a registered project, or None."""

    def __init__(self, registry: ProjectRegistry) -> None:
        self._registry = registry

    def detect(self, cwd: str | Path | None = None) -> DetectedProject | None:
        """Return the registered project containing `cwd`, or None.

        `cwd` defaults to the process working directory. The path is
        resolved before matching. Longest registered root wins.
        """
        resolved = (
            Path(cwd).expanduser().resolve(strict=False)
            if cwd is not None
            else Path.cwd().resolve()
        )
        project = self._registry.project_containing(resolved)
        if project is None:
            return None
        return DetectedProject(project=project, cwd=resolved)
