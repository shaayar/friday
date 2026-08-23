"""
Tests for ProjectRegistry.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from friday.filesystem.exceptions import (
    GrantNotFoundError,
    RegistryCorruptError,
    RootNotFoundError,
)
from friday.filesystem.models import READ_PERMISSION, WRITE_PERMISSION
from friday.filesystem.registry import ProjectRegistry


@pytest.fixture
def storage(tmp_path: Path) -> Path:
    return tmp_path / "registry.json"


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    return root


def test_register(storage: Path, project_root: Path) -> None:
    registry = ProjectRegistry(storage)
    project = registry.register(project_root, name="my-project")

    assert project.id
    assert project.root == project_root.resolve()
    assert project.name == "my-project"
    assert project.permissions == frozenset({READ_PERMISSION, WRITE_PERMISSION})
    assert registry.get(project.id) is project


def test_register_explicit_permissions(storage: Path, project_root: Path) -> None:
    registry = ProjectRegistry(storage)
    project = registry.register(project_root, permissions=("read",))
    assert project.permissions == frozenset({READ_PERMISSION})


def test_register_unknown_permission_rejected(
    storage: Path, project_root: Path
) -> None:
    registry = ProjectRegistry(storage)
    with pytest.raises(ValueError):
        registry.register(project_root, permissions=("delete",))


def test_persistence(storage: Path, project_root: Path) -> None:
    registry = ProjectRegistry(storage)
    project = registry.register(project_root, name="persisted")

    reloaded = ProjectRegistry(storage)
    restored = reloaded.get(project.id)
    assert restored is not None
    assert restored.root == project.root
    assert restored.name == "persisted"
    assert restored.permissions == project.permissions


def test_listing(storage: Path, project_root: Path, tmp_path: Path) -> None:
    registry = ProjectRegistry(storage)
    other = tmp_path / "other"
    other.mkdir()
    first = registry.register(project_root)
    second = registry.register(other)

    projects = registry.list_projects()
    assert [p.id for p in projects] == [first.id, second.id]


def test_revoke(storage: Path, project_root: Path) -> None:
    registry = ProjectRegistry(storage)
    project = registry.register(project_root)
    registry.revoke(project.id)

    assert registry.get(project.id) is None
    assert registry.list_projects() == []


def test_revoke_persists(storage: Path, project_root: Path) -> None:
    registry = ProjectRegistry(storage)
    project = registry.register(project_root)
    registry.revoke(project.id)

    reloaded = ProjectRegistry(storage)
    assert reloaded.list_projects() == []


def test_revoke_unknown_raises(storage: Path, project_root: Path) -> None:
    registry = ProjectRegistry(storage)
    registry.register(project_root)
    with pytest.raises(GrantNotFoundError):
        registry.revoke("does-not-exist")


def test_register_nonexistent_root(storage: Path, tmp_path: Path) -> None:
    registry = ProjectRegistry(storage)
    with pytest.raises(RootNotFoundError):
        registry.register(tmp_path / "missing")


def test_register_file_as_root(storage: Path, tmp_path: Path) -> None:
    registry = ProjectRegistry(storage)
    a_file = tmp_path / "file.txt"
    a_file.write_text("x")
    with pytest.raises(RootNotFoundError):
        registry.register(a_file)


def test_project_containing(storage: Path, project_root: Path) -> None:
    registry = ProjectRegistry(storage)
    project = registry.register(project_root)
    (project_root / "sub").mkdir()

    assert registry.project_containing(project_root) is project
    assert registry.project_containing(project_root / "sub" / "a.txt") is project
    assert registry.project_containing(Path("/unrelated/path")) is None


def test_project_containing_prefers_longest_match(
    storage: Path, project_root: Path
) -> None:
    registry = ProjectRegistry(storage)
    outer = registry.register(project_root)
    (project_root / "sub").mkdir()
    inner = registry.register(project_root / "sub")

    assert (
        registry.project_containing(project_root / "sub" / "deep" / "file.txt") is inner
    )
    assert registry.project_containing(project_root / "other") is outer
    assert registry.project_containing(project_root / "sub") is inner


def test_rename(storage: Path, project_root: Path) -> None:
    registry = ProjectRegistry(storage)
    project = registry.register(project_root, name="before")
    registry.rename(project.id, "after")

    renamed = registry.get(project.id)
    assert renamed is not None
    assert renamed.name == "after"
    assert renamed.id == project.id
    assert renamed.root == project.root


def test_contains(storage: Path, project_root: Path) -> None:
    registry = ProjectRegistry(storage)
    project = registry.register(project_root)
    assert registry.contains(project.id) is True
    assert registry.contains("missing") is False


def test_corrupt_registry_raises(storage: Path, project_root: Path) -> None:
    storage.write_text("{ not valid json ")

    with pytest.raises(RegistryCorruptError):
        ProjectRegistry(storage)


def test_loads_legacy_grant_schema(storage: Path, project_root: Path) -> None:
    legacy = {
        "grants": {
            "legacy1": {
                "id": "legacy1",
                "root": str(project_root.resolve()),
                "label": "old-name",
                "permissions": ["read", "write"],
                "created_at": "2026-01-01T00:00:00+00:00",
            }
        }
    }
    storage.write_text(json.dumps(legacy))

    registry = ProjectRegistry(storage)
    project = registry.get("legacy1")
    assert project is not None
    assert project.name == "old-name"
    assert project.root == project_root.resolve()
