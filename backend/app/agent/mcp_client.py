"""FastMCP Client Bridge for Accounts Payable AI Employee.

Connects Main AP Employee, Specialist Subagents (control-executor,
exception-investigator, workflow-improvement-analyst), and Deterministic
Application Gates to the FastMCP server over SSE (Server-Sent Events) transport.

Features:
- Configurable target URL via MCP_SERVER_URL (default: http://127.0.0.1:8000/sse)
- Automatic detection of live remote FastMCP server vs in-process FastMCP instance
- Role-based tool access validation prior to network dispatch
- Thread-safe synchronous invocation bridge using dedicated event loop
- Structured logging with detailed timing, caller identification, and transport status
"""

from __future__ import annotations

import asyncio
import os
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

from fastmcp import Client
from fastmcp.exceptions import ToolError

from app.agent.flow_logger import flow_logger

# Ensure /mcp is on sys.path for server fallback imports
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_MCP_DIR = str(_PROJECT_ROOT / "mcp")
if _MCP_DIR not in sys.path:
    sys.path.insert(0, _MCP_DIR)


def get_local_mcp_server() -> Any:
    """Lazily load FastMCP server instance from the /mcp server module for fallback."""
    from server import mcp
    return mcp


DEFAULT_MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://127.0.0.1:8000/sse")
_background_server_thread: Optional[threading.Thread] = None


def is_port_reachable(host: str, port: int, timeout: float = 0.5) -> bool:
    """Check if target host:port is accepting TCP socket connections."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            return s.connect_ex((host, port)) == 0
    except Exception:
        return False


def start_mcp_server_background(host: str = "127.0.0.1", port: int = 8000) -> Optional[threading.Thread]:
    """Start FastMCP server on HTTP/SSE in a background daemon thread."""
    global _background_server_thread
    if _background_server_thread and _background_server_thread.is_alive():
        return _background_server_thread

    # If an external FastMCP server is already active on host:port, reuse it
    if is_port_reachable(host, port):
        return None

    def _serve():
        # Run server with SSE transport
        srv = get_local_mcp_server()
        srv.run(
            transport="sse",
            host=host,
            port=port,
            show_banner=False,
            log_level="error",
        )

    t = threading.Thread(target=_serve, daemon=True, name="FastMCP-SSE-Server")
    t.start()
    _background_server_thread = t

    # Wait up to 3 seconds for port to bind
    for _ in range(30):
        if is_port_reachable(host, port):
            break
        time.sleep(0.1)

    return t


class FastMCPClientManager:
    """Manages persistent communication to the FastMCP server."""

    def __init__(self, server_url: str = DEFAULT_MCP_SERVER_URL):
        self.server_url = server_url
        parsed = urlparse(server_url)
        self.host = parsed.hostname or "127.0.0.1"
        self.port = parsed.port or 8000

        # Dedicated background event loop for thread-safe async calls
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run_loop,
            daemon=True,
            name="FastMCP-Client-Worker",
        )
        self._thread.start()

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _get_target(self) -> Any:
        """Resolve client target: remote SSE endpoint if port reachable, else local server."""
        if is_port_reachable(self.host, self.port):
            return self.server_url
        return get_local_mcp_server()

    def is_remote_connected(self) -> bool:
        """Returns True if connected to an active remote HTTP/SSE FastMCP process."""
        return is_port_reachable(self.host, self.port)

    def call_tool(
        self,
        caller: str,
        tool_name: str,
        arguments: dict[str, Any],
        timeout: float = 15.0,
    ) -> Any:
        """Invoke a tool on the FastMCP server with timing, logging, and error handling.

        Args:
            caller: Agent or role calling the tool (main_agent, control-executor, etc.).
            tool_name: Registered FastMCP tool name.
            arguments: Tool arguments dictionary.
            timeout: Maximum execution seconds.

        Returns:
            The tool's result data.
        """
        # Validate caller permissions
        from app.agent.mcp_tools import verify_tool_permission
        if caller:
            verify_tool_permission(caller, tool_name)

        target = self._get_target()
        transport_tag = "SSE" if isinstance(target, str) else "In-Process"
        t0 = time.time()

        async def _invoke():
            async with Client(target) as client:
                res = await client.call_tool(tool_name, arguments)
                return res.data

        future = asyncio.run_coroutine_threadsafe(_invoke(), self._loop)
        try:
            result_data = future.result(timeout=timeout)
            duration_ms = (time.time() - t0) * 1000
            return result_data
        except ToolError as te:
            duration_ms = (time.time() - t0) * 1000
            err_msg = str(te)
            flow_logger.tool_call(
                caller=caller,
                tool_name=f"[FastMCP {transport_tag}] {tool_name}",
                status="FAILED",
                details=f"Tool error: {err_msg}",
                duration_ms=duration_ms,
            )
            # Unwrap original exception message if possible
            prefix = f"Error calling tool '{tool_name}':"
            clean_msg = err_msg.split(prefix)[-1].strip() if prefix in err_msg else err_msg
            if "PermissionError" in err_msg or "permission" in clean_msg.lower():
                raise PermissionError(clean_msg)
            if "ValueError" in err_msg or "completeness validation failed" in clean_msg.lower():
                raise ValueError(clean_msg)
            raise
        except Exception as exc:
            duration_ms = (time.time() - t0) * 1000
            flow_logger.tool_call(
                caller=caller,
                tool_name=f"[FastMCP {transport_tag}] {tool_name}",
                status="FAILED",
                details=f"Unexpected error: {exc}",
                duration_ms=duration_ms,
            )
            raise


# Global singleton client manager
_global_client_manager: Optional[FastMCPClientManager] = None


def get_mcp_client() -> FastMCPClientManager:
    """Retrieve global FastMCP client manager instance."""
    global _global_client_manager
    if _global_client_manager is None:
        _global_client_manager = FastMCPClientManager()
    return _global_client_manager
