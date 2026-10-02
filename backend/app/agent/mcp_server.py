"""FastMCP Server Bridge for Accounts Payable AI Employee.

Re-exports FastMCP server and tools from the primary MCP directory (/mcp).
"""

from __future__ import annotations

import sys
from pathlib import Path

_MCP_DIR = str(Path(__file__).resolve().parents[3] / "mcp")
if _MCP_DIR not in sys.path:
    sys.path.insert(0, _MCP_DIR)

from server import *
