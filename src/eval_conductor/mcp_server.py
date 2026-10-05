#!/usr/bin/env python3
"""Eval Conductor MCP server.

Exposes the fail-closed eval gate as MCP tools so ANY MCP-capable agent
(Claude Code, OpenAI Codex, Cursor, Copilot) can run it. It shells out to the
installed `eval-conductor` CLI, so the gate logic lives in one place and the
server stays a thin, robust adapter.

Install:  pip install "mcp>=1.0" eval-conductor
Run:      python eval_conductor_mcp.py         (stdio transport)

Register it with an agent via its MCP config, e.g.:
  { "mcpServers": { "eval-conductor": {
      "command": "python", "args": ["/abs/path/eval_conductor_mcp.py"] } } }
"""

from __future__ import annotations

import shlex
import subprocess
import sys

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    sys.stderr.write(
        "eval-conductor-mcp: the MCP SDK 1.x is required "
        "(pip install \"eval-conductor[mcp]\"  or  pip install \"mcp>=1.0,<2\"). "
        "Note: mcp 2.x renamed FastMCP and is not yet supported.\n")
    raise SystemExit(1)

mcp = FastMCP("eval-conductor")


def _run(subcommand: str, extra: str, working_directory: str) -> str:
    """Run `eval-conductor <subcommand> <extra>` and return a labeled result."""
    cmd = ["eval-conductor", subcommand, *shlex.split(extra or "")]
    try:
        proc = subprocess.run(
            cmd, cwd=working_directory or ".",
            capture_output=True, text=True, timeout=1800,
        )
    except FileNotFoundError:
        return ("ERROR: `eval-conductor` is not installed or not on PATH. "
                "Install it with: pip install eval-conductor")
    except subprocess.TimeoutExpired:
        return "ERROR: eval-conductor timed out after 1800s."
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    decision = {0: "PROMOTE/PROVEN", 1: "BLOCK/REGRESSED", 2: "CANNOT PROVE"}.get(
        proc.returncode, f"exit {proc.returncode}")
    parts = [f"decision: {decision} (exit {proc.returncode})"]
    if out:
        parts.append("stdout:\n" + out)
    if err:
        parts.append("stderr:\n" + err)
    return "\n\n".join(parts)


@mcp.tool()
def prove(working_directory: str = ".", args: str = "") -> str:
    """Prove the repo's test suite didn't regress and emit a signed receipt.

    Zero config. First run captures the pass-rate/test-count as the bar; later
    runs BLOCK if the pass-rate drops or tests disappear. Returns the decision,
    the receipt id, and a pasteable PR badge.

    args: extra flags, e.g. '--run "pytest --junitxml={junit}"' or '--junit report.xml'.
    """
    return _run("prove", args, working_directory)


@mcp.tool()
def gate(working_directory: str = ".", args: str = "") -> str:
    """Run the full registry gate: candidate.json vs baseline.json under the
    registry -> per-metric PROMOTE/BLOCK, with a signed receipt. Requires a repo
    already initialized with the gate (evals/registry.yaml etc.)."""
    return _run("gate", args, working_directory)


@mcp.tool()
def verify(working_directory: str = ".", args: str = "") -> str:
    """Walk and verify the receipt chain offline: structure, every signature,
    every decision vs. its own verdicts. Any tamper, fork, or mismatch is
    reported. Read-only."""
    return _run("verify", args, working_directory)


if __name__ == "__main__":
    run()


def run() -> None:
    """Console entry point: eval-conductor-mcp (stdio transport)."""
    mcp.run()
