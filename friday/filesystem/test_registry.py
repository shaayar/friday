"""
Tests for ProjectRootRegistry.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from friday.filesystem.exceptions import GrantNotFoundError, RootNotFoundError
from friday.filesystem.models import READ_PERMISSION, WRITE_PERMISSION
from friday.filesystem.registry import ProjectRootRegistry


@pytest.fixture
def storage(tmp_path: Path) -> Path:
    return tmp_path / "registry.json"


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    return root


def test_register(storage: Path, project_root: Path) -> None:
    registry = ProjectRootRegistry(storage)
    grant = registry.register(project_root, label="my-project")

    assert grant.id
    assert grant.root == project_root.resolve()
    assert grant.label == "my-project"
    assert grant.permissions == frozenset({READ_PERMISSION, WRITE_PERMISSION})
    assert registry.get(grant.id) is grant


def test_register_explicit_permissions(storage: Path, project_root: Path) -> None:
    registry = ProjectRootRegistry(storage)
    grant = registry.register(project_root, permissions=("read",))
    assert grant.permissions == frozenset({READ_PERMISSION})


def test_register_unknown_permission_rejected(storage: Path, project_root: Path) -> None:
    registry = ProjectRootRegistry(storage)
    with pytest.raises(ValueError):
        registry.register(project_root, permissions=("delete",))


def test_persistence(storage: Path, project_root: Path) -> None:
    registry = ProjectRootRegistry(storage)
    grant = registry.register(project_root, label="persisted")

    reloaded = ProjectRootRegistry(storage)
    restored = reloaded.get(grant.id)
    assert restored is not None
    assert restored.root == grant.root
    assert restored.label == "persisted"
    assert restored.permissions == grant.permissions


def test_listing(storage: Path, project_root: Path, tmp_path: Path) -> None:
    registry = ProjectRootRegistry(storage)
    other = tmp_path / "other"
    other.mkdir()
    first = registry.register(project_root)
    second = registry.register(other)

    grants = registry.list_grants()
    assert [g.id for g in grants] == [first.id, second.id]


def test_revoke(storage: Path, project_root: Path) -> None:
    registry = ProjectRootRegistry(storage)
    grant = registry.register(project_root)
    registry.revoke(grant.id)

    assert registry.get(grant.id) is None
    assert registry.list_grants() == []


def test_revoke_persists(storage: Path, project_root: Path) -> None:
    registry = ProjectRootRegistry(storage)
    grant = registry.register(project_root)
    registry.revoke(grant.id)

    reloaded = ProjectRootRegistry(storage)
    assert reloaded.list_grants() == []


def test_revoke_unknown_raises(storage: Path, project_root: Path) -> None:
    registry = ProjectRootRegistry(storage)
    registry.register(project_root)
    with pytest.raises(GrantNotFoundError):
        registry.revoke("does-not-exist")


def test_register_nonexistent_root(storage: Path, tmp_path: Path) -> None:
    registry = ProjectRootRegistry(storage)
    with pytest.raises(RootNotFoundError):
        registry.register(tmp_path / "missing")


def test_register_file_as_root(storage: Path, tmp_path: Path) -> None:
    registry = ProjectRootRegistry(storage)
    a_file = tmp_path / "file.txt"
    a_file.write_text("x")
    with pytest.raises(RootNotFoundError):
        registry.register(a_file)


def test_grant_containing(storage: Path, project_root: Path) -> None:
    registry = ProjectRootRegistry(storage)
    grant = registry.register(project_root)
    (project_root / "sub").mkdir()

    assert registry.grant_containing(project_root) is grant
    assert registry.grant_containing(project_root / "sub" / "a.txt") is grant
    assert registry.grant_containing(Path("/unrelated/path")) is None
