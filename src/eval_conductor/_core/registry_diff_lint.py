"""IE-06b: registry DIFF-justification lint — a VALID edit cannot weaken a
gate without a paper trail.

registry_lint.py (IE-06) catches a registry that is structurally wrong: a
typo'd enum (`direction: lower_beter`), an unknown key, a non-finite
threshold. It cannot catch the more dangerous move, because every value
involved is individually legal:

    direction: higher_better  ->  lower_better      # inverts the gate
    threshold: 0.92           ->  0.80              # lowers the bar
    blocking:  hard           ->  soft              # red gate -> warning
    noise_band: 0.02          ->  0.20              # 10x more slack
    (delete the whole row)                          # removes the gate

Each passes schema lint. Each turns a red gate green. This is the exact
thing "never edit a threshold to turn a red gate green" forbids — and a
rule a human has to remember is a rule that gets forgotten under deadline.

This lint makes the rule mechanical. It diffs the NEW registry against an
OLD one (a git ref, by default the merge-base with the main branch) and
splits every change into:

  - STRENGTHENING or NEUTRAL  (harder to pass, or metadata) -> allowed silently
  - WEAKENING                 (easier to pass)              -> requires a
    justification, keyed to the metric, in evals/registry_changes.yaml

A weakening change with no justification -> exit 2, naming the metric and
exactly what got weaker. Fail-closed, like every other gate here.

What "weakening" means, per field (direction-aware):
  direction  any change            -> WEAKENING (inverting a gate is the
                                      canonical attack; even a correction
                                      needs the paper trail)
  threshold  higher_better: lowered | lower_better: raised -> WEAKENING
             (the opposite tightens the gate -> allowed)
  blocking   hard > soft > monitor_only; any move DOWN     -> WEAKENING
  noise_band widened (increased)                           -> WEAKENING
  online     true -> false (gate stops running in prod)    -> WEAKENING
  removed    a metric row deleted                          -> WEAKENING
  added      a new metric row                              -> NEUTRAL (safe)
  renamed    handled as remove(old)+add(new): the removal is WEAKENING,
             so a rename used to smuggle a weaker gate still trips the lint.
  name/level/pillar/method/detects/judge_prompt changes    -> NEUTRAL

What this lint deliberately does NOT do: judge whether a supplied
justification is *true*. It enforces that one EXISTS, is non-placeholder,
and is committed next to the change where a reviewer and git blame can see
it. Truth is the reviewer's job; this removes the "I didn't notice the
gate moved" excuse.

Justifications file (evals/registry_changes.yaml), keyed by metric name:

    task_success_rate: >
      Threshold 0.92->0.90 after dataset v3 added 40 harder adversarial
      cases; equivalent bar on the harder set. See PR #123.

CLI:
  python registry_diff_lint.py [--registry PATH] [--base GITREF]
                               [--justifications PATH] [--old PATH]
  exit 0  no weakening, or every weakening is justified
  exit 2  unjustified weakening, or inputs unreadable (fail-closed)

--old PATH compares against a file instead of git (used by tests and by
anyone not in a git repo). Without it, the OLD registry is read from
`git show <base>:<registry>`; if the registry did not exist at base (brand
new gate) there is nothing to weaken and the lint passes.
"""
from __future__ import annotations

import argparse
import math
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

# Reused placeholder detector — same bar the conductor holds evidence to.
_PLACEHOLDERS = {"", "todo", "tbd", "tba", "n/a", "na", "fixme", "xxx", "..."}
_BLOCKING_RANK = {"monitor_only": 0, "soft": 1, "hard": 2}


@dataclass
class Change:
    metric: str
    field: str          # direction|threshold|blocking|noise_band|online|row
    old: object
    new: object
    kind: str           # WEAKENING | STRENGTHENING | NEUTRAL
    detail: str


def _num(v: object) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    f = float(v)
    return f if math.isfinite(f) else None


def _by_name(rows: list) -> dict:
    out = {}
    for r in rows:
        if isinstance(r, dict) and isinstance(r.get("name"), str) and r["name"]:
            out[r["name"]] = r
    return out


def _classify_threshold(direction: str, old: object, new: object) -> Change | None:
    o, n = _num(old), _num(new)
    if o is None or n is None or o == n:
        return None
    # higher_better: a LOWER threshold is an easier bar -> weaker.
    # lower_better:  a HIGHER threshold is an easier bar -> weaker.
    if direction == "higher_better":
        weaker = n < o
    elif direction == "lower_better":
        weaker = n > o
    else:
        # unknown/absent direction: cannot prove it tightened -> fail closed.
        weaker = True
    kind = "WEAKENING" if weaker else "STRENGTHENING"
    return Change("", "threshold", old, new, kind,
                  f"threshold {o} -> {n} ({direction or 'direction?'})")


def diff_rows(old_row: dict, new_row: dict) -> list[Change]:
    """Field-level changes between two rows of the SAME metric name."""
    changes: list[Change] = []
    name = new_row.get("name", old_row.get("name", "?"))

    # direction: any change is weakening (gate inversion is the headline risk)
    od, nd = old_row.get("direction"), new_row.get("direction")
    if od != nd:
        changes.append(Change(name, "direction", od, nd, "WEAKENING",
                              f"direction {od!r} -> {nd!r} — gate semantics changed"))

    # threshold: weakening is direction-dependent; judge against the NEW
    # direction (the gate a candidate will actually face after this edit).
    thr = _classify_threshold(nd if isinstance(nd, str) else "",
                              old_row.get("threshold"), new_row.get("threshold"))
    if thr is not None:
        thr.metric = name
        changes.append(thr)

    # blocking tier: moving down the ladder weakens enforcement
    ob, nb = old_row.get("blocking"), new_row.get("blocking")
    if ob != nb:
        ro, rn = _BLOCKING_RANK.get(ob, -1), _BLOCKING_RANK.get(nb, -1)
        kind = "WEAKENING" if rn < ro else "STRENGTHENING"
        changes.append(Change(name, "blocking", ob, nb, kind,
                              f"blocking {ob!r} -> {nb!r}"))

    # noise_band: a wider band swallows larger regressions -> weaker
    oban, nban = _num(old_row.get("noise_band")), _num(new_row.get("noise_band"))
    if oban is not None and nban is not None and oban != nban:
        kind = "WEAKENING" if nban > oban else "STRENGTHENING"
        changes.append(Change(name, "noise_band", old_row.get("noise_band"),
                              new_row.get("noise_band"), kind,
                              f"noise_band {oban} -> {nban}"))

    # online: a gate that stops running online stops catching prod regressions
    oo, no = old_row.get("online"), new_row.get("online")
    if oo != no:
        kind = "WEAKENING" if (oo is True and no is False) else "NEUTRAL"
        changes.append(Change(name, "online", oo, no, kind,
                              f"online {oo!r} -> {no!r}"))

    return changes


def diff_registries(old_rows: list, new_rows: list) -> list[Change]:
    """Every semantic change from old_rows to new_rows, classified.

    Rows are matched by `name`. A name present only in old is a removed gate
    (WEAKENING); a name present only in new is an added gate (NEUTRAL). A
    rename therefore shows up as remove(old)+add(new) — the removal trips the
    lint, so you cannot launder a weaker gate through a rename.
    """
    old_by, new_by = _by_name(old_rows), _by_name(new_rows)
    changes: list[Change] = []
    for name in sorted(old_by.keys() | new_by.keys()):
        if name in old_by and name not in new_by:
            changes.append(Change(name, "row", "present", "removed", "WEAKENING",
                                  "metric removed — a deleted gate cannot block"))
        elif name in new_by and name not in old_by:
            changes.append(Change(name, "row", "absent", "added", "NEUTRAL",
                                  "new metric added"))
        else:
            changes.extend(diff_rows(old_by[name], new_by[name]))
    return changes


def _valid_justification(j: object) -> bool:
    return isinstance(j, str) and j.strip().lower() not in _PLACEHOLDERS


def lint_diff(old_rows: list, new_rows: list, justifications: dict) -> list[str]:
    """Return an error per unjustified WEAKENING change; [] means clean.

    One valid justification keyed to a metric covers every weakening change
    to that metric in this diff — the reviewer sees each change listed and
    the single reason behind them. Strengthening and neutral changes never
    require anything.
    """
    errors: list[str] = []
    weakening = [c for c in diff_registries(old_rows, new_rows)
                 if c.kind == "WEAKENING"]
    justifications = justifications or {}
    for c in weakening:
        if not _valid_justification(justifications.get(c.metric)):
            errors.append(
                f"{c.metric}: {c.detail} — WEAKENS the gate with no "
                f"justification. Add one under {c.metric!r} in "
                f"evals/registry_changes.yaml (a real reason, tied to this "
                f"change, that survives review).")
    return errors


# ----------------------------------------------------------------- CLI glue
def _load_yaml(text: str, source: str):
    import yaml
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise SystemExit(f"FAIL: {source}: not valid YAML — {e}")


def _git_show(ref_path: str) -> str | None:
    """`git show <ref>:<path>`; None if the path didn't exist at that ref."""
    r = subprocess.run(["git", "show", ref_path], capture_output=True, text=True)
    if r.returncode != 0:
        return None
    return r.stdout


def _default_base() -> str:
    """merge-base with origin/main (then main), else HEAD~1, else empty."""
    for target in ("origin/main", "origin/master", "main", "master"):
        r = subprocess.run(["git", "merge-base", "HEAD", target],
                           capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    r = subprocess.run(["git", "rev-parse", "HEAD~1"],
                       capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""


def _as_rows(obj: object, source: str) -> list:
    if obj is None:
        return []
    if not isinstance(obj, list):
        raise SystemExit(f"FAIL: {source}: registry must be a list, got "
                         f"{type(obj).__name__}")
    return obj


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--registry", default="evals/registry.yaml",
                    help="the NEW registry (working tree)")
    ap.add_argument("--justifications", default="evals/registry_changes.yaml")
    ap.add_argument("--base", default=None,
                    help="git ref for the OLD registry (default: merge-base "
                         "with the main branch)")
    ap.add_argument("--old", default=None,
                    help="compare against this file instead of git "
                         "(skips git entirely)")
    args = ap.parse_args(argv)

    new_path = Path(args.registry)
    if not new_path.exists():
        print(f"FAIL: {new_path} not found — run /eval-init first", file=sys.stderr)
        return 2
    new_rows = _as_rows(_load_yaml(new_path.read_text(), str(new_path)), str(new_path))

    # OLD registry: file mode, or git mode.
    if args.old is not None:
        op = Path(args.old)
        if not op.exists():
            print(f"FAIL: --old {op} not found", file=sys.stderr)
            return 2
        old_rows = _as_rows(_load_yaml(op.read_text(), str(op)), str(op))
    else:
        base = args.base or _default_base()
        if not base:
            print("note: no git base found (shallow clone or first commit) — "
                  "nothing to diff against; pass --old to compare a file.")
            return 0
        old_text = _git_show(f"{base}:{args.registry}")
        if old_text is None:
            print(f"note: {args.registry} did not exist at {base[:12]} — "
                  f"brand-new gate, nothing to weaken.")
            return 0
        old_rows = _as_rows(_load_yaml(old_text, f"{base}:{args.registry}"),
                            f"{base}:{args.registry}")

    jpath = Path(args.justifications)
    justifications = {}
    if jpath.exists():
        loaded = _load_yaml(jpath.read_text(), str(jpath))
        if isinstance(loaded, dict):
            justifications = loaded
        elif loaded is not None:
            print(f"FAIL: {jpath} must be a mapping of metric -> justification",
                  file=sys.stderr)
            return 2

    errors = lint_diff(old_rows, new_rows, justifications)
    if errors:
        print(f"IE-06b registry diff lint: {len(errors)} unjustified "
              f"weakening change(s)", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        print("\nnever edit a threshold to turn a red gate green. If the change "
              "is legitimate, write down why.", file=sys.stderr)
        return 2
    print("IE-06b registry diff lint: OK (no unjustified gate weakening)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
