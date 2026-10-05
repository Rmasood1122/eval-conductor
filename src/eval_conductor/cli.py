"""Standalone `eval-conductor` command.

A thin dispatcher over the existing core modules. Each core module exposes a
`main(argv) -> int`, and self-inserts its own directory onto sys.path on import
(so its bare sibling imports resolve). We reproduce that exact runtime contract
here by putting the bundled `_core` directory on sys.path and importing the
modules by bare name — identical to how the plugin runs them. No logic is
reimplemented, so a CLI decision and a plugin decision are byte-identical.
"""

from __future__ import annotations

import sys
from pathlib import Path

_CORE = Path(__file__).resolve().parent / "_core"
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))

__version__ = "1.4.0"

# (subcommand) -> (core module name, fixed leading args prepended to the user's)
# The core modules are imported lazily inside dispatch() so that `--help` and a
# bad subcommand are fast and never import everything.
_ROUTES: dict[str, tuple[str, list[str]]] = {
    "prove":        ("wedge",         []),
    "gate":         ("promote",       []),
    "baseline":     ("baseline",      []),
    "import":       ("adapters",      []),
    "explain":      ("explain",       []),
    "verify":       ("eval_receipt",  ["verify"]),
    "init-key":     ("eval_receipt",  ["init"]),
    "seal":         ("prereg",        ["seal"]),
    "seal-check":   ("prereg",        ["check"]),
    "registry-lint":("registry_diff_lint", []),
    "conductor":    ("conductor",     []),
}

_SUMMARY = {
    "prove":         "Prove an existing test suite -> signed receipt + PR badge (zero config).",
    "gate":          "Candidate vs baseline under the registry -> PROMOTE/BLOCK.",
    "baseline":      "Run your eval N times and measure per-metric noise bands.",
    "import":        "Convert junit/plugin-eval/promptfoo/scores into candidate.json.",
    "explain":       "Explain a gate decision in plain English.",
    "verify":        "Walk + verify the receipt chain offline.",
    "init-key":      "Generate a receipt signing key.",
    "seal":          "Pre-register (seal) the bar before a run.",
    "seal-check":    "Verify the live bar against the seal (--require-seal to fail closed).",
    "registry-lint": "Diff-lint the registry against its own git history.",
    "conductor":     "The 27-step evidence-gated build ledger.",
}


def _usage() -> str:
    lines = [
        "eval-conductor — the integrity layer for your evals",
        f"  version {__version__}",
        "",
        "usage: eval-conductor <command> [options]",
        "",
        "commands:",
    ]
    width = max(len(c) for c in _ROUTES)
    for cmd in _ROUTES:
        lines.append(f"  {cmd.ljust(width)}  {_SUMMARY.get(cmd, '')}")
    lines += [
        "",
        "Run `eval-conductor <command> --help` for a command's options.",
        "Start with:  eval-conductor prove",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    if not argv or argv[0] in ("-h", "--help", "help"):
        print(_usage())
        return 0
    if argv[0] in ("-V", "--version", "version"):
        print(__version__)
        return 0

    cmd, rest = argv[0], argv[1:]
    route = _ROUTES.get(cmd)
    if route is None:
        print(f"eval-conductor: unknown command '{cmd}'\n", file=sys.stderr)
        print(_usage(), file=sys.stderr)
        return 2

    module_name, fixed = route
    import importlib
    mod = importlib.import_module(module_name)
    return int(mod.main(fixed + rest))


if __name__ == "__main__":
    raise SystemExit(main())
