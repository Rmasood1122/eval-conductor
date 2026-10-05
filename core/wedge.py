"""Zero-config wedge: `eval-prove` — one command, a signed proof of your tests.

The on-ramp to the gate. `/eval-init` installs a full registry-driven gate, which
is the right tool once a team is ready to define metrics and bands. This command
is for the sixty seconds before that: point it at a repo that already has tests
and get back a tamper-evident, signed receipt that *these tests passed, provably,
at this commit* — plus a badge you can paste into a pull request. No registry, no
editing, no config.

Proof + auto-gate (capture-then-gate):
  - FIRST run has nothing to regress against, so it PROMOTEs and records the
    measured pass-rate and test-count as the bar in evals/.wedge-baseline.json.
    (A hardcoded "100% or BLOCK" would fail every flaky suite on run one and make
    the tool useless — the honest bar is "don't get worse than you are now".)
  - LATER runs BLOCK if the pass-rate drops below the bar or tests disappear
    (losing tests is the oldest way to turn a gate green). The bar ratchets up on
    a clean run and never down — a BLOCK never lowers it.

Every decision emits a receipt via the same engine as the full gate (eval_receipt),
so a wedge proof and a gate proof verify identically. A signing key is generated
(gitignored) on first run so proofs are signed by default.

Honest about what a green badge means: it proves "not worse than before", not
"good", and the badge always shows the test COUNT so it can't imply more coverage
than exists. One run doesn't calibrate flakiness — for measured noise bands and
real thresholds, graduate to `/eval-init`.

Usage:
  python3 wedge.py                      # detect + run pytest, prove the result
  python3 wedge.py --junit report.xml   # already have JUnit? just prove it
  python3 wedge.py --run "make test"    # your own command (must write JUnit)
  python3 wedge.py --min-pass-rate 0.95 # pin a floor instead of the captured one

Exit: 0 PROMOTE · 1 BLOCK · 2 can't measure (fail-closed — no proof of an
unmeasured run).
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from adapters import parse_junit, junit_scores, AdapterError   # noqa: E402
from compare import decide                                      # noqa: E402
import eval_receipt                                             # noqa: E402

DEFAULT_RECEIPTS_DIR = "evals/receipts"
DEFAULT_KEY_PATH = "evals/.receipt-key"
DEFAULT_BASELINE = "evals/.wedge-baseline.json"


# --------------------------------------------------------------- detection
def detect_suite(work_dir: Path) -> tuple[str, str]:
    """(kind, reason). kind is 'pytest' or 'none'. Self-contained so the vendored
    wedge needs nothing but adapters/compare/eval_receipt beside it."""
    markers = [p for p in ("tests", "test") if (work_dir / p).is_dir()]
    if not markers and (list(work_dir.glob("test_*.py"))
                        + list(work_dir.glob("*_test.py"))):
        markers = ["test_*.py at repo root"]
    section = re.compile(r"^\s*\[(tool\.pytest(\.ini_options)?|pytest|tool:pytest)\]",
                         re.M)
    cfg = [p for p in ("pytest.ini", "tox.ini", "setup.cfg", "pyproject.toml")
           if (work_dir / p).exists()
           and section.search((work_dir / p).read_text(errors="replace"))]
    if markers or cfg:
        return "pytest", "found " + ", ".join(markers + cfg)
    return "none", "no test suite detected"


def run_pytest(work_dir: Path, run_cmd: str | None) -> Path | None:
    """Run the suite, return the JUnit XML path, or None if it couldn't run."""
    out = work_dir / ".eval-prove-junit.xml"
    if out.exists():
        out.unlink()
    if run_cmd:
        # The user's command must write JUnit to this path; we tell them where.
        cmd = run_cmd.replace("{junit}", str(out))
        try:
            # SECURITY: shell=True runs ONLY the command the user passed
            # explicitly via --run (e.g. "pytest --junitxml={junit}"). It is
            # never built from network input, file contents, or any untrusted
            # source — identical trust level to a Makefile target the user runs
            # themselves. The timeout bounds a runaway command.
            subprocess.run(cmd, cwd=work_dir, shell=True, timeout=1800)
        except (OSError, subprocess.TimeoutExpired):
            return None
        return out if out.exists() else None
    try:
        subprocess.run(
            [sys.executable, "-m", "pytest", "-q", f"--junitxml={out}"],
            cwd=work_dir, capture_output=True, text=True, timeout=1800)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out if out.exists() else None


# --------------------------------------------------------------- gate
def _registry_from_baseline(baseline: dict | None, min_pass_rate: float | None) -> list:
    """Build the in-memory gate. None baseline (first run) => empty registry =>
    nothing to breach => PROMOTE, and we capture the bar afterwards."""
    if baseline is None and min_pass_rate is None:
        return []
    floor_rate = min_pass_rate if min_pass_rate is not None else baseline["test_pass_rate"]
    reg = [{
        "name": "test_pass_rate", "direction": "higher_better",
        "threshold": float(floor_rate), "noise_band": 0.0, "blocking": "hard",
    }]
    if baseline is not None:
        reg.append({
            "name": "test_count", "direction": "higher_better",
            "threshold": float(baseline["test_count"]), "noise_band": 0.0,
            "blocking": "hard",
        })
    reg.append({
        "name": "test_failures", "direction": "lower_better",
        "threshold": 1e9, "noise_band": 0.0, "blocking": "monitor_only",
    })
    return reg


def _verdict_dicts(verdicts) -> list:
    return [{"metric": v.metric, "status": v.status, "reason": v.reason,
             "candidate": v.candidate, "threshold": v.threshold} for v in verdicts]


# --------------------------------------------------------------- badge
def _badge(decision: str, scores: dict) -> str:
    passed = int(round(scores["test_pass_rate"] * scores["test_count"]))
    total = scores["test_count"]
    if decision == "PROMOTE":
        label, color = f"proven {passed}/{total}", "brightgreen"
    else:
        label, color = f"regressed {passed}/{total}", "red"
    label_enc = label.replace(" ", "%20").replace("/", "%2F")
    url = f"https://img.shields.io/badge/evals-{label_enc}-{color}"
    return f"![evals]({url})"


# --------------------------------------------------------------- orchestrate
def run(*, work_dir, junit_path=None, run_cmd=None, receipts_dir=DEFAULT_RECEIPTS_DIR,
        key_path=DEFAULT_KEY_PATH, baseline_file=DEFAULT_BASELINE,
        min_pass_rate=None) -> dict:
    """Measure -> gate -> prove. Returns a result dict; raises nothing for a
    normal BLOCK (that's decision data, not an error). Raises WedgeUnmeasured
    only when it genuinely cannot measure."""
    work_dir = Path(work_dir)
    receipts_dir = Path(receipts_dir)
    baseline_file = Path(baseline_file)
    key_path = Path(key_path)

    # 1. obtain JUnit
    if junit_path is not None:
        jp = Path(junit_path)
        if not jp.exists():
            raise WedgeUnmeasured(f"--junit {jp} not found")
    else:
        kind, reason = detect_suite(work_dir)
        if kind == "none":
            raise WedgeUnmeasured(
                "no test suite detected. Point me at results with --junit "
                "report.xml, or give a command that writes JUnit with "
                "--run \"pytest --junitxml={junit}\".")
        jp = run_pytest(work_dir, run_cmd)
        if jp is None:
            raise WedgeUnmeasured(
                "could not run the test suite to a JUnit file. Run your tests "
                "yourself and pass the XML with --junit, or use --run.")

    # 2. score (fail-closed: zero executed -> 0.0)
    try:
        scores = junit_scores(jp)
    except AdapterError as exc:
        raise WedgeUnmeasured(str(exc))

    # 2b. zero collected tests is not a proof. A run that measured nothing must
    # fail closed (CANNOT PROVE), never emit a brightgreen "PROVEN 0/0" badge.
    if scores.get("test_count", 0) == 0:
        raise WedgeUnmeasured(
            "zero tests were collected or executed — a run that measured nothing "
            "proves nothing. Check your test discovery (e.g. functions must be "
            "named test_*), or pass results with --junit / --run.")

    # 3. gate (capture-then-gate)
    baseline = None
    if baseline_file.exists():
        try:
            baseline = json.loads(baseline_file.read_text())
        except (json.JSONDecodeError, OSError):
            baseline = None
    # The bar also lives in the signed, tamper-evident receipts. If the local
    # baseline file is missing (deleted, or a fresh clone), rebuild the bar from
    # the receipt chain so deleting evals/.wedge-baseline.json cannot launder a
    # regression into a "first run". A genuine first run (no receipts yet) still
    # captures cleanly. To lower the bar deliberately, pin it with --min-pass-rate.
    bar_from_receipts = False
    if baseline is None:
        recovered = _bar_from_receipts(receipts_dir)
        if recovered is not None:
            baseline = recovered
            bar_from_receipts = True
    registry = _registry_from_baseline(baseline, min_pass_rate)
    if registry:
        decision, verdicts = decide(registry, scores, None)
    else:
        decision, verdicts = "PROMOTE", []   # first run: capture, don't gate

    # 4. ratchet the bar forward on PROMOTE only; a BLOCK never lowers it
    if decision == "PROMOTE":
        new_bar = {"test_pass_rate": scores["test_pass_rate"],
                   "test_count": scores["test_count"]}
        if baseline is not None:
            new_bar["test_pass_rate"] = max(baseline["test_pass_rate"],
                                            scores["test_pass_rate"])
            new_bar["test_count"] = max(baseline["test_count"],
                                        scores["test_count"])
        baseline_file.parent.mkdir(parents=True, exist_ok=True)
        baseline_file.write_text(json.dumps(new_bar, indent=2) + "\n")

    # 5. sign + receipt (auto-gen key so proofs are signed by default)
    _ensure_key(key_path)
    key = eval_receipt.load_key_from(str(key_path))
    receipt_path = eval_receipt.emit(
        decision, verdicts, registry_path=str(jp), candidate_path=str(jp),
        baseline_path=str(baseline_file) if baseline_file.exists() else None,
        manifest={"source": "eval-prove", "scores": scores},
        receipts_dir=receipts_dir, key=key)

    return {
        "decision": decision,
        "scores": scores,
        "verdicts": _verdict_dicts(verdicts),
        "receipt_path": str(receipt_path) if receipt_path else None,
        "badge": _badge(decision, scores),
        "first_run": baseline is None,
        "bar_from_receipts": bar_from_receipts,
    }


def _bar_from_receipts(receipts_dir) -> dict | None:
    """Reconstruct the ratcheted bar from prior eval-prove PROMOTE receipts.

    The bar is the high-water mark (max pass-rate, max test-count) across past
    PROMOTE receipts — the same value the local .wedge-baseline.json would hold.
    Because it comes from the signed, hash-chained receipts, deleting the local
    baseline file cannot reset it. Returns {test_pass_rate, test_count} or None
    when there is genuinely no prior proof. Never raises."""
    rdir = Path(receipts_dir)
    if not rdir.exists():
        return None
    best_rate = best_count = None
    try:
        paths = list(rdir.rglob("*.json"))
    except OSError:
        return None
    for p in paths:
        try:
            r = json.loads(p.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        if r.get("decision") != "PROMOTE":
            continue
        man = r.get("manifest") or {}
        if man.get("source") != "eval-prove":
            continue
        sc = man.get("scores") or {}
        pr, tc = sc.get("test_pass_rate"), sc.get("test_count")
        if not isinstance(pr, (int, float)) or isinstance(pr, bool):
            continue
        if not isinstance(tc, (int, float)) or isinstance(tc, bool):
            continue
        best_rate = pr if best_rate is None else max(best_rate, pr)
        best_count = tc if best_count is None else max(best_count, tc)
    if best_rate is None:
        return None
    return {"test_pass_rate": float(best_rate), "test_count": float(best_count)}


class WedgeUnmeasured(Exception):
    """Could not measure the suite — fail closed, no proof of an unmeasured run."""


def _ensure_key(key_path: Path) -> None:
    if key_path.exists():
        return
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_text(eval_receipt.make_key() + "\n")
    try:
        key_path.chmod(0o600)
    except OSError:
        pass


# --------------------------------------------------------------- CLI
def _print_result(res: dict) -> None:
    s = res["scores"]
    passed = int(round(s["test_pass_rate"] * s["test_count"]))
    if res["decision"] == "PROMOTE":
        tag = "first run — bar captured" if res["first_run"] else "no regression"
        print(f"\nPROVEN ({tag}): {passed}/{s['test_count']} tests pass "
              f"({s['test_pass_rate']*100:.1f}%)")
    else:
        print(f"\nBLOCKED: regression vs your captured bar — "
              f"{passed}/{s['test_count']} tests pass "
              f"({s['test_pass_rate']*100:.1f}%)", file=sys.stderr)
        for v in res["verdicts"]:
            if v["status"] == "BLOCK":
                print(f"  - {v['metric']}: {v['reason']}", file=sys.stderr)
    if res.get("bar_from_receipts"):
        print("(bar recovered from signed receipts — the local baseline file was "
              "missing. Deleting it does not reset the bar; pin a lower floor "
              "deliberately with --min-pass-rate.)", file=sys.stderr)
    if res["receipt_path"]:
        rid = Path(res["receipt_path"]).stem
        print(f"receipt: {rid[:12]}…  ({res['receipt_path']})")
    print("\nPaste this into your PR:")
    print(f"  {res['badge']}")
    print("\nThis proves \"not worse than before\", not \"good\" — "
          f"{s['test_count']} test(s), signed. For measured noise bands and "
          "real thresholds, run /eval-init.")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default=".", help="repo to prove (default: cwd)")
    ap.add_argument("--junit", default=None, help="an existing JUnit XML to prove")
    ap.add_argument("--run", default=None,
                    help="command that writes JUnit; use {junit} for the path")
    ap.add_argument("--min-pass-rate", type=float, default=None,
                    help="pin the pass-rate floor instead of the captured one")
    ap.add_argument("--receipts-dir", default=DEFAULT_RECEIPTS_DIR)
    ap.add_argument("--receipt-key", default=DEFAULT_KEY_PATH)
    ap.add_argument("--baseline-file", default=DEFAULT_BASELINE)
    args = ap.parse_args(argv)

    try:
        res = run(work_dir=args.dir, junit_path=args.junit, run_cmd=args.run,
                  receipts_dir=args.receipts_dir, key_path=args.receipt_key,
                  baseline_file=args.baseline_file, min_pass_rate=args.min_pass_rate)
    except WedgeUnmeasured as exc:
        print(f"CANNOT PROVE: {exc}", file=sys.stderr)
        return 2
    _print_result(res)
    return 0 if res["decision"] == "PROMOTE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
