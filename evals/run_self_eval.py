#!/usr/bin/env python3
"""Self-eval candidate producer — eval-conductor gating itself (dogfood).

Runs the repo's own test suite and emits evals/candidate.json with three
measured scores, then core/promote.py judges them against evals/registry.yaml.

Scores (all measured, no estimates):
  self_test_pass_rate        passed / executed   (executed = collected - skipped)
  test_count                 total collected tests (JUnit `tests` attribute)
  fail_closed_tests_covered  count of test functions whose body asserts a
                             fail-closed outcome, by the pattern below

Fail-closed, by construction: if pytest cannot even collect/run, scores come
out at 0 and the gate BLOCKs — a broken test run can never look like a pass.

stdlib only (+ pytest, which CI installs). Run from the repo root:
    python evals/run_self_eval.py
    python core/promote.py --registry evals/registry.yaml \
                           --candidate evals/candidate.json \
                           --baseline evals/baseline.json
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "evals" / "registry.yaml"
CANDIDATE = ROOT / "evals" / "candidate.json"
TESTS_DIR = ROOT / "tests"

# A "fail-closed test" asserts a blocking / refusing / non-zero-exit outcome.
# Kept in ONE place and applied identically every run, so the count only moves
# when the tests themselves change — never run to run. If you tune this, the
# threshold move it implies is governed by the diff lint.
FAIL_CLOSED = re.compile(
    r"BLOCK|REFUSED|SIG FAIL|CHAIN FAIL|"
    r"returncode\s*==\s*[12]|\.returncode\s*==\s*[12]|"
    r"exit\s*=?=?\s*[12]|status\s*==\s*[\"']BLOCK[\"']|"
    r"must\s+refuse|tamper"
)


def run_pytest_junit() -> tuple[int, int, int, int]:
    """(collected, executed, failed, skipped) from a JUnit XML run, via the
    same parser the plugin ships to users (core/adapters.py). On any failure
    to produce/parse the XML, returns zeros so the gate fails closed."""
    sys.path.insert(0, str(ROOT / "core"))
    from adapters import AdapterError, parse_junit  # noqa: E402
    with tempfile.TemporaryDirectory() as td:
        xml = Path(td) / "report.xml"
        subprocess.run(
            [sys.executable, "-m", "pytest", "tests/", "-q",
             f"--junitxml={xml}"],
            cwd=ROOT, capture_output=True, text=True,
        )
        try:
            j = parse_junit(xml)
        except AdapterError as e:
            print(f"FAIL: {e} — treating as 0 tests (fail closed)", file=sys.stderr)
            return 0, 0, 0, 0
    return j["tests"], j["executed"], j["failed"], j["skipped"]


def _iter_test_bodies(src: str):
    """Yield (name, body) for each top-level `def test_*`."""
    lines = src.splitlines()
    cur, body = None, []
    for ln in lines:
        m = re.match(r"def (test_\w+)\(", ln)
        if m:
            if cur is not None:
                yield cur, "\n".join(body)
            cur, body = m.group(1), []
        elif cur is not None and ln and not ln[0].isspace() and ln.startswith("def "):
            yield cur, "\n".join(body)
            cur, body = None, []
        elif cur is not None:
            body.append(ln)
    if cur is not None:
        yield cur, "\n".join(body)


def fail_closed_count() -> int:
    n = 0
    for tf in sorted(TESTS_DIR.glob("test_*.py")):
        for _name, body in _iter_test_bodies(tf.read_text(encoding="utf-8")):
            if FAIL_CLOSED.search(body):
                n += 1
    return n


def main() -> int:
    collected, executed, failed, skipped = run_pytest_junit()
    pass_rate = (executed - failed) / executed if executed > 0 else 0.0
    candidate = {
        "manifest": {
            # lets promote.py's stale/tamper check engage: the candidate
            # attests which registry it was judged against.
            "registry_hash": hashlib.sha256(REGISTRY.read_bytes()).hexdigest(),
        },
        "scores": {
            "self_test_pass_rate": round(pass_rate, 6),
            "test_count": collected,
            "fail_closed_tests_covered": fail_closed_count(),
        },
    }
    CANDIDATE.write_text(json.dumps(candidate, indent=2) + "\n")
    s = candidate["scores"]
    print(f"self-eval -> {CANDIDATE.relative_to(ROOT)}")
    print(f"  collected={collected} executed={executed} failed={failed} "
          f"skipped={skipped}")
    print(f"  self_test_pass_rate       = {s['self_test_pass_rate']}")
    print(f"  test_count                = {s['test_count']}")
    print(f"  fail_closed_tests_covered = {s['fail_closed_tests_covered']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
