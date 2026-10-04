#!/usr/bin/env python3
"""/eval-init scaffolder — installs the gate into the CURRENT repository.

Creates (never overwrites without --force):
  evals/registry.yaml            metric registry for the detected profile (EDIT IT)
  evals/registry_changes.yaml    justifications file for the diff lint
  evals/candidate.example.json   the score contract your eval run must emit
  evals/tools/                   vendored gate: promote.py, compare.py, adapters.py,
                                 registry_lint.py, registry_diff_lint.py,
                                 baseline.py, conductor.py, explain.py,
                                 steps.yaml  (stdlib + PyYAML only)
  evals/fixtures/README.md       how to prove every hard gate can BLOCK
  .github/workflows/eval-gate.yml  CI wiring, producer pre-filled for the profile

Profiles (--profile, default auto):
  pytest       repo has a test suite -> gate test_pass_rate / test_count /
               test_failures from JUnit XML on the FIRST push, no editing needed.
               test_count floor = tests collected right now.
  plugin-eval  repo is a Claude Code plugin -> gate `claude plugin eval` results
               (score, with-vs-without delta, case floor).
  llm          starter LLM-system registry (task success, schema, safety,
               latency, cost); you wire the producer.
  auto         plugin-eval if .claude-plugin/plugin.json exists, else pytest if
               a test suite is detected, else llm.

Also: `--conductor` initializes the 27-step evidence ledger
      (evals/conductor_state.json) for --project/--archetype.

Usage: eval_init.py [--force] [--profile auto|pytest|plugin-eval|llm]
                    [--conductor --project NAME --archetype A2]
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
CORE = PLUGIN_ROOT / "core"
TEMPLATES = PLUGIN_ROOT / "templates"
PROFILES = ("auto", "pytest", "plugin-eval", "llm")

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

PRODUCERS = {
    "pytest": """\
          # Tests failing must NOT stop the adapter: a missing/empty JUnit file
          # scores 0.0 and the gate BLOCKs — fail closed, not fail silent.
          pip install pytest
          # EDIT if your tests need more: pip install -r requirements.txt / pip install -e .
          [ -f requirements.txt ] && pip install -r requirements.txt || true
          [ -f pyproject.toml ] && pip install -e . 2>/dev/null || true
          python -m pytest -q --junitxml=evals/junit.xml || true
          python evals/tools/adapters.py junit evals/junit.xml""",
    "plugin-eval": """\
          # Needs Claude Code + ANTHROPIC_API_KEY in CI secrets. --max-cost-usd
          # caps spend; a partial run is REFUSED by the adapter, never scored.
          npm install -g @anthropic-ai/claude-code
          claude plugin eval . --trust-plugin --no-publish --max-cost-usd 10 --json evals/plugin-eval.json
          python evals/tools/adapters.py plugin-eval evals/plugin-eval.json""",
    "llm": """\
          # EDIT: run your evals, then convert their output. Adapters:
          #   python evals/tools/adapters.py promptfoo out.json
          #   python evals/tools/adapters.py scores   my-scores.json   # {metric: number}
          echo "REPLACE ME — run your evals here" && test -f evals/candidate.json""",
}

EXAMPLES = {
    "pytest": """\
{
  "manifest": {
    "source": "junit:evals/junit.xml",
    "registry_hash": "sha256 of evals/registry.yaml — adapters.py fills this in"
  },
  "scores": {
    "test_pass_rate": 1.0,
    "test_count": __TEST_COUNT__,
    "test_failures": 0
  }
}
""",
    "plugin-eval": """\
{
  "manifest": {
    "source": "plugin-eval:evals/results/<timestamp>/aggregate-result.json",
    "registry_hash": "sha256 of evals/registry.yaml — adapters.py fills this in"
  },
  "scores": {
    "plugin_eval_score": 0.92,
    "plugin_eval_mean_delta": 0.35,
    "plugin_eval_min_case_score": 0.8,
    "plugin_eval_min_case_delta": 0.1,
    "plugin_eval_cases_passed": 5,
    "plugin_eval_cases_total": 5
  }
}
""",
}


def detect_profile(repo: Path) -> tuple[str, str]:
    """(profile, reason)."""
    if (repo / ".claude-plugin" / "plugin.json").exists():
        return "plugin-eval", ".claude-plugin/plugin.json present"
    markers = [p for p in ("tests", "test") if (repo / p).is_dir()]
    if not markers and list(repo.glob("test_*.py")) + list(repo.glob("*_test.py")):
        markers = ["test_*.py at repo root"]
    section = re.compile(r"^\s*\[(tool\.pytest(\.ini_options)?|pytest|tool:pytest)\]", re.M)
    cfg = [p for p in ("pytest.ini", "tox.ini", "setup.cfg", "pyproject.toml")
           if (repo / p).exists() and section.search((repo / p).read_text(errors="replace"))]
    if markers or cfg:
        return "pytest", "found " + ", ".join(markers + cfg)
    return "llm", "no plugin manifest or test suite detected"


def count_tests(repo: Path) -> int | None:
    """Tests pytest would collect right now, or None if collection fails."""
    try:
        r = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q"],
                           cwd=repo, capture_output=True, text=True, timeout=300)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode not in (0, 5):   # 5 = no tests collected; anything else = broken collection
        return None
    out = r.stdout + r.stderr
    # "N tests collected", "1 test collected", "S/N tests collected (K deselected)":
    # the SELECTED count is what JUnit will report — deselected tests never do.
    m = re.search(r"(?:(\d+)/)?(\d+) tests? collected", out)
    if m:
        return int(m.group(1) if m.group(1) else m.group(2))
    if re.search(r"no tests collected", out):
        return 0
    return len([ln for ln in r.stdout.splitlines() if "::" in ln])


def ensure_gitignore(repo: Path, lines: list[str]) -> None:
    gi = repo / ".gitignore"
    text = gi.read_text() if gi.exists() else ""
    existing = set(text.splitlines())
    add = [ln for ln in lines if ln not in existing]
    if not add:
        return
    body = (text.rstrip("\n") + "\n" if text else "") + "\n".join(add) + "\n"
    gi.write_text(body)
    for ln in add:
        print(f"  gitignore: added {ln}")


def install(force: bool, profile: str) -> str:
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

    test_count: int | None = None
    if profile == "pytest":
        test_count = count_tests(repo)
        if test_count is None:
            print("  note: pytest collection failed — test_count floor set to 1; "
                  "raise it in a reviewed commit once the suite collects")
            test_count = 1
        elif test_count == 0:
            print("  note: pytest collects 0 tests here — a floor of 0 protects nothing, "
                  "and a 0-test run scores 0.0. Falling back to the llm profile; "
                  "re-run with --profile pytest once tests exist.")
            profile = "llm"
        else:
            print(f"  detected {test_count} tests -> test_count floor = {test_count}")

    def fill(text: str) -> str:
        return text.replace("__TEST_COUNT__", str(test_count if test_count is not None else 1))

    reg_src = {"pytest": "registry.pytest.yaml",
               "plugin-eval": "registry.plugin-eval.yaml",
               "llm": "registry.yaml"}[profile]
    put(repo / "evals/registry.yaml", text=fill((TEMPLATES / reg_src).read_text()))
    put(repo / "evals/registry_changes.yaml", src=TEMPLATES / "registry_changes.yaml")
    if profile in EXAMPLES:
        put(repo / "evals/candidate.example.json", text=fill(EXAMPLES[profile]))
    else:
        put(repo / "evals/candidate.example.json", src=TEMPLATES / "candidate.example.json")
    for f in ("promote.py", "compare.py", "adapters.py", "registry_lint.py",
              "registry_diff_lint.py", "baseline.py", "conductor.py", "explain.py",
              "eval_receipt.py", "prereg.py", "canonical.py", "chain_state.py",
              "steps.yaml"):
        put(repo / "evals/tools" / f, src=CORE / f)
    put(repo / "evals/fixtures/README.md", text=FIXTURES_README)
    workflow = (TEMPLATES / "eval-gate.yml").read_text().replace(
        "__PRODUCE_CANDIDATE__", PRODUCERS[profile])
    put(repo / ".github/workflows/eval-gate.yml", text=workflow)

    # Eval receipts: gitignore the signing key (never committed) and generate
    # one so every gate run signs a tamper-evident receipt automatically. The
    # receipts themselves (evals/receipts/) ARE committed — they are the anchor
    # — so they are deliberately NOT ignored.
    import secrets as _secrets
    ensure_gitignore(repo, ["evals/.receipt-key"])
    key_path = repo / "evals/.receipt-key"
    if not key_path.exists():  # never clobber an existing key — it would orphan old receipts
        key_path.write_text(_secrets.token_hex(32) + "\n")
        try:
            key_path.chmod(0o600)
        except OSError:
            pass
        created.append(str(key_path.relative_to(repo)))
        print(f"  wrote: {key_path.relative_to(repo)} (signing key — gitignored, "
              f"never commit it; receipts sign automatically now)")
    return profile


NEXT = {
    "pytest": """
NEXT STEPS (in order):
 1. python -m pytest -q --junitxml=evals/junit.xml; python evals/tools/adapters.py junit evals/junit.xml
 2. python evals/tools/promote.py            -> first gate run: real numbers, threshold-only.
 3. git add evals .github && git push        -> the gate is live in CI on this push.
 4. Add your LLM/eval metrics to evals/registry.yaml when you have a producer
    (adapters: promptfoo, scores). Then baseline.py --runs 3 for noise bands.
 5. Write BLOCK fixtures (evals/fixtures/README.md) — prove each hard gate fires.
Never edit a threshold to turn a red gate green.""",
    "plugin-eval": """
NEXT STEPS (in order):
 1. claude plugin eval . --trust-plugin --no-publish      -> evals/results/<ts>/
 2. python evals/tools/adapters.py plugin-eval evals/results/
 3. python evals/tools/promote.py            -> first gate run, threshold-only.
 4. Noise bands from data: repeat step 1 three times, convert each run
    (adapters.py plugin-eval evals/results/<ts>/ --out evals/runs/<n>.json),
    then python evals/tools/baseline.py --from "evals/runs/*.json"
 5. Add ANTHROPIC_API_KEY to CI secrets; the workflow is pre-filled.
Never edit a threshold to turn a red gate green.""",
    "llm": """
NEXT STEPS (in order):
 1. EDIT evals/registry.yaml — your real metrics, thresholds, blocking tiers.
 2. Make your eval run write evals/candidate.json (shape: candidate.example.json),
    or convert its output: python evals/tools/adapters.py promptfoo|scores <file>
 3. python evals/tools/promote.py            -> first gate run (threshold-only).
 4. python evals/tools/baseline.py --cmd "<your eval cmd>" --runs 3
                                             -> measured noise bands.
 5. Write BLOCK fixtures (evals/fixtures/README.md) — prove each hard gate fires.
 6. Fill in the eval command in .github/workflows/eval-gate.yml and push.
Never edit a threshold to turn a red gate green.""",
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--profile", choices=PROFILES, default="auto")
    ap.add_argument("--conductor", action="store_true")
    ap.add_argument("--project")
    ap.add_argument("--archetype", default="A2")
    args = ap.parse_args()

    try:
        import yaml  # noqa: F401
    except ImportError:
        print("FAIL: PyYAML is required — pip install pyyaml", file=sys.stderr)
        return 2

    repo = Path.cwd()
    profile = args.profile
    if profile == "auto":
        profile, why = detect_profile(repo)
        print(f"Profile: {profile} ({why}; override with --profile)")
    else:
        print(f"Profile: {profile}")
    print(f"Installing eval gate into {repo}")
    profile = install(args.force, profile)

    if args.conductor:
        if not args.project:
            print("FAIL: --conductor needs --project NAME", file=sys.stderr)
            return 2
        r = subprocess.run([sys.executable, "evals/tools/conductor.py", "init",
                            "--project", args.project, "--archetype", args.archetype])
        if r.returncode != 0:
            return r.returncode

    print(NEXT[profile])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
