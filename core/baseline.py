"""Baseline runner: turn N candidate runs into a baseline with measured noise bands.

Repo-agnostic. Two modes:

  1. --cmd "make eval-candidate" --runs 3
     Runs your eval command N times; after each run reads --candidate
     (default evals/candidate.json) and collects the scores.
  2. --from "evals/runs/*.json"
     Reads already-produced candidate files (glob) instead of running anything.

Output (default evals/baseline.json):
  {"manifest": <copied from the last candidate, if present>,
   "n_runs": N,
   "metrics": {"<name>": {"mean": m, "sigma": s, "band_2sigma": 2s}}}

The gate uses max(registry noise_band, band_2sigma) as the regression band,
so a noisy metric earns a wide band from DATA, not from someone's guess.
Refuses to write a baseline from fewer than 2 runs unless --allow-single.
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import statistics
import subprocess
import sys
from pathlib import Path


def collect_from_cmd(cmd: str, runs: int, candidate: Path) -> list[dict]:
    outs = []
    for i in range(runs):
        print(f"[baseline] run {i + 1}/{runs}: {cmd}")
        r = subprocess.run(cmd, shell=True)
        if r.returncode != 0:
            raise SystemExit(f"FAIL: eval command exited {r.returncode} on run {i + 1}")
        if not candidate.exists():
            raise SystemExit(f"FAIL: {candidate} not written by the eval command")
        outs.append(json.loads(candidate.read_text()))
    return outs


def collect_from_glob(pattern: str) -> list[dict]:
    files = sorted(glob.glob(pattern))
    if not files:
        raise SystemExit(f"FAIL: no files match {pattern}")
    return [json.loads(Path(f).read_text()) for f in files]


def scores_of(raw: dict, source: str) -> dict:
    s = raw.get("scores") if isinstance(raw.get("scores"), dict) else raw
    if not isinstance(s, dict) or not s:
        raise SystemExit(f"FAIL: {source}: no scores found")
    out = {}
    for k, v in s.items():
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise SystemExit(f"FAIL: {source}: score {k}={v!r} is non-numeric — "
                             f"a broken emitter must not shape the baseline")
        out[k] = float(v)
    return out


def build_baseline(runs: list[dict]) -> dict:
    all_scores = [scores_of(r, f"run {i}") for i, r in enumerate(runs)]
    names = sorted(set().union(*[set(s) for s in all_scores]))
    metrics = {}
    for name in names:
        vals = [s[name] for s in all_scores if name in s]
        if any(not math.isfinite(v) for v in vals):
            raise SystemExit(f"FAIL: non-finite value for {name} in baseline runs "
                             f"— a broken instrument must not become the baseline")
        mean = statistics.fmean(vals)
        sigma = statistics.stdev(vals) if len(vals) > 1 else 0.0
        metrics[name] = {"mean": mean, "sigma": sigma, "band_2sigma": 2 * sigma}
    out = {"n_runs": len(runs), "metrics": metrics}
    last_manifest = runs[-1].get("manifest")
    if isinstance(last_manifest, dict):
        out["manifest"] = last_manifest
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cmd", help="eval command to run N times")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--from", dest="from_glob", help="glob of candidate files")
    ap.add_argument("--candidate", default="evals/candidate.json")
    ap.add_argument("--out", default="evals/baseline.json")
    ap.add_argument("--allow-single", action="store_true",
                    help="permit a 1-run baseline (bands will be zero — regressions "
                         "inside real noise will BLOCK; you were warned)")
    args = ap.parse_args(argv)

    if bool(args.cmd) == bool(args.from_glob):
        ap.error("exactly one of --cmd or --from is required")
    runs = (collect_from_cmd(args.cmd, args.runs, Path(args.candidate))
            if args.cmd else collect_from_glob(args.from_glob))
    if len(runs) < 2 and not args.allow_single:
        raise SystemExit("FAIL: need >=2 runs to measure noise bands "
                         "(--allow-single to override)")
    baseline = build_baseline(runs)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(baseline, indent=2) + "\n")
    print(f"baseline written -> {out}  (runs: {baseline['n_runs']})")
    for k, v in baseline["metrics"].items():
        print(f"  {k}: mean {v['mean']:.4f}  band_2sigma {v['band_2sigma']:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
