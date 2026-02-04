"""
MCP (Model Context Protocol) Server für InjectionRadar.

Ermöglicht AI-Assistenten wie Claude, InjectionRadar als Tool zu nutzen.
"""

from .server import create_mcp_server, run_mcp_server

__all__ = ["create_mcp_server", "run_mcp_server"]
