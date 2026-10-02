---
name: fastmcp-server-builder
description: Automated creation, testing, and deployment of Python Model Context Protocol (MCP) servers using FastMCP.
tags: [mcp, fastmcp, python, integration]
---

# FastMCP Server Builder Skill

You are an expert agent skilled in scaffolding, expanding, and validating high-performance **Model Context Protocol (MCP)** servers using the **FastMCP** framework. 

Follow these instructions whenever the user wants to create a new MCP server or add capabilities to an existing one.

## 1. Project Scaffolding
Always use `uv` as the default package manager for FastMCP servers.
1. Initialize the project: `uv init my-mcp-server && cd my-mcp-server`
2. Add FastMCP dependencies: `uv add fastmcp`
3. Create the entrypoint file as `server.py`.

## 2. FastMCP Core Implementation Pattern
When writing code for `server.py`, use the following standard architecture:

```python
import os
from typing import Optional
from pydantic import BaseModel, Field
from fastmcp import FastMCP

# 1. Initialize FastMCP with a clean name
mcp = FastMCP("My API Assistant")

# 2. Define strict models for tool inputs if they are complex
class SearchQuery(BaseModel):
    query: str = Field(description="Search terms or keywords")
    limit: Optional[int] = Field(default=5, description="Max results to return")

# 3. Create Tools (Actions the AI can perform)
@mcp.tool()
def search_items(query: str, limit: int = 5) -> str:
    """
    Search external database or API items. Always include explicit docstrings 
    explaining what the tool does, as the LLM reads this.
    """
    # Tool logic here
    return f"Results for '{query}' (limit {limit})"

# 4. Create Resources (Contextual data the AI can read)
@mcp.resource("config://app")
def get_config() -> str:
    """Exposes static or dynamic app configuration context."""
    return "app_version=1.0.0\nenvironment=production"

# 5. Create Prompts (Predefined templates or UI entrypoints)
@mcp.prompt()
def analyze_logs(log_data: str) -> str:
    """Pre-configures a system prompt layout for log analysis."""
    return f"Please analyze these logs for errors and summarize them:\n\n{log_data}"

# 6. Run block
if __name__ == "__main__":
    mcp.run()
```

## 3. Mandatory Quality & Security Guardrails
* **Type Hints & Docstrings:** Every `@mcp.tool` function **must** have full Python type hints and a detailed docstring. The docstring is translated directly into the tool description for the LLM client.
* **Environment Variables:** Do not hardcode API keys or credentials. Use `os.environ.get("KEY_NAME")` and explicitly document required keys in a comment at the top of `server.py`.
* **Path Validation:** If a tool handles file paths, you **must** validate that it restricts operations to the intended target directory to prevent directory traversal vulnerabilities.

## 4. Local Testing & Verification Workflow
Before declaring a server operational, run these commands to test it:
1. **Inspect tools:** Execute `uv run fastmcp inspect server.py` to check the registered tool descriptions and schemas.
2. **Interactive UI Dev:** Run `uv run fastmcp dev server.py` to open the MCP Inspector dashboard for hot-reloading and executing live tool calls.

## 5. Client Installation Target
When the server passes testing, generate the configuration block for the user's client choice:

### Claude Desktop config (`~/Library/Application Support/Claude/claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "my-mcp-server": {
      "command": "uv",
      "args": ["--directory", "/absolute/path/to/my-mcp-server", "run", "fastmcp", "run", "server.py"]
    }
  }
}
```

### Cursor config:
Instruct the user to navigate to **Cursor Settings -> Features -> MCP**, click "+ New MCP Server", choose type `stdio`, and set the command to `uv --directory /absolute/path/to/my-mcp-server run fastmcp run server.py`.
