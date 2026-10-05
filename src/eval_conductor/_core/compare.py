"""Gate logic: compare candidate vs baseline under the registry -> PROMOTE/BLOCK.

Pure functions so tests/test_l0_gate.py can verify every branch. Rules:
  - hard metric breaching its threshold                  -> BLOCK
  - hard metric regressing beyond noise band vs baseline -> BLOCK
  - soft metric breach/regression                        -> WARN (human review)
  - monitor_only                                         -> report only
  - NaN / non-finite / non-numeric score                 -> BLOCK, always (IE-07)
Band used = max(registry noise_band, measured band from baseline), where the
measured band is band_2sigma (default) or band_mad when the registry row says
`band_method: mad` (F-E2: robust for bounded/pass-rate metrics; centre is the
median instead of the mean — Verdict.baseline_mean then holds the median).

Fail-closed rationale (IE-07, FM-02/FM-05): NaN compares False against every
threshold, so before this rule a NaN score sailed through both the breach and
the regression checks and PASSed silently. A score that isn't a finite number
is not a measurement; it blocks regardless of the metric's blocking tier —
same policy as a metric missing from the candidate run.
"""
from __future__ import annotations

import math
import numbers
from dataclasses import dataclass


@dataclass
class Verdict:
    metric: str
    blocking: str
    candidate: float
    baseline_mean: float | None
    threshold: float
    band: float
    status: str      # PASS | WARN | BLOCK
    reason: str


def judge_metric(spec: dict, candidate: float, base: dict | None) -> Verdict:
    name = spec["name"]
    direction = spec["direction"]
    threshold = float(spec["threshold"])
    blocking = spec.get("blocking", "soft")
    band = float(spec.get("noise_band", 0.0))
    if not math.isfinite(candidate):
        # IE-07: NaN/inf is an invalid measurement, never a passing one.
        # Blocks even monitor_only rows — the instrument itself is broken.
        return Verdict(name, blocking, candidate, None, threshold, band, "BLOCK",
                       f"non-finite score ({candidate}) — invalid measurement, fail closed")
    base_mean = None
    if base is not None:
        method = spec.get("band_method", "sigma")
        if method == "mad":
            # F-E2 robust path: centre on the median, band from MAD. A baseline
            # written before band_mad existed has no robust fields -> fall
            # back to the sigma pair rather than silently gating on zero.
            if "median" in base and "band_mad" in base:
                base_mean = float(base["median"])
                band = max(band, float(base["band_mad"]))
            else:
                base_mean = float(base["mean"])
                band = max(band, float(base.get("band_2sigma", 0.0)))
        else:
            base_mean = float(base["mean"])
            band = max(band, float(base.get("band_2sigma", 0.0)))

    higher = direction == "higher_better"
    breach = candidate < threshold if higher else candidate > threshold
    regression = False
    if base_mean is not None:
        delta = candidate - base_mean
        regression = (delta < -band) if higher else (delta > band)

    if blocking == "monitor_only":
        return Verdict(name, blocking, candidate, base_mean, threshold, band,
                       "PASS", "monitor_only")
    if breach:
        status = "BLOCK" if blocking == "hard" else "WARN"
        return Verdict(name, blocking, candidate, base_mean, threshold, band, status,
                       f"threshold breach: {candidate:.4f} vs {threshold} ({direction})")
    if regression:
        status = "BLOCK" if blocking == "hard" else "WARN"
        return Verdict(name, blocking, candidate, base_mean, threshold, band, status,
                       f"regression beyond band: {candidate:.4f} vs baseline "
                       f"{base_mean:.4f} (band {band:.4f})")
    return Verdict(name, blocking, candidate, base_mean, threshold, band, "PASS", "ok")


def decide(registry: list[dict], candidate_scores: dict, baseline: dict | None):
    verdicts = []
    for spec in registry:
        name = spec["name"]
        if name not in candidate_scores:
            verdicts.append(Verdict(name, spec.get("blocking", "soft"), float("nan"),
                                    None, float(spec["threshold"]), 0.0, "BLOCK",
                                    "metric missing from candidate run"))
            continue
        base = (baseline or {}).get("metrics", {}).get(name) if baseline else None
        raw_value = candidate_scores[name]
        if isinstance(raw_value, bool) or not isinstance(raw_value, numbers.Real):
            # IE-07: a non-numeric score (str "0.99", null, bool, list…) is not
            # a measurement, even when it would coerce cleanly — fail closed.
            verdicts.append(Verdict(name, spec.get("blocking", "soft"), float("nan"),
                                    None, float(spec["threshold"]), 0.0, "BLOCK",
                                    f"non-numeric score ({raw_value!r}) — fail closed"))
            continue
        verdicts.append(judge_metric(spec, float(raw_value), base))
    decision = "BLOCK" if any(v.status == "BLOCK" for v in verdicts) else "PROMOTE"
    return decision, verdicts
