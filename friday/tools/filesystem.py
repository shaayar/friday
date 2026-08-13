"""
Filesystem tools — MCP adapter for the filesystem capability layer.

This module is the only place where the filesystem subsystem touches MCP.
All policy, authorization, and I/O logic lives in friday.filesystem.
"""

from friday.config import config
from friday.filesystem.exceptions import FilesystemError
from friday.filesystem.manager import FileSystemManager
from friday.filesystem.policy import PathPolicy
from friday.filesystem.registry import ProjectRootRegistry


def _build_manager() -> FileSystemManager:
    registry = ProjectRootRegistry(config.FRIDAY_HOME / "project_roots.json")
    policy = PathPolicy(workspace_root=config.FRIDAY_HOME, registry=registry)
    return FileSystemManager(
        policy,
        read_limit_bytes=config.FILESYSTEM_READ_LIMIT_BYTES,
        write_limit_bytes=config.FILESYSTEM_WRITE_LIMIT_BYTES,
        list_limit=config.FILESYSTEM_LIST_LIMIT,
        search_max_results=config.FILESYSTEM_SEARCH_MAX_RESULTS,
        search_max_depth=config.FILESYSTEM_SEARCH_MAX_DEPTH,
    )


def _ok(data: dict) -> dict:
    return {"success": True, "error": None, "data": data}


def _err(exc: FilesystemError) -> dict:
    return {"success": False, "error": f"{type(exc).__name__}: {exc}", "data": None}


def register(mcp):
    """Register the four filesystem capabilities as MCP tools."""

    @mcp.tool()
    def read_file(path: str) -> dict:
        """Read a text file from an authorized root. Returns content and byte count."""
        manager = _build_manager()
        try:
            result = manager.read_file(path)
        except FilesystemError as exc:
            return _err(exc)
        return _ok({"path": str(result.path), "content": result.content, "bytes_read": result.bytes_read})

    @mcp.tool()
    def write_file(path: str, content: str, overwrite: bool = False) -> dict:
        """Write a text file inside an authorized root. Refuses to overwrite an existing file unless overwrite=True; the parent directory must already exist."""
        manager = _build_manager()
        try:
            result = manager.write_file(path, content, overwrite=overwrite)
        except FilesystemError as exc:
            return _err(exc)
        return _ok(
            {
                "path": str(result.path),
                "bytes_written": result.bytes_written,
                "existed": result.existed,
            }
        )

    @mcp.tool()
    def list_directory(path: str) -> dict:
        """List the entries of a directory inside an authorized root."""
        manager = _build_manager()
        try:
            result = manager.list_directory(path)
        except FilesystemError as exc:
            return _err(exc)
        return _ok(
            {
                "path": str(result.path),
                "entries": [
                    {
                        "name": entry.name,
                        "path": str(entry.path),
                        "is_dir": entry.is_dir,
                        "size": entry.size,
                        "modified": entry.modified,
                    }
                    for entry in result.entries
                ],
            }
        )

    @mcp.tool()
    def search_files(path: str, pattern: str, max_depth: int | None = None, max_results: int | None = None) -> dict:
        """Search file names by regex within an authorized root. Depth and result limits are enforced; optional max_depth/max_results narrow the search."""
        manager = _build_manager()
        try:
            result = manager.search_files(path, pattern, max_depth=max_depth, max_results=max_results)
        except FilesystemError as exc:
            return _err(exc)
        return _ok(
            {
                "query": result.query,
                "root": str(result.root),
                "matches": [str(match) for match in result.matches],
            }
        )
