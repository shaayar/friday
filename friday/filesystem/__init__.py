"""
Filesystem subsystem — authorized, policy-enforced filesystem access.

The subsystem is transport-free. It exposes four capabilities (read_file,
write_file, list_directory, search_files) through a strict policy boundary.
The MCP adapter lives in friday.tools.filesystem and is the only consumer.
"""

from friday.filesystem.manager import (
    DEFAULT_LIST_LIMIT,
    DEFAULT_READ_LIMIT_BYTES,
    DEFAULT_SEARCH_MAX_DEPTH,
    DEFAULT_SEARCH_MAX_RESULTS,
    DEFAULT_WRITE_LIMIT_BYTES,
    FileSystemManager,
)
from friday.filesystem.policy import PathPolicy
from friday.filesystem.registry import ProjectRegistry

__all__ = [
    "DEFAULT_LIST_LIMIT",
    "DEFAULT_READ_LIMIT_BYTES",
    "DEFAULT_SEARCH_MAX_DEPTH",
    "DEFAULT_SEARCH_MAX_RESULTS",
    "DEFAULT_WRITE_LIMIT_BYTES",
    "FileSystemManager",
    "PathPolicy",
    "ProjectRegistry",
]
