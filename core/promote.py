"""Release gate CLI: exit 0 = PROMOTE, exit 1 = BLOCK, exit 2 = bad input.

Repo-agnostic: reads the registry, baseline and candidate from the CURRENT
repository (defaults below), judges every registry metric fail-closed, prints
a decision table, and exits with a CI-consumable code.

Defaults (override with flags):
    registry   evals/registry.yaml
    baseline   evals/baseline.json      (optional — threshold-only gating without it)
    candidate  evals/candidate.json

Candidate shapes accepted:
  1. {"manifest": {...}, "scores": {"<metric>": <number>, ...}}   — preferred
  2. {"scores": {...}}                                            — no manifest
  3. {"<metric>": <number>, ...}                                  — flat adapter shape
Anything else fails loudly with exit 2 — never a bare KeyError.

Fail-closed rules (each one exists because a real gate was seen passing bad
runs without it):
  - invalid registry (schema lint)                       -> exit 2
  - NaN / inf / non-numeric score                        -> BLOCK
  - metric missing from candidate                        -> BLOCK
  - baseline carries a manifest and candidate's
    registry_hash/dataset_hash don't match ("stale
    baseline")                                           -> BLOCK before judging
  - hard metric threshold breach or regression beyond
    max(registry noise_band, baseline 2 sigma)           -> BLOCK
  - soft metric breach/regression                        -> WARN (human review)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import numbers
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from compare import decide            # noqa: E402
from registry_lint import lint_registry  # noqa: E402

MANIFEST_KEYS = ("registry_hash", "dataset_hash")
HEX_RE = re.compile(r"[0-9a-f]{8,64}$")


def registry_hash_mismatch(raw: object, registry_path: Path) -> str | None:
    """Verify the candidate's self-reported registry_hash against the ACTUAL
    registry file. Convention: registry_hash = sha256 of the registry file
    (full hexdigest or any prefix >= 8 hex chars). Manifest hashes compared
    only between candidate and baseline are attestations — both can carry the
    same stale value after the registry is edited, so the gate recomputes
    what it can. dataset_hash stays an attestation (the gate cannot know
    your dataset)."""
    cand_manifest = raw.get("manifest") if isinstance(raw, dict) else None
    if not isinstance(cand_manifest, dict):
        return None
    claimed = cand_manifest.get("registry_hash")
    if not isinstance(claimed, str) or not claimed:
        return None
    if not HEX_RE.fullmatch(claimed.lower()):
        return (f"registry_hash {claimed!r} is not a sha256 hex (prefix) of the "
                f"registry file — use sha256 of {registry_path} (>=8 hex chars)")
    actual = hashlib.sha256(registry_path.read_bytes()).hexdigest()
    if not actual.startswith(claimed.lower()):
        return (f"registry_hash mismatch: candidate attests {claimed!r} but "
                f"{registry_path} on disk hashes to {actual[:12]}… — the "
                f"registry changed after this candidate/baseline was produced")
    return None


def load_registry(path: Path) -> list[dict]:
    import yaml
    rows = yaml.safe_load(path.read_text())
    errors = lint_registry(rows)
    if errors:
        raise ValueError("registry lint failed:\n  - " + "\n  - ".join(errors))
    return rows


def extract_scores(raw: object, source: str) -> dict:
    if isinstance(raw, dict) and isinstance(raw.get("scores"), dict):
        return raw["scores"]
    if (isinstance(raw, dict) and raw
            and all(isinstance(v, numbers.Real) for v in raw.values())):
        return raw  # flat adapter shape
    raise ValueError(
        f"{source}: candidate must be {{'scores': {{...}}}} or a flat "
        f"{{metric: number}} object; got {type(raw).__name__}"
    )


def manifest_mismatch(raw: object, baseline: dict | None) -> str | None:
    """Reason string when candidate/baseline manifests don't match, else None."""
    base_manifest = (baseline or {}).get("manifest")
    if not isinstance(base_manifest, dict):
        return None  # nothing to be stale against
    cand_manifest = raw.get("manifest") if isinstance(raw, dict) else None
    if not isinstance(cand_manifest, dict):
        return ("stale baseline: baseline carries a manifest but the candidate "
                "carries none — cannot prove they measured the same "
                "registry/dataset; fail closed")
    diffs = [f"{k}: candidate {cand_manifest.get(k)!r} vs baseline {base_manifest.get(k)!r}"
             for k in MANIFEST_KEYS
             if cand_manifest.get(k) != base_manifest.get(k)]
    if diffs:
        return "stale baseline: manifest mismatch — " + "; ".join(diffs)
    return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--registry", default="evals/registry.yaml")
    ap.add_argument("--baseline", default="evals/baseline.json")
    ap.add_argument("--candidate", default="evals/candidate.json")
    args = ap.parse_args(argv)

    baseline = None
    bp = Path(args.baseline)
    if bp.exists():
        baseline = json.loads(bp.read_text())
    else:
        print("WARNING: no baseline found — gating on thresholds only. "
              "Run the baseline runner before trusting this gate.")

    cp = Path(args.candidate)
    if not cp.exists():
        print(f"FAIL: candidate not found: {cp} — your eval run must write it "
              f"(see evals/candidate.example.json)", file=sys.stderr)
        return 2
    raw = json.loads(cp.read_text())
    try:
        scores = extract_scores(raw, args.candidate)
    except ValueError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 2

    stale = manifest_mismatch(raw, baseline)
    if stale:
        print(f"\nDECISION: BLOCK — {stale}", file=sys.stderr)
        return 1
    rp = Path(args.registry)
    if rp.exists():
        tampered = registry_hash_mismatch(raw, rp)
        if tampered:
            print(f"\nDECISION: BLOCK — {tampered}", file=sys.stderr)
            return 1

    try:
        registry = load_registry(Path(args.registry))
    except FileNotFoundError:
        print(f"FAIL: registry not found: {args.registry} — run /eval-init first",
              file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 2

    decision, verdicts = decide(registry, scores, baseline)

    w = max(len(v.metric) for v in verdicts)
    print(f"\n{'metric'.ljust(w)}  {'block':6} {'cand':>8} {'base':>8} {'band':>7}  status  reason")
    for v in verdicts:
        base_s = f"{v.baseline_mean:.4f}" if v.baseline_mean is not None else "   -  "
        print(f"{v.metric.ljust(w)}  {v.blocking:6} {v.candidate:8.4f} {base_s:>8} "
              f"{v.band:7.4f}  {v.status:6}  {v.reason}")

    warns = [v for v in verdicts if v.status == "WARN"]
    print(f"\nDECISION: {decision}"
          + (f"  ({len(warns)} soft warning(s) -> human review)" if warns else ""))
    return 0 if decision == "PROMOTE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
