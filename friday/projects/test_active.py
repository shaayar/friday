"""
Tests for ActiveProjectManager.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from friday.filesystem.registry import ProjectRegistry
from friday.projects.active import ActiveProjectManager
from friday.projects.detector import ProjectDetector
from friday.projects.exceptions import ProjectNotFoundError
from friday.projects.models import DETECTED, EXPLICIT


@pytest.fixture
def env(tmp_path: Path) -> SimpleNamespace:
    registry = ProjectRegistry(tmp_path / "registry.json")
    detector = ProjectDetector(registry)
    active = ActiveProjectManager(tmp_path / "active_project.json", registry, detector)
    return SimpleNamespace(registry=registry, detector=detector, active=active, tmp=tmp_path)


@pytest.fixture
def project(env: SimpleNamespace) -> str:
    root = env.tmp / "project"
    root.mkdir()
    return env.registry.register(root, name="app").id


def test_activate_sets_explicit(env: SimpleNamespace, project: str) -> None:
    active = env.active.activate(project)

    assert active.project_id == project
    assert active.source == EXPLICIT
    assert env.active.get() == active


def test_activate_persists(env: SimpleNamespace, project: str) -> None:
    env.active.activate(project)

    reloaded = ActiveProjectManager(env.tmp / "active_project.json", env.registry, env.detector)
    assert reloaded.get() is not None
    assert reloaded.get().project_id == project
    assert reloaded.get().source == EXPLICIT


def test_activate_unknown_project_raises(env: SimpleNamespace) -> None:
    with pytest.raises(ProjectNotFoundError):
        env.active.activate("does-not-exist")


def test_explicit_active_survives_cwd_changes(env: SimpleNamespace, project: str) -> None:
    env.active.activate(project)
    outside = env.tmp / "elsewhere"
    outside.mkdir()

    result = env.active.reconcile(outside)

    assert result is not None
    assert result.source == EXPLICIT
    assert result.project_id == project


def test_reconcile_without_explicit_sets_detected(
    env: SimpleNamespace, project: str, tmp_path: Path
) -> None:
    root = tmp_path / "project"
    sub = root / "src"
    sub.mkdir(parents=True)
    env.registry.register(root, name="app")

    result = env.active.reconcile(sub)

    assert result is not None
    assert result.source == DETECTED
    assert result.project_id == env.registry.project_containing(sub.resolve()).id


def test_reconcile_outside_all_roots_clears(env: SimpleNamespace, project: str) -> None:
    env.active.reconcile(env.tmp / "project")
    outside = env.tmp / "elsewhere"
    outside.mkdir()

    result = env.active.reconcile(outside)

    assert result is None
    assert env.active.get() is None


def test_clear_falls_back_to_detection(env: SimpleNamespace, project: str, tmp_path: Path) -> None:
    root = tmp_path / "project"
    sub = root / "src"
    sub.mkdir(parents=True)
    env.registry.register(root, name="app")
    env.active.activate(project)

    result = env.active.clear(sub)

    assert result is not None
    assert result.source == DETECTED


def test_clear_outside_all_roots_leaves_none(env: SimpleNamespace, project: str) -> None:
    env.active.activate(project)
    outside = env.tmp / "elsewhere"
    outside.mkdir()

    result = env.active.clear(outside)

    assert result is None
    assert env.active.get() is None


def test_unregistered_explicit_active_cleared_and_falls_back(
    env: SimpleNamespace, project: str, tmp_path: Path
) -> None:
    env.active.activate(project)
    env.registry.revoke(project)
    root = tmp_path / "other"
    root.mkdir()
    other = env.registry.register(root, name="other")

    result = env.active.reconcile(root)

    assert result is not None
    assert result.source == DETECTED
    assert result.project_id == other.id


def test_stale_pointer_cleared_on_reconcile(env: SimpleNamespace, tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    env.registry.register(root, name="app")
    stale = {"project_id": "ghost", "source": EXPLICIT, "updated_at": "2026-01-01T00:00:00+00:00"}
    (tmp_path / "active_project.json").write_text(json.dumps(stale))
    outside = tmp_path / "elsewhere"
    outside.mkdir()

    result = env.active.reconcile(outside)

    assert result is None
    assert env.active.get() is None


def test_detected_active_is_recomputed(env: SimpleNamespace, tmp_path: Path) -> None:
    root = tmp_path / "first"
    root.mkdir()
    first = env.registry.register(root, name="first")
    env.active.reconcile(root)
    assert env.active.get().project_id == first.id

    other_root = tmp_path / "other"
    other_root.mkdir()
    second = env.registry.register(other_root, name="second")
    result = env.active.reconcile(other_root)

    assert result is not None
    assert result.source == DETECTED
    assert result.project_id == second.id