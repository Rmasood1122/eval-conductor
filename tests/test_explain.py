"""/eval-explain: must never disagree with the gate, and must name the theater."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))

from compare import decide        # noqa: E402
from explain import explain       # noqa: E402

HARD = {"name": "acc", "direction": "higher_better", "threshold": 0.9,
        "blocking": "hard", "noise_band": 0.02, "detects": ["FM-Q"]}
SOFT = {**HARD, "name": "lat", "direction": "lower_better", "threshold": 2.0,
        "blocking": "soft", "noise_band": 0.1}
BASE = {"metrics": {"acc": {"mean": 0.95, "band_2sigma": 0.02},
                    "lat": {"mean": 1.5, "band_2sigma": 0.1}}}

CASES = [
    ({"acc": 0.96, "lat": 1.5}, BASE),          # clean PROMOTE
    ({"acc": 0.85, "lat": 1.5}, BASE),          # hard breach
    ({"acc": 0.91, "lat": 1.5}, BASE),          # regression beyond band
    ({"acc": 0.96, "lat": 2.5}, BASE),          # soft breach -> WARN, PROMOTE
    ({"acc": float("nan"), "lat": 1.5}, BASE),  # non-finite
    ({"lat": 1.5}, BASE),                       # missing metric
    ({"acc": "0.99", "lat": 1.5}, BASE),        # non-numeric
    ({"acc": 0.92, "lat": 1.5}, None),          # no baseline, threshold-only
]


def test_explain_decision_always_equals_gate_decision():
    for scores, base in CASES:
        gate, _ = decide([HARD, SOFT], scores, base)
        mine, _ = explain([HARD, SOFT], scores, base)
        assert gate == mine, (scores, gate, mine)


def test_breach_is_called_absolute_with_distance():
    _, t = explain([HARD], {"acc": 0.85}, BASE)
    assert "ABSOLUTE floor broken" in t and "0.0500 past the line" in t


def test_regression_is_called_relative_with_band():
    _, t = explain([HARD], {"acc": 0.91}, BASE)
    assert "RELATIVE drop vs baseline" in t and "±0.0200" in t
    assert "is a baseline refresh fair here?" in t


def test_block_lists_the_theater_moves():
    _, t = explain([HARD], {"acc": 0.85}, BASE)
    for move in ("threshold", "noise_band", "hard -> soft", "delete the metric",
                 "refresh the baseline"):
        assert move in t, move


def test_pass_does_not_lecture():
    _, t = explain([HARD], {"acc": 0.96}, BASE)
    assert "What NOT to do" not in t and "DECISION: PROMOTE" in t


def test_soft_warn_asks_for_a_recorded_decision():
    d, t = explain([SOFT], {"lat": 2.5}, BASE)
    assert d == "PROMOTE" and "soft WARN" in t and "a shrug is not a decision" in t


def test_nan_explains_the_python_trap():
    _, t = explain([HARD], {"acc": float("nan")}, BASE)
    assert "nan < threshold" in t and "monitor_only" in t


def test_no_baseline_is_flagged():
    _, t = explain([HARD], {"acc": 0.92}, None)
    assert "regression detection OFF" in t


def _run_all():
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn(); print(f"  PASS {fn.__name__}")
        except AssertionError as e:
            failed += 1; print(f"  FAIL {fn.__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_all())
