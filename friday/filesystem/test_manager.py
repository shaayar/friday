"""
Tests for FileSystemManager operations and limits.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from friday.filesystem.exceptions import (
    AlreadyExistsError,
    IsDirectoryError,
    LimitError,
    NotDirectoryError,
    PathDeniedError,
    PathNotFoundError,
    PermissionDeniedError,
)
from friday.filesystem.manager import FileSystemManager
from friday.filesystem.policy import PathPolicy
from friday.filesystem.registry import ProjectRegistry


@pytest.fixture
def env(tmp_path: Path) -> SimpleNamespace:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    external = tmp_path / "external"
    external.mkdir()
    registry = ProjectRegistry(tmp_path / "registry.json")
    registry.register(external, name="external", permissions=("read", "write"))
    policy = PathPolicy(workspace_root=workspace, registry=registry)
    manager = FileSystemManager(policy)
    return SimpleNamespace(
        workspace=workspace, external=external, registry=registry, policy=policy, manager=manager
    )


def test_read_file(env: SimpleNamespace) -> None:
    target = env.workspace / "hello.txt"
    target.write_text("hello")

    result = env.manager.read_file(target)
    assert result.content == "hello"
    assert result.bytes_read == 5


def test_read_file_missing_raises(env: SimpleNamespace) -> None:
    with pytest.raises(PathNotFoundError):
        env.manager.read_file(env.workspace / "missing.txt")


def test_read_file_directory_raises(env: SimpleNamespace) -> None:
    (env.workspace / "dir").mkdir()
    with pytest.raises(IsDirectoryError):
        env.manager.read_file(env.workspace / "dir")


def test_read_file_denied_outside_root(env: SimpleNamespace, tmp_path: Path) -> None:
    with pytest.raises(PathDeniedError):
        env.manager.read_file(tmp_path / "secret.txt")


def test_read_size_limit(env: SimpleNamespace) -> None:
    target = env.workspace / "big.txt"
    target.write_text("x" * 50)
    limited = FileSystemManager(env.policy, read_limit_bytes=10)
    with pytest.raises(LimitError):
        limited.read_file(target)


def test_write_file_creates(env: SimpleNamespace) -> None:
    result = env.manager.write_file(env.workspace / "new.txt", "data")

    assert result.existed is False
    assert result.bytes_written == 4
    assert (env.workspace / "new.txt").read_text() == "data"


def test_write_file_no_overwrite_by_default(env: SimpleNamespace) -> None:
    target = env.workspace / "existing.txt"
    target.write_text("old")
    with pytest.raises(AlreadyExistsError):
        env.manager.write_file(target, "new")


def test_write_file_overwrite_allowed(env: SimpleNamespace) -> None:
    target = env.workspace / "existing.txt"
    target.write_text("old")
    result = env.manager.write_file(target, "new", overwrite=True)

    assert result.existed is True
    assert target.read_text() == "new"


def test_write_file_missing_parent_raises(env: SimpleNamespace) -> None:
    with pytest.raises(NotDirectoryError):
        env.manager.write_file(env.workspace / "missing" / "file.txt", "data")


def test_write_file_denied_outside_root(env: SimpleNamespace, tmp_path: Path) -> None:
    with pytest.raises(PathDeniedError):
        env.manager.write_file(tmp_path / "new.txt", "data")


def test_write_size_limit(env: SimpleNamespace) -> None:
    limited = FileSystemManager(env.policy, write_limit_bytes=10)
    with pytest.raises(LimitError):
        limited.write_file(env.workspace / "big.txt", "x" * 50)


def test_create_directory(env: SimpleNamespace) -> None:
    result = env.manager.create_directory(env.workspace / "newdir")

    assert result.path == (env.workspace / "newdir").resolve()
    assert (env.workspace / "newdir").is_dir()


def test_create_directory_nested_without_parent_raises(env: SimpleNamespace) -> None:
    with pytest.raises(NotDirectoryError):
        env.manager.create_directory(env.workspace / "missing" / "deep")


def test_create_directory_nested_with_parents(env: SimpleNamespace) -> None:
    result = env.manager.create_directory(env.workspace / "a" / "b" / "c", parents=True)

    assert result.path == (env.workspace / "a" / "b" / "c").resolve()
    assert (env.workspace / "a" / "b" / "c").is_dir()


def test_create_directory_existing_raises(env: SimpleNamespace) -> None:
    target = env.workspace / "exists"
    target.mkdir()
    with pytest.raises(AlreadyExistsError):
        env.manager.create_directory(target)


def test_create_directory_on_file_raises(env: SimpleNamespace) -> None:
    target = env.workspace / "file.txt"
    target.write_text("x")
    with pytest.raises(NotDirectoryError):
        env.manager.create_directory(target)


def test_create_directory_denied_outside_root(env: SimpleNamespace, tmp_path: Path) -> None:
    with pytest.raises(PathDeniedError):
        env.manager.create_directory(tmp_path / "newdir")


def test_create_directory_requires_write_permission(
    env: SimpleNamespace, tmp_path: Path
) -> None:
    read_only = tmp_path / "readonly"
    read_only.mkdir()
    env.registry.register(read_only, permissions=("read",))
    with pytest.raises(PermissionDeniedError):
        env.manager.create_directory(read_only / "sub")


def test_list_directory(env: SimpleNamespace) -> None:
    (env.workspace / "a.txt").write_text("a")
    (env.workspace / "sub").mkdir()

    listing = env.manager.list_directory(env.workspace)
    names = {entry.name for entry in listing.entries}
    assert names == {"a.txt", "sub"}


def test_list_directory_missing_raises(env: SimpleNamespace) -> None:
    with pytest.raises(PathNotFoundError):
        env.manager.list_directory(env.workspace / "missing")


def test_list_directory_on_file_raises(env: SimpleNamespace) -> None:
    target = env.workspace / "file.txt"
    target.write_text("x")
    with pytest.raises(NotDirectoryError):
        env.manager.list_directory(target)


def test_list_directory_limit(env: SimpleNamespace) -> None:
    for i in range(15):
        (env.workspace / f"f{i}.txt").write_text("x")
    limited = FileSystemManager(env.policy, list_limit=10)
    with pytest.raises(LimitError):
        limited.list_directory(env.workspace)


def test_search_files(env: SimpleNamespace) -> None:
    (env.workspace / "app.py").write_text("x")
    (env.workspace / "readme.md").write_text("x")
    (env.workspace / "sub").mkdir()
    (env.workspace / "sub" / "app_test.py").write_text("x")

    result = env.manager.search_files(env.workspace, r"\.py$")
    names = {match.name for match in result.matches}
    assert names == {"app.py", "app_test.py"}


def test_search_files_missing_raises(env: SimpleNamespace) -> None:
    with pytest.raises(PathNotFoundError):
        env.manager.search_files(env.workspace / "missing", r".*")


def test_search_depth_limit(env: SimpleNamespace) -> None:
    (env.workspace / "a.py").write_text("x")
    (env.workspace / "d1").mkdir()
    (env.workspace / "d1" / "b.py").write_text("x")
    (env.workspace / "d1" / "d2").mkdir()
    (env.workspace / "d1" / "d2" / "c.py").write_text("x")

    result = env.manager.search_files(env.workspace, r"\.py$", max_depth=1)
    names = {match.name for match in result.matches}
    assert names == {"a.py", "b.py"}


def test_search_result_limit(env: SimpleNamespace) -> None:
    for i in range(15):
        (env.workspace / f"file{i}.py").write_text("x")
    limited = FileSystemManager(env.policy, search_max_results=5)
    with pytest.raises(LimitError):
        limited.search_files(env.workspace, r"\.py$")


def test_search_does_not_follow_symlink_escape(env: SimpleNamespace, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.py").write_text("x")
    link = env.workspace / "linkdir"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks not supported on this platform")

    result = env.manager.search_files(env.workspace, r"\.py$")
    assert result.matches == ()
