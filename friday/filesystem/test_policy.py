"""
Tests for PathPolicy authorization.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from friday.filesystem.exceptions import PathDeniedError, PermissionDeniedError
from friday.filesystem.policy import PathPolicy
from friday.filesystem.registry import ProjectRegistry


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    root.mkdir()
    return root


@pytest.fixture
def external(tmp_path: Path) -> Path:
    root = tmp_path / "external"
    root.mkdir()
    return root


@pytest.fixture
def registry(tmp_path: Path) -> ProjectRegistry:
    return ProjectRegistry(tmp_path / "registry.json")


@pytest.fixture
def policy(workspace: Path, registry: ProjectRegistry) -> PathPolicy:
    return PathPolicy(workspace_root=workspace, registry=registry)


def test_authorized_workspace_path(policy: PathPolicy, workspace: Path) -> None:
    access = policy.authorize(workspace / "a" / "b.txt", "read")
    assert access.path == (workspace / "a" / "b.txt").resolve()
    assert access.root == workspace.resolve()


def test_authorized_external_root(
    policy: PathPolicy, registry: ProjectRegistry, external: Path
) -> None:
    registry.register(external, permissions=("read", "write"))
    access = policy.authorize(external / "doc.txt", "read")
    assert access.path == (external / "doc.txt").resolve()
    assert access.root == external.resolve()


def test_unauthorized_path(policy: PathPolicy, tmp_path: Path) -> None:
    with pytest.raises(PathDeniedError):
        policy.authorize(tmp_path / "outside.txt", "read")


def test_parent_traversal_denied(policy: PathPolicy, workspace: Path) -> None:
    (workspace / "sub").mkdir()
    evil = workspace / "sub" / ".." / ".." / "leak.txt"
    with pytest.raises(PathDeniedError):
        policy.authorize(evil, "read")


def test_symlink_escape_denied(policy: PathPolicy, workspace: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret")
    link = workspace / "escape"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks not supported on this platform")
    with pytest.raises(PathDeniedError):
        policy.authorize(link / "secret.txt", "read")


def test_read_only_grant_rejects_write(
    policy: PathPolicy, registry: ProjectRegistry, external: Path
) -> None:
    registry.register(external, permissions=("read",))
    with pytest.raises(PermissionDeniedError):
        policy.authorize(external / "doc.txt", "write")


def test_write_grant_allows_write(
    policy: PathPolicy, registry: ProjectRegistry, external: Path
) -> None:
    registry.register(external, permissions=("read", "write"))
    access = policy.authorize(external / "doc.txt", "write")
    assert access.path == (external / "doc.txt").resolve()


def test_relative_path_inside_authorized_root(
    policy: PathPolicy, workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(workspace)
    access = policy.authorize("notes.txt", "read")
    assert access.path == (workspace / "notes.txt").resolve()


def test_relative_path_outside_any_root_denied(
    policy: PathPolicy, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    with pytest.raises(PathDeniedError):
        policy.authorize("notes.txt", "read")
