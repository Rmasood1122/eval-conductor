"""Diff-justification lint tests (IE-06b). Pure functions, every branch.

Written as plain assert-functions so they run under pytest AND standalone
(`python test_registry_diff_lint.py`) — the diff lint is a release-blocking
gate, so its own tests must run even where pytest isn't installed.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))

from registry_diff_lint import (  # noqa: E402
    diff_registries, diff_rows, lint_diff, _classify_threshold,
)

HB = {"name": "acc", "direction": "higher_better", "threshold": 0.9,
      "blocking": "hard", "noise_band": 0.02, "online": True}
LB = {"name": "lat", "direction": "lower_better", "threshold": 5.0,
      "blocking": "soft", "noise_band": 0.5, "online": True}


def row(base, **over):
    r = dict(base)
    r.update(over)
    return r


def kinds(changes):
    return {(c.metric, c.field): c.kind for c in changes}


# ---- threshold direction-awareness ----------------------------------------
def test_higher_better_lowering_threshold_weakens():
    c = _classify_threshold("higher_better", 0.92, 0.80)
    assert c.kind == "WEAKENING", c

def test_higher_better_raising_threshold_strengthens():
    c = _classify_threshold("higher_better", 0.80, 0.92)
    assert c.kind == "STRENGTHENING", c

def test_lower_better_raising_threshold_weakens():
    c = _classify_threshold("lower_better", 5.0, 9.0)
    assert c.kind == "WEAKENING", c

def test_lower_better_lowering_threshold_strengthens():
    c = _classify_threshold("lower_better", 9.0, 5.0)
    assert c.kind == "STRENGTHENING", c

def test_unknown_direction_threshold_fails_closed():
    # cannot prove a tightening without a known direction -> treat as weaker
    c = _classify_threshold("", 0.9, 0.95)
    assert c.kind == "WEAKENING", c

def test_equal_threshold_is_no_change():
    assert _classify_threshold("higher_better", 0.9, 0.9) is None


# ---- direction flip (the headline attack) ---------------------------------
def test_direction_flip_is_weakening():
    changes = diff_rows(HB, row(HB, direction="lower_better"))
    assert kinds(changes)[("acc", "direction")] == "WEAKENING"


# ---- blocking tier ladder -------------------------------------------------
def test_hard_to_soft_weakens():
    changes = diff_rows(HB, row(HB, blocking="soft"))
    assert kinds(changes)[("acc", "blocking")] == "WEAKENING"

def test_hard_to_monitor_only_weakens():
    changes = diff_rows(HB, row(HB, blocking="monitor_only"))
    assert kinds(changes)[("acc", "blocking")] == "WEAKENING"

def test_soft_to_hard_strengthens():
    changes = diff_rows(row(HB, blocking="soft"), HB)
    assert kinds(changes)[("acc", "blocking")] == "STRENGTHENING"


# ---- noise band -----------------------------------------------------------
def test_widening_band_weakens():
    changes = diff_rows(HB, row(HB, noise_band=0.20))
    assert kinds(changes)[("acc", "noise_band")] == "WEAKENING"

def test_narrowing_band_strengthens():
    changes = diff_rows(HB, row(HB, noise_band=0.001))
    assert kinds(changes)[("acc", "noise_band")] == "STRENGTHENING"


# ---- online ---------------------------------------------------------------
def test_online_true_to_false_weakens():
    changes = diff_rows(HB, row(HB, online=False))
    assert kinds(changes)[("acc", "online")] == "WEAKENING"

def test_online_false_to_true_is_neutral():
    changes = diff_rows(row(HB, online=False), HB)
    assert kinds(changes)[("acc", "online")] == "NEUTRAL"


# ---- row add / remove / rename --------------------------------------------
def test_removed_metric_weakens():
    changes = diff_registries([HB, LB], [HB])
    assert kinds(changes)[("lat", "row")] == "WEAKENING"

def test_added_metric_is_neutral():
    changes = diff_registries([HB], [HB, LB])
    assert kinds(changes)[("lat", "row")] == "NEUTRAL"

def test_rename_cannot_launder_a_weaker_gate():
    # rename acc->accuracy AND lower its threshold: the rename shows up as
    # remove(acc)+add(accuracy); the removal is WEAKENING, so it's caught.
    new = [row(HB, name="accuracy", threshold=0.5)]
    changes = diff_registries([HB], new)
    assert kinds(changes)[("acc", "row")] == "WEAKENING"      # old removed
    assert kinds(changes)[("accuracy", "row")] == "NEUTRAL"   # new added


# ---- lint_diff: justification enforcement ---------------------------------
def test_unjustified_weakening_errors():
    errs = lint_diff([HB], [row(HB, threshold=0.5)], {})
    assert len(errs) == 1 and "acc" in errs[0]

def test_justified_weakening_passes():
    errs = lint_diff([HB], [row(HB, threshold=0.5)],
                     {"acc": "dataset v3 added harder cases; see PR #123"})
    assert errs == []

def test_placeholder_justification_rejected():
    for bad in ("", "   ", "TODO", "tbd", "...", "n/a"):
        errs = lint_diff([HB], [row(HB, threshold=0.5)], {"acc": bad})
        assert len(errs) == 1, repr(bad)

def test_strengthening_needs_no_justification():
    errs = lint_diff([HB], [row(HB, threshold=0.99)], {})
    assert errs == []

def test_one_justification_covers_multiple_weakenings_same_metric():
    new = [row(HB, threshold=0.5, blocking="soft", noise_band=0.5)]
    errs = lint_diff([HB], new, {"acc": "deliberate relaxation, reviewed, PR #7"})
    assert errs == []

def test_no_changes_no_errors():
    assert lint_diff([HB, LB], [HB, LB], {}) == []


def _run_all():
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"  PASS {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL {fn.__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_all())
