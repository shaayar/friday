"""
Data resources — expose static content or dynamic data via MCP resources.
"""


def register(mcp):

    @mcp.resource("friday://info")
    def server_info() -> str:
        """Returns basic info about this MCP server."""
        return "Friday MCP Server\nA Tony Stark-inspired AI assistant.\nBuilt with FastMCP."
