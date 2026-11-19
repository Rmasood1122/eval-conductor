"""Fail-closed gaps found in the 1.4.3 audit. Every test here failed on 1.4.3 except the ones marked as guards.

- eval-prove painted a green "proven" badge for a suite that was not all
  passing (0/3 on a first run read "proven 0/3", brightgreen).
- Marking failing tests as skipped kept the pass rate at 1.0 and the test count
  unchanged, so a regression was laundered into PROMOTE.
- JUnit summary attributes were trusted over the <testcase> elements.
- `prereg check --require-seal` accepted an UNSIGNED head seal even when the
  key was supplied, so a rewritten seal passed.
- A baseline with NaN/inf/negative bands, or missing a gated metric, judged
  PROMOTE instead of failing closed.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

import prereg  # noqa: E402
import wedge  # noqa: E402
from adapters import AdapterError, junit_scores  # noqa: E402
from compare import decide  # noqa: E402

KEY = bytes.fromhex("ab" * 32)


def _suite(tmp, cases, attrs=None, name="junit.xml"):
    """cases: list of 'pass' | 'fail' | 'error' | 'skip'."""
    body = []
    for i, c in enumerate(cases):
        inner = {"pass": "", "fail": "<failure/>", "error": "<error/>",
                 "skip": "<skipped/>"}[c]
        body.append(f'<testcase classname="t" name="c{i}">{inner}</testcase>')
    if attrs is None:
        attrs = {"tests": len(cases),
                 "failures": cases.count("fail"), "errors": cases.count("error"),
                 "skipped": cases.count("skip")}
    a = " ".join(f'{k}="{v}"' for k, v in attrs.items())
    p = tmp / name
    p.write_text(f'<testsuite name="s" {a}>{"".join(body)}</testsuite>')
    return p


def _prove(tmp, junit, **kw):
    return wedge.run(work_dir=tmp, junit_path=junit,
                     receipts_dir=tmp / "evals" / "receipts",
                     baseline_file=tmp / "evals" / ".wedge-baseline.json",
                     key_path=tmp / "evals" / ".receipt-key", **kw)


# ------------------------------------------------------------------ badge
def test_first_run_with_failures_is_not_a_green_proof(tmp_path):
    res = _prove(tmp_path, _suite(tmp_path, ["fail", "fail", "fail"]))
    assert "brightgreen" not in res["badge"]
    assert "proven" not in res["badge"]


# guard: must keep passing
def test_all_passing_still_green(tmp_path):
    res = _prove(tmp_path, _suite(tmp_path, ["pass"] * 4))
    assert "proven%204%2F4-brightgreen" in res["badge"]


# ------------------------------------------------------------------ skips
def test_skipping_failing_tests_does_not_launder_a_regression(tmp_path):
    assert _prove(tmp_path, _suite(tmp_path, ["pass"] * 5))["decision"] == "PROMOTE"
    # two tests now fail; mark them skipped instead of fixing them
    res = _prove(tmp_path, _suite(tmp_path, ["pass"] * 3 + ["skip"] * 2))
    assert res["decision"] == "BLOCK"
    assert any(v["metric"] == "test_executed" and v["status"] == "BLOCK"
               for v in res["verdicts"])


def test_badge_counts_skipped_tests_as_not_passed(tmp_path):
    res = _prove(tmp_path, _suite(tmp_path, ["pass"] * 4 + ["skip"]))
    assert "4%2F5" in res["badge"]
    assert "brightgreen" not in res["badge"]


def test_scores_expose_executed_and_skipped(tmp_path):
    s = junit_scores(_suite(tmp_path, ["pass", "fail", "skip"]))
    assert s["test_executed"] == 2 and s["test_skipped"] == 1


# ------------------------------------------------------------------ junit
def test_missing_failures_attribute_does_not_read_as_all_pass(tmp_path):
    p = _suite(tmp_path, ["pass", "fail", "fail"], attrs={"tests": 3})
    assert junit_scores(p)["test_pass_rate"] < 1.0


def test_summary_attributes_cannot_overrule_testcases(tmp_path):
    p = _suite(tmp_path, ["fail"] * 4,
               attrs={"tests": 4, "failures": 0, "errors": 0, "skipped": 0})
    assert junit_scores(p)["test_failures"] == 4


def test_negative_counts_rejected(tmp_path):
    p = tmp_path / "neg.xml"
    p.write_text('<testsuite tests="10" failures="-5" errors="0" skipped="0"/>')
    with pytest.raises(AdapterError):
        junit_scores(p)


# ------------------------------------------------------------------ seal
REG = ("- name: m\n  direction: higher_better\n  threshold: 0.8\n"
       "  noise_band: 0.0\n  blocking: hard\n")


def test_unsigned_seal_rejected_when_key_supplied(tmp_path, capsys):
    reg = tmp_path / "registry.yaml"
    reg.write_text(REG)
    sd = tmp_path / "evals" / "seals"
    assert prereg.create_seal(registry_path=reg, seals_dir=sd, bands=None, key=None)
    # an attacker with repo write access but no key can only write unsigned seals
    rc = prereg.check(reg, seals_dir=sd, key=KEY, require_seal=True)
    assert rc == 2
    assert "UNSIGNED" in capsys.readouterr().err


# guard: must keep passing
def test_signed_seal_with_key_still_passes(tmp_path):
    reg = tmp_path / "registry.yaml"
    reg.write_text(REG)
    sd = tmp_path / "evals" / "seals"
    assert prereg.create_seal(registry_path=reg, seals_dir=sd, bands=None, key=KEY)
    assert prereg.check(reg, seals_dir=sd, key=KEY, require_seal=True) == 0


# ------------------------------------------------------------------ baseline
SPEC = [{"name": "m", "direction": "higher_better", "threshold": 0.5,
         "noise_band": 0.0, "blocking": "hard"}]


@pytest.mark.parametrize("entry", [
    {"mean": float("nan"), "band_2sigma": 0.01},
    {"mean": 0.9, "band_2sigma": float("inf")},
    {"mean": "0.9", "band_2sigma": 0.01},
    {"band_2sigma": 0.01},
])
def test_invalid_baseline_entry_blocks(entry):
    # candidate equals the baseline mean, so only validation can block it
    decision, verdicts = decide(SPEC, {"m": 0.9}, {"metrics": {"m": entry}})
    assert decision == "BLOCK", verdicts


def test_metric_missing_from_baseline_blocks():
    decision, _ = decide(SPEC, {"m": 0.6}, {"metrics": {"other": {"mean": 1.0}}})
    assert decision == "BLOCK"


@pytest.mark.parametrize("baseline", [[], {"metrics": []}, {"no_metrics": 1}])
def test_malformed_baseline_blocks(baseline):
    decision, _ = decide(SPEC, {"m": 0.6}, baseline)
    assert decision == "BLOCK"


# guard: must keep passing
def test_valid_baseline_still_judged():
    decision, _ = decide(SPEC, {"m": 0.9},
                         {"metrics": {"m": {"mean": 0.9, "band_2sigma": 0.02}}})
    assert decision == "PROMOTE"
