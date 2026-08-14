"""
Tests for ProjectWorkspace.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from friday.filesystem.manager import FileSystemManager
from friday.filesystem.policy import PathPolicy
from friday.filesystem.registry import ProjectRegistry
from friday.projects.workspace import ProjectWorkspace

SEEDED_FILES = ("context.md", "facts.md", "decisions.md", "changelog.md", "state.json")


@pytest.fixture
def env(tmp_path: Path) -> SimpleNamespace:
    friday_home = tmp_path / "friday"
    friday_home.mkdir()
    registry = ProjectRegistry(tmp_path / "registry.json")
    policy = PathPolicy(workspace_root=friday_home, registry=registry)
    manager = FileSystemManager(policy)
    workspace = ProjectWorkspace(manager, friday_home / "projects")
    return SimpleNamespace(
        manager=manager,
        workspace=workspace,
        projects_root=friday_home / "projects",
    )


def test_ensure_creates_directory_and_seeds_files(env: SimpleNamespace) -> None:
    path = env.workspace.ensure("abc123")

    assert path == env.projects_root / "abc123"
    assert path.is_dir()
    for name in SEEDED_FILES:
        assert (path / name).is_file()
    assert json.loads((path / "state.json").read_text(encoding="utf-8")) == {}


def test_ensure_is_idempotent(env: SimpleNamespace) -> None:
    path = env.workspace.ensure("abc123")
    env.workspace.ensure("abc123")
    assert path.is_dir()


def test_ensure_does_not_overwrite_existing_files(env: SimpleNamespace) -> None:
    env.workspace.ensure("p1")
    env.workspace.write_context("p1", "custom context")

    env.workspace.ensure("p1")

    assert env.workspace.read_context("p1") == "custom context"


def test_read_write_context(env: SimpleNamespace) -> None:
    env.workspace.ensure("p1")
    env.workspace.write_context("p1", "working on feature X")
    assert env.workspace.read_context("p1") == "working on feature X"


def test_append_fact(env: SimpleNamespace) -> None:
    env.workspace.ensure("p1")
    env.workspace.append_fact("p1", "Project uses Python 3.11.")
    env.workspace.append_fact("p1", "Tests run with pytest.")

    content = env.workspace.read_facts("p1")
    assert "Project uses Python 3.11." in content
    assert "Tests run with pytest." in content


def test_append_decision(env: SimpleNamespace) -> None:
    env.workspace.ensure("p1")
    env.workspace.append_decision("p1", "Use longest-root matching.")
    env.workspace.append_decision("p1", "Explicit beats detected.")

    content = env.workspace.read_decisions("p1")
    assert "Use longest-root matching." in content
    assert "Explicit beats detected." in content


def test_append_changelog(env: SimpleNamespace) -> None:
    env.workspace.ensure("p1")
    env.workspace.append_changelog("p1", "Added project registry.")

    assert "Added project registry." in env.workspace.read_changelog("p1")


def test_state_roundtrip(env: SimpleNamespace) -> None:
    env.workspace.ensure("p1")
    env.workspace.write_state("p1", {"branch": "main", "task": "add tests"})

    assert env.workspace.read_state("p1") == {"branch": "main", "task": "add tests"}


def test_project_path_is_under_workspace_root(env: SimpleNamespace) -> None:
    assert env.workspace.project_path("p1") == env.projects_root / "p1"
