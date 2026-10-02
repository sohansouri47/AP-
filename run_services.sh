#!/usr/bin/env bash
# =====================================================================
# ZAMP AP AI Employee — Service Launcher
# =====================================================================

set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

echo "=========================================================="
echo "⚡ Starting ZAMP Accounts Payable AI Employee Platform"
echo "=========================================================="

# 1. Check PostgreSQL
echo "Checking PostgreSQL connection on port 5432..."
if nc -z 127.0.0.1 5432 2>/dev/null; then
    echo "✅ PostgreSQL is reachable on 127.0.0.1:5432"
else
    echo "⚠️ Warning: PostgreSQL does not seem to be listening on 127.0.0.1:5432."
    echo "   Ensure PostgreSQL container/service is running: postgresql://postgres:postgres@localhost:5432/zamp_ap"
fi

# 2. Check FastMCP Server (Port 8000)
if nc -z 127.0.0.1 8000 2>/dev/null; then
    echo "✅ FastMCP Server is already running on port 8000."
else
    echo "🚀 Starting FastMCP Server on port 8000 (background)..."
    PYTHONPATH=backend:mcp .venv/bin/python mcp/run_server.py &
    MCP_PID=$!
    echo "   FastMCP PID: $MCP_PID"
    sleep 2
fi

# 3. Start FastAPI Backend (Port 8080)
if nc -z 127.0.0.1 8080 2>/dev/null; then
    echo "✅ FastAPI Backend is already running on port 8080."
else
    echo "🚀 Starting FastAPI Backend on port 8080 (background)..."
    PYTHONPATH=backend .venv/bin/uvicorn app.main:app --port 8080 &
    API_PID=$!
    echo "   FastAPI PID: $API_PID"
    sleep 2
fi

# 4. Start Streamlit Frontend (Port 8501)
echo "🚀 Starting Streamlit Frontend on http://localhost:8501..."
echo "=========================================================="
echo "Access the UI at: http://localhost:8501"
echo "API Docs at:     http://localhost:8080/docs"
echo "FastMCP SSE at:  http://localhost:8000/sse"
echo "=========================================================="

PYTHONPATH=frontend .venv/bin/streamlit run frontend/app.py --server.port 8501
