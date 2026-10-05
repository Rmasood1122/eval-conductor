#!/usr/bin/env python3
"""Score adapters: turn the eval output you ALREADY produce into a gateable
candidate.json — so the gate judges real numbers from day one.

    python evals/tools/adapters.py junit       report.xml
    python evals/tools/adapters.py plugin-eval evals/results/            # latest run
    python evals/tools/adapters.py plugin-eval evals/results/<ts>/aggregate-result.json
    python evals/tools/adapters.py promptfoo   promptfoo-output.json
    python evals/tools/adapters.py scores      my-scores.json            # flat {metric: number}

Every adapter writes {"manifest": {"registry_hash": ..., "source": ...},
"scores": {...}} to --out (default evals/candidate.json). registry_hash is the
sha256 of --registry (default evals/registry.yaml) so promote.py can VERIFY the
candidate was produced against the registry on disk.

Fail-closed, by construction:
  - unreadable / unparseable input                       -> exit 2, nothing written
  - JUnit with zero executed tests                       -> pass rate 0.0 (gate BLOCKs)
  - claude plugin eval result with "partial": true       -> exit 2 (a partial run
    gates nothing — cost ceiling hit or auth failed mid-run)
  - promptfoo output with no recognisable stats           -> exit 2

Metric names each adapter emits (put these in your registry):
  junit        test_pass_rate, test_count, test_failures
  plugin-eval  plugin_eval_score, plugin_eval_mean_delta, plugin_eval_min_case_score,
               plugin_eval_min_case_delta, plugin_eval_cases_passed, plugin_eval_cases_total
  promptfoo    promptfoo_pass_rate, promptfoo_total, promptfoo_failures
  scores       whatever keys the file has (numbers only; anything else -> exit 2)

stdlib only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import numbers
import sys
from pathlib import Path
from xml.etree import ElementTree as ET


class AdapterError(Exception):
    """Input could not be turned into scores. Caller exits 2; nothing is written."""


# ----------------------------------------------------------------- helpers
def _finite(x: object, what: str) -> float:
    if isinstance(x, bool) or not isinstance(x, numbers.Real):
        raise AdapterError(f"{what} is not a number: {x!r}")
    f = float(x)
    if not math.isfinite(f):
        raise AdapterError(f"{what} is not finite: {x!r}")
    return f


def _load_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise AdapterError(f"not found: {path}")
    except json.JSONDecodeError as e:
        raise AdapterError(f"invalid JSON in {path}: {e}")


# ------------------------------------------------------------------- junit
def parse_junit(xml_path: Path) -> dict:
    """(tests, executed, failed, skipped) from a JUnit XML file.

    executed = tests - skipped; failed includes <error>s. Missing or unparseable
    XML raises AdapterError — the caller decides whether that is exit 2 (adapter
    CLI) or zeros (a producer that must always emit a candidate).
    """
    if not xml_path.exists():
        raise AdapterError(f"JUnit XML not found: {xml_path}")
    try:
        root = ET.parse(xml_path).getroot()
    except ET.ParseError as e:
        raise AdapterError(f"unparseable JUnit XML {xml_path}: {e}")
    suites = root.findall("testsuite") or ([root] if root.tag == "testsuite" else [])
    if not suites:
        raise AdapterError(f"{xml_path}: no <testsuite> elements")
    try:
        tests = sum(int(s.get("tests", 0)) for s in suites)
        failures = sum(int(s.get("failures", 0)) for s in suites)
        errors = sum(int(s.get("errors", 0)) for s in suites)
        skipped = sum(int(s.get("skipped", 0)) for s in suites)
    except ValueError as e:
        raise AdapterError(f"{xml_path}: non-integer suite counts: {e}")
    return {"tests": tests, "executed": tests - skipped,
            "failed": failures + errors, "skipped": skipped}


def junit_scores(xml_path: Path) -> dict:
    j = parse_junit(xml_path)
    ex = j["executed"]
    rate = (ex - j["failed"]) / ex if ex > 0 else 0.0   # zero tests = 0.0, fail closed
    return {"test_pass_rate": round(rate, 6),
            "test_count": j["tests"],
            "test_failures": j["failed"]}


# ------------------------------------------------------------- plugin-eval
def resolve_plugin_eval_result(path: Path) -> Path:
    """Accept the aggregate-result.json, a run dir containing it, or the
    evals/results/ dir (pick the lexically-latest timestamped run)."""
    if path.is_file():
        return path
    if not path.is_dir():
        raise AdapterError(f"not found: {path}")
    direct = path / "aggregate-result.json"
    if direct.exists():
        return direct
    runs = sorted(p for p in path.iterdir()
                  if p.is_dir() and (p / "aggregate-result.json").exists())
    if not runs:
        raise AdapterError(f"no aggregate-result.json under {path} — run "
                           f"`claude plugin eval .` first")
    return runs[-1] / "aggregate-result.json"


def plugin_eval_scores(path: Path) -> dict:
    """Scores from `claude plugin eval` aggregate-result.json (schemaVersion 1).

    Delta (with-plugin minus without) is the number that matters: a case that
    scores 1.0 in both arms was not passed BECAUSE of the plugin.
    """
    src = resolve_plugin_eval_result(path)
    data = _load_json(src)
    if not isinstance(data, dict):
        raise AdapterError(f"{src}: expected a JSON object")
    if data.get("partial"):
        raise AdapterError(
            f"{src}: partial run ({data.get('partialReason') or 'unknown reason'}) "
            f"— a partial eval gates nothing; re-run to completion")
    agg = data.get("aggregates")
    if not isinstance(agg, dict):
        raise AdapterError(f"{src}: missing 'aggregates' — not a claude plugin eval result")
    cases = data.get("cases") or []
    case_scores, case_deltas = [], []
    for c in cases:
        ca = (c or {}).get("aggregates") or {}
        if "score" in ca:
            case_scores.append(_finite(ca["score"], f"case {c.get('name')!r} score"))
        if ca.get("delta") is not None:
            case_deltas.append(_finite(ca["delta"], f"case {c.get('name')!r} delta"))
    out = {
        "plugin_eval_score": _finite(agg.get("overallScore"), "aggregates.overallScore"),
        "plugin_eval_cases_passed": _finite(agg.get("casesPassed"), "aggregates.casesPassed"),
        "plugin_eval_cases_total": _finite(agg.get("casesTotal"), "aggregates.casesTotal"),
    }
    if agg.get("meanDelta") is not None:
        out["plugin_eval_mean_delta"] = _finite(agg["meanDelta"], "aggregates.meanDelta")
    if case_scores:
        out["plugin_eval_min_case_score"] = min(case_scores)
    if case_deltas:
        out["plugin_eval_min_case_delta"] = min(case_deltas)
    return out


# --------------------------------------------------------------- promptfoo
def promptfoo_scores(path: Path) -> dict:
    """Scores from `promptfoo eval -o out.json`. Looks for stats at
    results.stats or top-level stats: {successes, failures, errors?}."""
    data = _load_json(path)
    stats = None
    if isinstance(data, dict):
        res = data.get("results")
        if isinstance(res, dict) and isinstance(res.get("stats"), dict):
            stats = res["stats"]
        elif isinstance(data.get("stats"), dict):
            stats = data["stats"]
    if not stats or not all(k in stats for k in ("successes", "failures")):
        raise AdapterError(f"{path}: no promptfoo stats (successes/failures) found")
    ok = _finite(stats["successes"], "stats.successes")
    bad = _finite(stats["failures"], "stats.failures")
    bad += _finite(stats.get("errors", 0), "stats.errors")
    total = ok + bad
    rate = ok / total if total > 0 else 0.0
    return {"promptfoo_pass_rate": round(rate, 6),
            "promptfoo_total": total,
            "promptfoo_failures": bad}


# ------------------------------------------------------------------ scores
def flat_scores(path: Path) -> dict:
    data = _load_json(path)
    if isinstance(data, dict) and isinstance(data.get("scores"), dict):
        data = data["scores"]
    if not isinstance(data, dict) or not data:
        raise AdapterError(f"{path}: expected a non-empty JSON object of metric -> number")
    return {str(k): _finite(v, f"score {k!r}") for k, v in data.items()}


ADAPTERS = {
    "junit": junit_scores,
    "plugin-eval": plugin_eval_scores,
    "promptfoo": promptfoo_scores,
    "scores": flat_scores,
}


def build_candidate(kind: str, src: Path, registry: Path, extra_manifest: dict | None = None) -> dict:
    if kind not in ADAPTERS:
        raise AdapterError(f"unknown adapter {kind!r}; choose from {sorted(ADAPTERS)}")
    if not registry.exists():
        raise AdapterError(f"registry not found: {registry} — run from the repo root "
                           f"(or pass --registry) so the candidate can attest which "
                           f"registry it was produced against")
    scores = ADAPTERS[kind](src)
    manifest = {"source": f"{kind}:{src}",
                "registry_hash": hashlib.sha256(registry.read_bytes()).hexdigest()}
    if extra_manifest:
        manifest.update(extra_manifest)
    return {"manifest": manifest, "scores": scores}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("kind", choices=sorted(ADAPTERS))
    ap.add_argument("source", help="file (or, for plugin-eval, a results dir)")
    ap.add_argument("--out", default="evals/candidate.json")
    ap.add_argument("--registry", default="evals/registry.yaml")
    ap.add_argument("--dataset-hash", help="optional attestation copied into the manifest")
    args = ap.parse_args(argv)
    try:
        cand = build_candidate(args.kind, Path(args.source), Path(args.registry),
                               {"dataset_hash": args.dataset_hash} if args.dataset_hash else None)
    except AdapterError as e:
        print(f"FAIL: {e}", file=sys.stderr)
        return 2
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(cand, indent=2) + "\n")
    print(f"{args.kind} -> {out}")
    for k, v in cand["scores"].items():
        print(f"  {k:28} = {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
