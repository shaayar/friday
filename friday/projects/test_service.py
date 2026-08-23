"""
Tests for ProjectService.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from friday.filesystem.exceptions import RootNotFoundError
from friday.projects.exceptions import ProjectNotFoundError
from friday.projects.models import DETECTED, EXPLICIT
from friday.projects.service import ProjectService, build_project_service


@pytest.fixture
def service(tmp_path: Path) -> ProjectService:
    return build_project_service(tmp_path / "friday")


def test_register_creates_project_and_seeds_workspace(
    service: ProjectService, tmp_path: Path
) -> None:
    root = tmp_path / "project"
    root.mkdir()

    project = service.register(root, name="app")

    assert project.id
    assert project.name == "app"
    workspace_path = service.get_workspace(project.id).project_path(project.id)
    assert workspace_path.is_dir()
    for filename in (
        "context.md",
        "facts.md",
        "decisions.md",
        "changelog.md",
        "state.json",
    ):
        assert (workspace_path / filename).is_file()


def test_register_validates_root_exists(
    service: ProjectService, tmp_path: Path
) -> None:
    with pytest.raises(RootNotFoundError):
        service.register(tmp_path / "missing")


def test_register_duplicate_root_returns_existing(
    service: ProjectService, tmp_path: Path
) -> None:
    root = tmp_path / "project"
    root.mkdir()

    first = service.register(root, name="app")
    second = service.register(root, name="other")

    assert second.id == first.id
    assert second.name == "app"


def test_stable_id_independent_of_name(service: ProjectService, tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()

    project = service.register(root, name="first-name")
    renamed = service.rename(project.id, "new-name")

    assert renamed.id == project.id
    assert renamed.name == "new-name"


def test_rename_keeps_workspace(service: ProjectService, tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    project = service.register(root, name="before")
    service.get_workspace(project.id).write_context(project.id, "valuable")

    service.rename(project.id, "after")

    assert service.get_workspace(project.id).read_context(project.id) == "valuable"


def test_unregister_removes_entry_retains_workspace(
    service: ProjectService, tmp_path: Path
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    project = service.register(root, name="app")
    workspace_path = service.get_workspace(project.id).project_path(project.id)

    service.unregister(project.id)

    assert service.get_project(project.id) is None
    assert workspace_path.is_dir()


def test_list_and_get(service: ProjectService, tmp_path: Path) -> None:
    first_root = tmp_path / "p1"
    first_root.mkdir()
    second_root = tmp_path / "p2"
    second_root.mkdir()
    first = service.register(first_root, name="a")
    second = service.register(second_root, name="b")

    assert {p.id for p in service.list_projects()} == {first.id, second.id}
    assert service.get_project(first.id) is not None
    assert service.get_project("missing") is None


def test_detect(service: ProjectService, tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    service.register(root, name="app")

    detected = service.detect(root / "src" / "components")

    assert detected is not None
    assert detected.project.name == "app"


def test_activate_and_explicit_survives_cwd_change(
    service: ProjectService, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    project = service.register(root, name="app")
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.chdir(outside)

    active = service.activate(project.id)
    assert active.source == EXPLICIT
    assert service.reconcile().project_id == project.id
    assert service.active_project().source == EXPLICIT


def test_clear_active_falls_back_to_detection(
    service: ProjectService, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    project = service.register(root, name="app")
    service.activate(project.id)
    sub = root / "sub"
    sub.mkdir()
    monkeypatch.chdir(sub)

    active = service.clear_active()

    assert active is not None
    assert active.source == DETECTED
    assert active.project_id == project.id


def test_unregister_active_project_falls_back_to_detection(
    service: ProjectService, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    project = service.register(root, name="app")
    service.activate(project.id)
    other_root = tmp_path / "other"
    other_root.mkdir()
    other = service.register(other_root, name="other")
    monkeypatch.chdir(other_root)

    service.unregister(project.id)

    active = service.active_project()
    assert active is not None
    assert active.source == DETECTED
    assert active.project_id == other.id


def test_unknown_project_operations_raise(
    service: ProjectService, tmp_path: Path
) -> None:
    with pytest.raises(ProjectNotFoundError):
        service.activate("missing")
    with pytest.raises(ProjectNotFoundError):
        service.rename("missing", "x")
    with pytest.raises(ProjectNotFoundError):
        service.unregister("missing")
    with pytest.raises(ProjectNotFoundError):
        service.get_workspace("missing")


def test_service_shares_filesystem_composition_root(
    service: ProjectService, tmp_path: Path
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    project = service.register(root, name="app")

    assert service.registry.get(project.id) is not None
    assert service.filesystem_manager is not None
    assert service.policy is not None
