"""
Tools — Tool registry and implementations for the MCP server.
"""
from . import system, utils, web

def register_all_tools(mcp):
    system.register(mcp)
    utils.register(mcp)
    web.register(mcp)