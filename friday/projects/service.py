"""
ProjectService — the single public API of the project subsystem.

Registration, CWD detection, active-project focus, reconciliation, and
workspace access all flow through this facade. The service also acts as
the shared composition root: one registry / policy / filesystem-manager
construction is reused by the filesystem tools and the project layer so
authorization and project identity never drift.
"""

from __future__ import annotations

from pathlib import Path

from friday.config import config
from friday.filesystem.exceptions import GrantNotFoundError
from friday.filesystem.manager import FileSystemManager
from friday.filesystem.models import Project
from friday.filesystem.policy import PathPolicy
from friday.filesystem.registry import ProjectRegistry
from friday.projects.active import ActiveProjectManager
from friday.projects.detector import ProjectDetector
from friday.projects.exceptions import ProjectNotFoundError
from friday.projects.models import ActiveProject, DetectedProject
from friday.projects.workspace import ProjectWorkspace


def _build_filesystem(
    friday_home: Path, registry_path: Path | None
) -> tuple[ProjectRegistry, PathPolicy, FileSystemManager]:
    registry = ProjectRegistry(registry_path or friday_home / "project_roots.json")
    policy = PathPolicy(workspace_root=friday_home, registry=registry)
    manager = FileSystemManager(
        policy,
        read_limit_bytes=config.FILESYSTEM_READ_LIMIT_BYTES,
        write_limit_bytes=config.FILESYSTEM_WRITE_LIMIT_BYTES,
        list_limit=config.FILESYSTEM_LIST_LIMIT,
        search_max_results=config.FILESYSTEM_SEARCH_MAX_RESULTS,
        search_max_depth=config.FILESYSTEM_SEARCH_MAX_DEPTH,
    )
    return registry, policy, manager


def build_filesystem_manager(
    friday_home: str | Path | None = None, *, registry_path: str | Path | None = None
) -> FileSystemManager:
    """Build the shared filesystem manager for the trusted workspace.

    Intended for the filesystem tool adapter so it shares the same
    registry/policy/manager graph as the project service.
    """
    home = Path(friday_home) if friday_home is not None else config.FRIDAY_HOME
    _, _, manager = _build_filesystem(home, Path(registry_path) if registry_path else None)
    return manager


def build_project_service(
    friday_home: str | Path | None = None, *, registry_path: str | Path | None = None
) -> ProjectService:
    """Compose a fully-wired ProjectService from FRIDAY home paths."""
    home = Path(friday_home) if friday_home is not None else config.FRIDAY_HOME
    registry, policy, manager = _build_filesystem(
        home, Path(registry_path) if registry_path else None
    )
    detector = ProjectDetector(registry)
    active = ActiveProjectManager(home / "active_project.json", registry, detector)
    workspace = ProjectWorkspace(manager, home / "projects")
    return ProjectService(
        registry=registry,
        policy=policy,
        filesystem=manager,
        detector=detector,
        active=active,
        workspace=workspace,
    )


class ProjectService:
    """Single public entry point for the project workspace subsystem."""

    def __init__(
        self,
        *,
        registry: ProjectRegistry,
        policy: PathPolicy,
        filesystem: FileSystemManager,
        detector: ProjectDetector,
        active: ActiveProjectManager,
        workspace: ProjectWorkspace,
    ) -> None:
        self._registry = registry
        self._policy = policy
        self._filesystem = filesystem
        self._detector = detector
        self._active = active
        self._workspace = workspace

    @property
    def registry(self) -> ProjectRegistry:
        return self._registry

    @property
    def policy(self) -> PathPolicy:
        return self._policy

    @property
    def filesystem_manager(self) -> FileSystemManager:
        return self._filesystem

    def register(
        self,
        root: str | Path,
        *,
        name: str | None = None,
        permissions: tuple[str, ...] | None = None,
    ) -> Project:
        """Explicitly register a project root and seed its workspace.

        Registering an already-registered root returns the existing
        project (idempotent).
        """
        existing = self._project_with_root(root)
        if existing is not None:
            return existing
        project = self._registry.register(root, name=name, permissions=permissions)
        self._workspace.ensure(project.id)
        return project

    def rename(self, project_id: str, new_name: str) -> Project:
        """Rename a project's display name; identity and workspace are unchanged."""
        try:
            return self._registry.rename(project_id, new_name)
        except GrantNotFoundError as exc:
            raise ProjectNotFoundError(f"No registered project with id {project_id!r}") from exc

    def unregister(self, project_id: str) -> None:
        """Remove a project from the registry.

        The private workspace is retained on disk. If the removed project
        was explicitly active, the pointer is cleared immediately and the
        active project falls back to CWD detection.
        """
        try:
            self._registry.revoke(project_id)
        except GrantNotFoundError as exc:
            raise ProjectNotFoundError(f"No registered project with id {project_id!r}") from exc
        self._active.reconcile()

    def list_projects(self) -> list[Project]:
        return self._registry.list_projects()

    def get_project(self, project_id: str) -> Project | None:
        return self._registry.get(project_id)

    def detect(self, cwd: str | Path | None = None) -> DetectedProject | None:
        """Detect which registered project contains `cwd` (read-only)."""
        return self._detector.detect(cwd)

    def activate(self, project_id: str) -> ActiveProject:
        """Explicitly activate a registered project."""
        return self._active.activate(project_id)

    def clear_active(self, cwd: str | Path | None = None) -> ActiveProject | None:
        """Clear the explicit active project, falling back to CWD detection."""
        return self._active.clear(cwd)

    def active_project(self) -> ActiveProject | None:
        return self._active.get()

    def reconcile(self, cwd: str | Path | None = None) -> ActiveProject | None:
        """Recompute the active project per the precedence rules."""
        return self._active.reconcile(cwd)

    def get_workspace(self, project_id: str) -> ProjectWorkspace:
        """Return the private workspace handle for a registered project."""
        if self._registry.get(project_id) is None:
            raise ProjectNotFoundError(f"No registered project with id {project_id!r}")
        return self._workspace

    def _project_with_root(self, root: str | Path) -> Project | None:
        try:
            resolved = Path(root).expanduser().resolve(strict=True)
        except OSError:
            return None
        for project in self._registry.list_projects():
            if project.root == resolved:
                return project
        return None
