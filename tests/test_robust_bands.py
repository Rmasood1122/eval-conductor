"""F-E2: robust (MAD) bands. Runs standalone or under pytest."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))

from baseline import build_baseline, robust_stats, MAD_K, MAD_SCALE  # noqa: E402
from compare import judge_metric                                      # noqa: E402
from registry_lint import lint_registry                               # noqa: E402

GOOD = {"name": "m1", "level": "L1", "pillar": "quality", "method": "programmatic",
        "detects": ["FM-X"], "direction": "higher_better", "threshold": 0.5,
        "noise_band": 0.0, "blocking": "hard", "online": True}


def runs(*vals):
    return [{"scores": {"acc": v}} for v in vals]


def test_robust_stats_basic():
    med, mad = robust_stats([0.90, 0.91, 0.92, 0.93, 0.94])
    assert med == 0.92
    assert abs(mad - 0.01) < 1e-9


def test_robust_stats_ignores_single_outlier():
    # one wild run: sigma explodes, MAD does not
    med, mad = robust_stats([0.95, 0.95, 0.96, 0.95, 0.30])
    assert med == 0.95
    assert abs(mad - 0.0) < 1e-9


def test_baseline_writes_both_bands():
    b = build_baseline(runs(0.95, 0.96, 0.95, 0.97, 0.30))
    m = b["metrics"]["acc"]
    for k in ("mean", "sigma", "band_2sigma", "median", "mad", "band_mad"):
        assert k in m, k
    assert m["band_mad"] == MAD_K * MAD_SCALE * m["mad"]


def test_outlier_hides_regression_under_sigma_but_not_mad():
    """The motivating case: one bad baseline run inflates sigma so a real
    regression sits inside the 2-sigma band. The MAD band still catches it."""
    b = build_baseline(runs(0.95, 0.96, 0.95, 0.97, 0.30))["metrics"]["acc"]
    cand = 0.85   # a real 10-point drop from the typical 0.95
    spec_sigma = {**GOOD, "name": "acc"}                        # default sigma
    spec_mad = {**GOOD, "name": "acc", "band_method": "mad"}
    v_sigma = judge_metric(spec_sigma, cand, b)
    v_mad = judge_metric(spec_mad, cand, b)
    assert v_sigma.status == "PASS", (v_sigma.band, v_sigma.reason)  # swallowed
    assert v_mad.status == "BLOCK", (v_mad.band, v_mad.reason)       # caught
    assert v_mad.baseline_mean == b["median"]


def test_mad_falls_back_to_sigma_on_old_baseline():
    old = {"mean": 0.95, "band_2sigma": 0.02}   # pre-F-E2 baseline shape
    v = judge_metric({**GOOD, "name": "acc", "band_method": "mad"}, 0.94, old)
    assert v.status == "PASS" and v.baseline_mean == 0.95


def test_lint_accepts_band_method_and_rejects_unknown():
    assert lint_registry([{**GOOD, "band_method": "mad"}]) == []
    assert lint_registry([{**GOOD, "band_method": "sigma"}]) == []
    assert lint_registry([{**GOOD, "band_method": "trimmed"}])


def test_template_registry_lints():
    import yaml
    t = Path(__file__).resolve().parents[1] / "templates/registry.yaml"
    assert lint_registry(yaml.safe_load(t.read_text())) == []


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
