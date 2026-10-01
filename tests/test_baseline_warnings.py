"""Baseline band-trust warnings (F-E1). Pure function, runs standalone."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))

from baseline import band_warnings, build_baseline, RECOMMENDED_RUNS  # noqa: E402


def bl(n, metrics):
    return {"n_runs": n, "metrics": metrics}


def test_low_n_warns():
    w = band_warnings(bl(3, {"acc": {"mean": 0.9, "band_2sigma": 0.02}}))
    assert any("run(s)" in x for x in w)

def test_enough_runs_no_low_n_warning():
    w = band_warnings(bl(RECOMMENDED_RUNS, {"acc": {"mean": 0.9, "band_2sigma": 0.02}}))
    assert not any("high-variance estimate" in x for x in w)

def test_zero_band_warns_when_multi_run():
    w = band_warnings(bl(3, {"acc": {"mean": 0.97, "band_2sigma": 0.0}}))
    assert any("zero-width band" in x for x in w)
    assert any("acc" in x for x in w)

def test_zero_band_not_flagged_for_single_run():
    # n<2 zero bands are already covered by --allow-single's own warning
    w = band_warnings(bl(1, {"acc": {"mean": 0.97, "band_2sigma": 0.0}}))
    assert not any("zero-width band" in x for x in w)

def test_identical_runs_at_n3_produce_zero_band_then_warn():
    # the real trap: three legit-looking runs that happen to match exactly
    baseline = build_baseline([{"scores": {"acc": 0.97}}] * 3)
    assert baseline["metrics"]["acc"]["band_2sigma"] == 0.0
    w = band_warnings(baseline)
    assert any("zero-width band" in x for x in w)
    assert any("run(s)" in x for x in w)  # also flags low N


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
