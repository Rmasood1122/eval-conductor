"""Gate logic + lint tests for the vendored core. Every fail-closed branch."""
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))

from compare import decide, judge_metric          # noqa: E402
from registry_lint import lint_registry           # noqa: E402

HARD = {"name": "m", "direction": "higher_better", "threshold": 0.9,
        "blocking": "hard", "noise_band": 0.02}
SOFT = {**HARD, "blocking": "soft"}
LOWER = {"name": "lat", "direction": "lower_better", "threshold": 2.0,
         "blocking": "hard", "noise_band": 0.1}


def base(mean, band=0.02):
    return {"mean": mean, "band_2sigma": band}


# --- threshold / regression / band branches --------------------------------
def test_hard_breach_blocks():
    assert judge_metric(HARD, 0.85, base(0.95)).status == "BLOCK"


def test_soft_breach_warns():
    assert judge_metric(SOFT, 0.85, base(0.95)).status == "WARN"


def test_within_band_passes():
    assert judge_metric(HARD, 0.94, base(0.95)).status == "PASS"


def test_regression_beyond_band_blocks():
    assert judge_metric(HARD, 0.91, base(0.95)).status == "BLOCK"


def test_lower_better_all_branches():
    assert judge_metric(LOWER, 2.5, base(1.5, 0.1)).status == "BLOCK"   # breach above
    assert judge_metric(LOWER, 1.55, base(1.5, 0.1)).status == "PASS"   # in band
    assert judge_metric(LOWER, 1.9, base(1.5, 0.1)).status == "BLOCK"   # regression


def test_measured_band_overrides_registry_band():
    assert judge_metric(HARD, 0.91, base(0.95, band=0.05)).status == "PASS"


def test_no_baseline_threshold_only():
    assert judge_metric(HARD, 0.92, None).status == "PASS"
    assert judge_metric(HARD, 0.80, None).status == "BLOCK"


def test_monitor_only_never_blocks_on_thresholds():
    spec = {**HARD, "blocking": "monitor_only"}
    assert judge_metric(spec, 0.1, base(0.95)).status == "PASS"


# --- fail-closed: invalid measurements -------------------------------------
def test_nan_blocks_every_tier():
    for tier in ("hard", "soft", "monitor_only"):
        v = judge_metric({**HARD, "blocking": tier}, float("nan"), base(0.95))
        assert v.status == "BLOCK", tier
        assert "non-finite" in v.reason


def test_inf_blocks_both_directions():
    assert judge_metric(HARD, float("inf"), base(0.95)).status == "BLOCK"
    assert judge_metric(LOWER, float("-inf"), base(1.5, 0.1)).status == "BLOCK"


def test_missing_metric_blocks():
    decision, verdicts = decide([HARD], {}, None)
    assert decision == "BLOCK"
    assert "missing" in verdicts[0].reason


def test_non_numeric_blocks():
    for bad in ("0.99", None, True, [0.99]):
        decision, verdicts = decide([HARD], {"m": bad}, None)
        assert decision == "BLOCK", repr(bad)
        assert "non-numeric" in verdicts[0].reason


def test_decide_aggregation():
    decision, _ = decide([SOFT, LOWER], {"m": 0.85, "lat": 2.5}, None)
    assert decision == "BLOCK"
    decision, _ = decide([SOFT], {"m": 0.85}, None)
    assert decision == "PROMOTE"  # soft warn alone never blocks


# --- registry lint ----------------------------------------------------------
GOOD = {"name": "m1", "level": "L1", "pillar": "quality", "method": "programmatic",
        "detects": ["FM-X"], "direction": "higher_better", "threshold": 0.9,
        "noise_band": 0.02, "blocking": "hard", "online": True}


def row(**over):
    r = dict(GOOD)
    for k, v in over.items():
        if v is ...:
            r.pop(k, None)
        else:
            r[k] = v
    return r


def test_good_row_and_template_pass():
    import yaml
    assert lint_registry([GOOD]) == []
    template = Path(__file__).resolve().parents[1] / "templates/registry.yaml"
    assert lint_registry(yaml.safe_load(template.read_text())) == []


@pytest.mark.parametrize("bad", [
    row(direction="lower_beter"), row(blocking="hardd"), row(level="L9"),
    row(method="vibes"), row(pillar="velocity"), row(threshold=...),
    row(direction=...), row(detects=[]), row(threshold="0.9"),
    row(threshold=float("nan")), row(noise_band=-0.1), row(online="yes"),
    row(name=""), row(surprise=1), row(judge_prompt="p.md"),
])
def test_invalid_rows_fail(bad):
    assert lint_registry([bad])


def test_empty_or_non_list_fails():
    assert lint_registry([]) and lint_registry(None) and lint_registry({"a": 1})


def test_duplicate_names_fail():
    assert lint_registry([GOOD, dict(GOOD)])
