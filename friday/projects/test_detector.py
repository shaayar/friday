"""
Tests for ProjectDetector.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from friday.filesystem.registry import ProjectRegistry
from friday.projects.detector import ProjectDetector
from friday.projects.models import DetectedProject


@pytest.fixture
def env(tmp_path: Path) -> SimpleNamespace:
    registry = ProjectRegistry(tmp_path / "registry.json")
    detector = ProjectDetector(registry)
    return SimpleNamespace(registry=registry, detector=detector, tmp=tmp_path)


def test_detect_inside_root(env: SimpleNamespace, tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    project = env.registry.register(root, name="app")

    result = env.detector.detect(root / "src" / "components")

    assert isinstance(result, DetectedProject)
    assert result.project is project
    assert result.cwd == (root / "src" / "components").resolve()


def test_detect_at_root_itself(env: SimpleNamespace, tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    project = env.registry.register(root, name="app")

    result = env.detector.detect(root)

    assert result is not None
    assert result.project is project


def test_detect_unknown_directory_returns_none(env: SimpleNamespace, tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    env.registry.register(root, name="app")

    result = env.detector.detect(tmp_path / "unrelated")

    assert result is None


def test_detect_unknown_directory_never_registers(
    env: SimpleNamespace, tmp_path: Path
) -> None:
    unknown = tmp_path / "unknown"
    unknown.mkdir()
    before = len(env.registry.list_projects())

    env.detector.detect(unknown)

    assert len(env.registry.list_projects()) == before
    assert env.registry.project_containing(unknown.resolve()) is None


def test_detect_never_creates_workspace(env: SimpleNamespace, tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    env.registry.register(root, name="app")
    projects_dir = tmp_path / "friday" / "projects"
    projects_dir.mkdir(parents=True)

    env.detector.detect(root / "sub")

    assert list(projects_dir.iterdir()) == []


def test_detect_prefers_longest_matching_root(env: SimpleNamespace, tmp_path: Path) -> None:
    outer_root = tmp_path / "outer"
    inner_root = outer_root / "inner"
    inner_root.mkdir(parents=True)
    outer = env.registry.register(outer_root, name="outer")
    inner = env.registry.register(inner_root, name="inner")

    result = env.detector.detect(inner_root / "deep" / "file.py")

    assert result is not None
    assert result.project is inner

    outside = env.detector.detect(outer_root / "elsewhere")
    assert outside is not None
    assert outside.project is outer


def test_detect_defaults_to_current_directory(
    env: SimpleNamespace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    env.registry.register(root, name="app")
    sub = root / "sub"
    sub.mkdir()
    monkeypatch.chdir(sub)

    result = env.detector.detect()

    assert result is not None
    assert result.project.root == root.resolve()