# Eval Conductor MCP server

The MCP server ships inside the package. Don't run a loose script — use the
console entry point so there are no fragile paths:

    pip install "eval-conductor[mcp]"
    eval-conductor-mcp          # stdio transport

Register it with any MCP-capable agent (Cursor, Codex, Copilot, Claude Code):

    { "mcpServers": { "eval-conductor": { "command": "eval-conductor-mcp" } } }

Tools exposed: prove, gate, verify.
