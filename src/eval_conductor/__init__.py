"""Eval Conductor — the integrity layer for your evals.

Fail-closed release gates for AI/eval scores you already produce
(claude plugin eval, pytest, promptfoo, JUnit, any JSON), with signed,
tamper-evident, hash-chained receipts and pre-registered bars.

This package wraps the same engine shipped as the Claude Code / Codex plugin
and exposes it as a standalone CLI (`eval-conductor`) so it runs in any CI
pipeline with no AI agent required.
"""

__version__ = "1.4.0"
