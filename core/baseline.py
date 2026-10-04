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
   "metrics": {"<name>": {"mean": m, "sigma": s, "band_2sigma": 2s,
                          "median": md, "mad": a, "band_mad": 2*1.4826*a}}}

The gate uses max(registry noise_band, measured band) as the regression band,
so a noisy metric earns a wide band from DATA, not from someone's guess. The
measured band is band_2sigma by default, or band_mad for rows that declare
`band_method: mad` (robust; the right choice for pass-rates and anything
bounded near 0 or 1 — see F-E2 in the audit).
Refuses to write a baseline from fewer than 2 runs unless --allow-single.

HONESTY ABOUT N (read this before trusting a band):
  A 2-sigma band is only as good as the sigma it is measured from, and at
  small N that sigma is itself extremely noisy. At N=3 the estimate has 2
  degrees of freedom — the band can swing roughly +/-50-60% run to run, so a
  3-run band is closer to an educated guess than a measurement. Worse, a few
  runs can land identical BY LUCK (common for pass-rate metrics near 1.0),
  giving sigma=0 and a ZERO band: after that, any later dip at all — even one
  flaky case — BLOCKs. This runner now warns on both conditions (low N, and
  any zero band at N>=2). Treat >=10-20 runs as the floor for a band you lean
  on; N=3 is a smoke test, not a calibration.
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

# A band you lean on needs a sigma measured from enough runs. Below this the
# 2-sigma estimate is too noisy to be called a measurement — we still write
# it, but we say so loudly. See the module docstring on N.
RECOMMENDED_RUNS = 10

# Robust band (F-E2). mean ± 2σ assumes an unbounded, roughly normal metric.
# Pass-rates and anything pinned near 0 or 1 are neither: the ceiling
# compresses the variance, one outlier run blows σ up, and the symmetric band
# is the wrong shape. median ± k·1.4826·MAD is the standard robust
# alternative — 1.4826 scales MAD to σ under normality, so k=2 keeps the
# same nominal coverage as band_2sigma while ignoring single outliers.
# Per-row opt-in via registry `band_method: mad`; default stays sigma.
MAD_SCALE = 1.4826
MAD_K = 2.0


def robust_stats(vals: list[float]) -> tuple[float, float]:
    """(median, MAD) of vals. MAD = median(|x - median|). Both 0.0 for n<2."""
    if len(vals) < 2:
        return (float(vals[0]) if vals else 0.0), 0.0
    med = statistics.median(vals)
    mad = statistics.median(abs(v - med) for v in vals)
    return float(med), float(mad)


def band_warnings(baseline: dict) -> list[str]:
    """Non-fatal warnings about how trustworthy the measured bands are.

    Two conditions, both silent failure modes the gate would otherwise
    inherit without anyone noticing:
      - too few runs: the sigma behind every band is high-variance at low N.
      - a zero band at N>=2: runs landed identical (often by luck near a
        metric's ceiling), so the regression check now has NO slack and will
        BLOCK on the first bit of real noise.
    """
    warns: list[str] = []
    n = baseline.get("n_runs", 0)
    if n < RECOMMENDED_RUNS:
        warns.append(
            f"only {n} run(s): a 2-sigma band from {n} runs is a high-variance "
            f"estimate, not a measurement — it can swing ~50% run to run. Use "
            f">={RECOMMENDED_RUNS} runs for a band you gate on; treat this one "
            f"as a smoke test.")
    zero = [name for name, m in baseline.get("metrics", {}).items()
            if n >= 2 and float(m.get("band_2sigma", 0.0)) == 0.0]
    if zero:
        warns.append(
            f"zero-width band(s) for {zero}: every run scored identically, so "
            f"the measured band is 0.00 and the gate has NO slack for these — "
            f"the next run that dips by one case will BLOCK. This usually means "
            f"too few runs or a metric pinned at its ceiling, not real "
            f"zero-noise. Add runs, or set a deliberate registry noise_band.")
    return warns


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
        median, mad = robust_stats(vals)
        metrics[name] = {
            "mean": mean, "sigma": sigma, "band_2sigma": 2 * sigma,
            # robust companions (F-E2): used when the registry row says
            # band_method: mad. Always written so one baseline serves both.
            "median": median, "mad": mad, "band_mad": MAD_K * MAD_SCALE * mad,
        }
    out = {"n_runs": len(runs), "metrics": metrics}
    last_manifest = runs[-1].get("manifest")
    if isinstance(last_manifest, dict):
        out["manifest"] = last_manifest
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cmd", help="eval command to run N times")
    ap.add_argument("--runs", type=int, default=RECOMMENDED_RUNS,
                    help=f"eval runs to measure noise from (default "
                         f"{RECOMMENDED_RUNS}; fewer prints a trust warning)")
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
        print(f"  {k}: mean {v['mean']:.4f}  band_2sigma {v['band_2sigma']:.4f}"
              f"  | median {v['median']:.4f}  band_mad {v['band_mad']:.4f}")
    warns = band_warnings(baseline)
    for w in warns:
        print(f"WARNING: {w}", file=sys.stderr)
    if warns:
        print("WARNING: bands above are not yet calibration-grade — see the "
              "notes before gating on them.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
