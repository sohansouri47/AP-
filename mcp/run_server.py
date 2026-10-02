#!/usr/bin/env python3
"""Standalone FastMCP Server Runner for AP AI Employee.

Starts the FastMCP Accounts Payable server over HTTP/SSE transport (strictly non-stdio).
Default endpoint: http://127.0.0.1:8000/sse

Usage:
    python mcp/run_server.py
    python mcp/run_server.py --port 8001 --host 0.0.0.0
"""

import argparse
import sys
from pathlib import Path

# Ensure backend and mcp are on sys.path
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_BACKEND_DIR = str(_PROJECT_ROOT / "backend")
_MCP_DIR = str(_PROJECT_ROOT / "mcp")

for p in [_BACKEND_DIR, _MCP_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)

from server import run_server, mcp


def main():
    parser = argparse.ArgumentParser(description="Run AP AI Employee FastMCP Server")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Bind port (default: 8000)")
    parser.add_argument("--transport", default="sse", choices=["sse", "http"], help="Transport mode (default: sse)")
    args = parser.parse_args()

    print("=" * 65)
    print("AP AI EMPLOYEE - FASTMCP SERVER (NON-STDIO)")
    print("=" * 65)
    print(f"Transport: {args.transport.upper()} (Server-Sent Events)")
    print(f"Listen Address: http://{args.host}:{args.port}/{args.transport}")
    print(f"Server Name: {mcp.name}")
    print(f"Tools Registered: 34 AP Financial Controls & Subagent Tools")
    print(f"Resources: ap://config, ap://policy, ap://health")
    print("=" * 65)

    run_server(host=args.host, port=args.port, transport=args.transport)


if __name__ == "__main__":
    main()
