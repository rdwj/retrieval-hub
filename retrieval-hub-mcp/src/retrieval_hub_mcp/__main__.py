"""Entry point: ``python -m retrieval_hub_mcp``."""

import os

from retrieval_hub_mcp.server import mcp

if __name__ == "__main__":
    host = os.environ.get("MCP_HTTP_HOST", "127.0.0.1")
    port = int(os.environ.get("MCP_HTTP_PORT", "8000"))
    mcp.run(transport="streamable-http", host=host, port=port)
