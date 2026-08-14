"""
Project subsystem domain models.

These models form the vocabulary of the project workspace subsystem.
They are transport-free and independent of any interface (LiveKit, MCP,
CLI, web UI) and of any AI provider.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from friday.filesystem.models import Project

EXPLICIT = "explicit"
DETECTED = "detected"


@dataclass(frozen=True, slots=True)
class DetectedProject:
    """A runtime observation: which registered Project's root contains a CWD.

    Never persisted and never writes. Detecting a directory never
    registers or creates anything.
    """

    project: Project
    cwd: Path


@dataclass(frozen=True, slots=True)
class ActiveProject:
    """The current focus pointer, persisted to disk.

    ``source`` is ``EXPLICIT`` when the user activated the project and
    ``DETECTED`` when it was derived from the current working directory.
    An explicit active project survives CWD changes; a detected one is
    recomputed from the CWD on every reconcile.
    """

    project_id: str
    source: str
    updated_at: str
