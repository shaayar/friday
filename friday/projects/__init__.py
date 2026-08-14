"""
Project subsystem — project identity, registration, CWD detection,
active-project focus, and the private FRIDAY project workspace.

The subsystem is transport-free. It exposes the ``ProjectService``
facade as the single public entry point and performs all filesystem I/O
through the ``FileSystemManager`` capability layer.
"""

from friday.projects.active import ActiveProjectManager
from friday.projects.detector import ProjectDetector
from friday.projects.service import ProjectService, build_filesystem_manager, build_project_service
from friday.projects.workspace import ProjectWorkspace

__all__ = [
    "ActiveProjectManager",
    "ProjectDetector",
    "ProjectService",
    "ProjectWorkspace",
    "build_filesystem_manager",
    "build_project_service",
]
