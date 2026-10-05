"""IE-06: registry schema validator — a typo cannot invert or downgrade a gate.

The registry is the single source of truth for release gates, which makes it the
single most attractive edit path for eval theater (FM-03: `direction: lower_beter`
silently disables a gate; FM-12: an unknown key rides along unread). This lint
fails closed: any structural error refuses the whole registry, so run_suite and
promote refuse to run against it.

Enforced (per consumer0_eval_spec IE-06):
  - registry is a non-empty list of mappings
  - required keys present, no unknown keys
  - direction / blocking / level / method / pillar are enum-checked
  - detects is a non-empty list of non-empty strings
  - threshold finite number; noise_band finite number >= 0; online is bool
  - judge_prompt only allowed on llm_judge rows
  - metric names unique

NOT covered here (IE-06b, CI process lint, still to build): a registry/threshold
diff without a linked justification. Schema lint cannot see intent — flipping
`higher_better` to the other *valid* enum value passes schema and must be caught
by the diff-justification lint + review, per "never edit a threshold to turn a
red gate green".

CLI: `python registry_lint.py [path]` — exit 0 clean, exit 2 with
every error printed otherwise. Wired into load_registry(), so an invalid
registry also hard-fails the suite runner and the promote gate (exit 2).
"""
from __future__ import annotations

import math
import numbers
import sys
from pathlib import Path

DIRECTIONS = {"higher_better", "lower_better"}
BLOCKING = {"hard", "soft", "monitor_only"}
LEVELS = {"L0", "L1", "L2", "L3", "L4", "L5"}
METHODS = {"programmatic", "llm_judge", "human"}
PILLARS = {"quality", "safety", "ops"}

REQUIRED_KEYS = {"name", "level", "pillar", "method", "detects",
                 "direction", "threshold", "noise_band", "blocking", "online"}
OPTIONAL_KEYS = {"judge_prompt", "band_method"}
ALLOWED_KEYS = REQUIRED_KEYS | OPTIONAL_KEYS
BAND_METHODS = {"sigma", "mad"}


def _is_number(v: object) -> bool:
    return isinstance(v, numbers.Real) and not isinstance(v, bool)


def lint_registry(rows: object) -> list[str]:
    """Return every schema error found; [] means the registry is valid."""
    errors: list[str] = []
    if not isinstance(rows, list) or not rows:
        return [f"registry must be a non-empty list, got {type(rows).__name__}"]

    seen: set[str] = set()
    for i, row in enumerate(rows):
        where = f"row {i}"
        if not isinstance(row, dict):
            errors.append(f"{where}: must be a mapping, got {type(row).__name__}")
            continue
        name = row.get("name")
        if isinstance(name, str) and name:
            where = f"row {i} ({name})"
            if name in seen:
                errors.append(f"{where}: duplicate metric name")
            seen.add(name)
        else:
            errors.append(f"{where}: name must be a non-empty string")

        missing = REQUIRED_KEYS - row.keys()
        if missing:
            errors.append(f"{where}: missing required keys {sorted(missing)}")
        unknown = row.keys() - ALLOWED_KEYS
        if unknown:
            errors.append(f"{where}: unknown keys {sorted(unknown)} — "
                          f"unread keys are how gate edits hide")

        for key, allowed in (("direction", DIRECTIONS), ("blocking", BLOCKING),
                             ("level", LEVELS), ("method", METHODS),
                             ("pillar", PILLARS)):
            if key in row and row[key] not in allowed:
                errors.append(f"{where}: {key}={row[key]!r} not in {sorted(allowed)}")

        detects = row.get("detects")
        if "detects" in row and (
                not isinstance(detects, list) or not detects
                or not all(isinstance(d, str) and d for d in detects)):
            errors.append(f"{where}: detects must be a non-empty list of "
                          f"non-empty strings, got {detects!r}")

        thr = row.get("threshold")
        if "threshold" in row and (not _is_number(thr) or not math.isfinite(thr)):
            errors.append(f"{where}: threshold must be a finite number, got {thr!r}")
        band = row.get("noise_band")
        if "noise_band" in row and (
                not _is_number(band) or not math.isfinite(band) or band < 0):
            errors.append(f"{where}: noise_band must be a finite number >= 0, "
                          f"got {band!r}")
        if "online" in row and not isinstance(row["online"], bool):
            errors.append(f"{where}: online must be a bool, got {row['online']!r}")
        if "judge_prompt" in row and row.get("method") != "llm_judge":
            errors.append(f"{where}: judge_prompt only allowed on llm_judge rows")
        if "band_method" in row and row["band_method"] not in BAND_METHODS:
            errors.append(f"{where}: band_method={row['band_method']!r} not in "
                          f"{sorted(BAND_METHODS)}")
    return errors


def main(argv: list[str]) -> int:
    import yaml
    default = Path.cwd() / "evals/registry.yaml"
    path = Path(argv[1]) if len(argv) > 1 else default
    errors = lint_registry(yaml.safe_load(path.read_text()))
    if errors:
        print(f"IE-06 registry lint: {len(errors)} error(s) in {path}", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 2
    print(f"IE-06 registry lint: OK ({path})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
