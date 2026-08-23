"""
Tools — Tool registry and implementations for the MCP server.
"""

from . import filesystem, notes, retry, system, utils, web


def register_all_tools(mcp):
    filesystem.register(mcp)
    system.register(mcp)
    utils.register(mcp)
    web.register(mcp)
    notes.register(mcp)
    retry.register(mcp)
