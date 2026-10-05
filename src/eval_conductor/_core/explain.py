"""explain — turn a gate decision into a plain-English diagnosis.

Runs the SAME `decide()` the gate runs (never a second opinion), then for
every non-PASS metric says, in order:
  1. what the metric is and which way "better" points
  2. what happened — threshold breach (absolute) vs regression (relative to
     the baseline, beyond the noise band) vs invalid/missing measurement
  3. how far past the line, in the metric's own units
  4. the ONE legitimate fix, and the moves that are theater (threshold edit,
     band widening, tier downgrade, metric deletion, "refresh the baseline"
     while red) — each named, so nobody can say they didn't know

Also answers the question people actually ask: "is it fair to refresh the
baseline?" Rule: only after an INTENDED change has landed on main and been
reviewed. Refreshing because the candidate is red is the threshold-editing
move in a different hat.

CLI (repo root):  python explain.py [--registry R] [--baseline B] [--candidate C]
Exit code mirrors the gate (0 PROMOTE, 1 BLOCK, 2 bad input) so it can stand
in for promote.py in a CI step that wants the explanation in the log.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from compare import Verdict, decide            # noqa: E402
from promote import (extract_scores, load_registry, manifest_mismatch,  # noqa: E402
                     registry_hash_mismatch)

THEATER = (
    "What NOT to do (each turns a red gate green without fixing anything, and "
    "the diff lint will demand a written justification for it):\n"
    "    - raise/lower the threshold to just past the candidate\n"
    "    - widen noise_band until the regression fits inside it\n"
    "    - downgrade blocking: hard -> soft -> monitor_only\n"
    "    - delete the metric row\n"
    "    - 'refresh the baseline' while the gate is red"
)


def _units(v: float) -> str:
    return f"{v:.4f}"


def explain_verdict(v: Verdict, spec: dict, has_baseline: bool) -> str:
    better = "higher is better" if spec["direction"] == "higher_better" else "lower is better"
    lines = [f"## {v.metric}  [{v.blocking}]  -> {v.status}",
             f"   measures: {spec.get('detects', ['?'])[0]} ({better}); "
             f"threshold {_units(v.threshold)}"]
    r = v.reason

    if r.startswith("metric missing"):
        lines += ["   what happened: the candidate run did not report this metric at all.",
                  "   how far: n/a — there is no number to judge.",
                  "   fix: make the eval emit it again. A missing metric is treated as a",
                  "        failure on purpose: deleting a metric must never be the easy pass."]
    elif r.startswith("non-numeric") or r.startswith("non-finite"):
        lines += [f"   what happened: the score is not a finite number ({r.split('(')[1].split(')')[0]}).",
                  "   how far: n/a — the instrument is broken, not the system under test.",
                  "   fix: repair the scorer. NaN/inf/strings block on every tier, including",
                  "        monitor_only, because `nan < threshold` is False in Python and a",
                  "        naive gate would have passed this silently."]
    elif r.startswith("threshold breach"):
        gap = (v.threshold - v.candidate) if spec["direction"] == "higher_better" \
              else (v.candidate - v.threshold)
        lines += [f"   what happened: ABSOLUTE floor broken. candidate {_units(v.candidate)} "
                  f"vs threshold {_units(v.threshold)}.",
                  f"   how far: {_units(gap)} past the line ({better}).",
                  "   fix: this is the bar the team set in a reviewed registry. The change",
                  "        under test made the system worse than that bar; find the change.",
                  "        If the bar itself is wrong, that is a separate reviewed PR with a",
                  "        justification in evals/registry_changes.yaml — not a tweak here."]
    elif r.startswith("regression beyond band"):
        delta = v.candidate - (v.baseline_mean or 0.0)
        lines += [f"   what happened: RELATIVE drop vs baseline. candidate {_units(v.candidate)} "
                  f"vs baseline centre {_units(v.baseline_mean or 0.0)}, band ±{_units(v.band)}.",
                  f"   how far: moved {_units(delta)}; anything beyond ±{_units(v.band)} is "
                  f"outside measured noise.",
                  "   fix: the threshold is fine — the system got worse than it was. Diff the",
                  "        change set against the baseline commit. If you believe this is noise,",
                  "        the honest test is MORE baseline runs (data), not a wider band (guess).",
                  "   is a baseline refresh fair here? Only if an INTENDED change already landed",
                  "        on main and was reviewed. Refreshing because this run is red is the",
                  "        threshold-editing move in a different hat."]
    else:
        lines += [f"   what happened: {r}"]
    if not has_baseline and v.status != "BLOCK":
        lines += ["   note: no baseline — regression detection is OFF; only the absolute",
                  "         threshold was judged. Run /eval-baseline before trusting this."]
    return "\n".join(lines)


def explain(registry: list[dict], scores: dict, baseline: dict | None) -> tuple[str, str]:
    """(decision, text). Same decision the gate makes."""
    decision, verdicts = decide(registry, scores, baseline)
    specs = {s["name"]: s for s in registry}
    out = [f"DECISION: {decision}"]
    bad = [v for v in verdicts if v.status != "PASS"]
    if not bad:
        out.append("Every metric passed its threshold" +
                   (" and sat inside its noise band." if baseline else
                    " (no baseline: regression detection OFF)."))
    for v in bad:
        out.append("")
        out.append(explain_verdict(v, specs[v.metric], baseline is not None))
    if any(v.status == "BLOCK" for v in bad):
        out += ["", THEATER]
    warns = [v for v in bad if v.status == "WARN"]
    if warns:
        out += ["", f"{len(warns)} soft WARN(s): these do not block, but they need a human",
                "decision recorded somewhere a reviewer will see — a shrug is not a decision."]
    return decision, "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--registry", default="evals/registry.yaml")
    ap.add_argument("--baseline", default="evals/baseline.json")
    ap.add_argument("--candidate", default="evals/candidate.json")
    args = ap.parse_args(argv)

    bp, cp, rp = Path(args.baseline), Path(args.candidate), Path(args.registry)
    baseline = json.loads(bp.read_text()) if bp.exists() else None
    if not cp.exists():
        print(f"FAIL: candidate not found: {cp}", file=sys.stderr); return 2
    raw = json.loads(cp.read_text())
    try:
        scores = extract_scores(raw, args.candidate)
        registry = load_registry(rp)
    except (ValueError, FileNotFoundError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr); return 2

    # same pre-checks as promote.py, explained
    stale = manifest_mismatch(raw, baseline)
    if stale:
        print("DECISION: BLOCK (before judging any metric)\n"
              f"   {stale}\n   fix: re-run the baseline AND candidate against the same "
              "registry/dataset; a baseline from a different setup gates nothing.")
        return 1
    tampered = registry_hash_mismatch(raw, rp) if rp.exists() else None
    if tampered:
        print("DECISION: BLOCK (before judging any metric)\n"
              f"   {tampered}\n   fix: the registry on disk is not the one this candidate "
              "was produced under. Re-run the eval against the current registry. If the "
              "registry change was deliberate, it needs a justification "
              "(evals/registry_changes.yaml) and a re-run — not a bypass.")
        return 1

    decision, text = explain(registry, scores, baseline)
    print(text)
    return 0 if decision == "PROMOTE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
