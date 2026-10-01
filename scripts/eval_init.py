#!/usr/bin/env python3
"""/eval-init scaffolder — installs the gate into the CURRENT repository.

Creates (never overwrites without --force):
  evals/registry.yaml            starter metric registry (EDIT IT)
  evals/registry_changes.yaml    justifications file for the diff lint
  evals/candidate.example.json   the score contract your eval run must emit
  evals/tools/                   vendored gate: promote.py, compare.py,
                                 registry_lint.py, registry_diff_lint.py,
                                 baseline.py, conductor.py, steps.yaml
                                 (stdlib + PyYAML only)
  evals/fixtures/README.md       how to prove every hard gate can BLOCK
  .github/workflows/eval-gate.yml  CI wiring (you fill in your eval command)

Also: `--conductor` initializes the 27-step evidence ledger
      (evals/conductor_state.json) for --project/--archetype.

Usage: eval_init.py [--force] [--conductor --project NAME --archetype A2]
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
CORE = PLUGIN_ROOT / "core"
TEMPLATES = PLUGIN_ROOT / "templates"

FIXTURES_README = """\
# BLOCK fixtures — prove every hard gate can fire

A gate that has never been seen to BLOCK is decoration, not protection.
For EVERY `blocking: hard` row in `../registry.yaml`, keep one candidate
fixture here that breaches ONLY that metric (all other metrics healthy),
plus one `healthy.json` that PROMOTEs clean. Then assert both in a test:

    python evals/tools/promote.py --candidate evals/fixtures/block_<metric>.json
    # must exit 1, blocking exactly <metric>

    python evals/tools/promote.py --candidate evals/fixtures/healthy.json
    # must exit 0

For `lower_better` metrics (latency, cost) the breach value is ABOVE the
threshold — the most common fixture mistake.

Add a coverage check so a new hard row forces a new fixture: list the hard
rows from the registry, list the block_*.json files, assert the sets match.
"""


def install(force: bool) -> list[str]:
    created: list[str] = []
    repo = Path.cwd()

    def put(dst: Path, src: Path | None = None, text: str | None = None):
        if dst.exists() and not force:
            print(f"  skip (exists): {dst.relative_to(repo)}")
            return
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src is not None:
            shutil.copy2(src, dst)
        else:
            dst.write_text(text or "")
        created.append(str(dst.relative_to(repo)))
        print(f"  wrote: {dst.relative_to(repo)}")

    put(repo / "evals/registry.yaml", src=TEMPLATES / "registry.yaml")
    put(repo / "evals/registry_changes.yaml", src=TEMPLATES / "registry_changes.yaml")
    put(repo / "evals/candidate.example.json", src=TEMPLATES / "candidate.example.json")
    for f in ("promote.py", "compare.py", "registry_lint.py", "registry_diff_lint.py",
              "baseline.py", "conductor.py", "steps.yaml"):
        put(repo / "evals/tools" / f, src=CORE / f)
    put(repo / "evals/fixtures/README.md", text=FIXTURES_README)
    put(repo / ".github/workflows/eval-gate.yml", src=TEMPLATES / "eval-gate.yml")
    return created


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--conductor", action="store_true")
    ap.add_argument("--project")
    ap.add_argument("--archetype", default="A2")
    args = ap.parse_args()

    try:
        import yaml  # noqa: F401
    except ImportError:
        print("FAIL: PyYAML is required — pip install pyyaml", file=sys.stderr)
        return 2

    print(f"Installing eval gate into {Path.cwd()}")
    install(args.force)

    if args.conductor:
        if not args.project:
            print("FAIL: --conductor needs --project NAME", file=sys.stderr)
            return 2
        r = subprocess.run([sys.executable, "evals/tools/conductor.py", "init",
                            "--project", args.project, "--archetype", args.archetype])
        if r.returncode != 0:
            return r.returncode

    print("""
NEXT STEPS (in order):
 1. EDIT evals/registry.yaml — your real metrics, thresholds, blocking tiers.
 2. Make your eval run write evals/candidate.json (shape: candidate.example.json).
 3. python evals/tools/promote.py            -> first gate run (threshold-only).
 4. python evals/tools/baseline.py --cmd "<your eval cmd>" --runs 3
                                             -> measured noise bands.
 5. Write BLOCK fixtures (evals/fixtures/README.md) — prove each hard gate fires.
 6. Fill in the eval command in .github/workflows/eval-gate.yml and push.
Never edit a threshold to turn a red gate green.""")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
