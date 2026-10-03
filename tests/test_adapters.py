"""Adapters: existing eval output -> gateable candidate.json, fail-closed.

Every refusal here is a case where a naive adapter would have produced a
number that LOOKED like a measurement."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))
from adapters import (  # noqa: E402
    AdapterError, junit_scores, plugin_eval_scores, promptfoo_scores,
    flat_scores, resolve_plugin_eval_result, build_candidate,
)

JUNIT = """<?xml version="1.0"?>
<testsuites><testsuite name="t" tests="{tests}" failures="{failures}" errors="{errors}" skipped="{skipped}"/></testsuites>"""


def junit(tmp_path, **kw):
    d = dict(tests=10, failures=0, errors=0, skipped=0)
    d.update(kw)
    p = tmp_path / "r.xml"
    p.write_text(JUNIT.format(**d))
    return p


def test_junit_all_pass(tmp_path):
    s = junit_scores(junit(tmp_path))
    assert s == {"test_pass_rate": 1.0, "test_count": 10, "test_failures": 0}


def test_junit_failures_and_errors_both_count(tmp_path):
    s = junit_scores(junit(tmp_path, failures=1, errors=1))
    assert s["test_pass_rate"] == 0.8 and s["test_failures"] == 2


def test_junit_skipped_excluded_from_executed(tmp_path):
    s = junit_scores(junit(tmp_path, skipped=5))
    assert s["test_pass_rate"] == 1.0 and s["test_count"] == 10


def test_junit_zero_executed_is_zero_pass_rate_not_one(tmp_path):
    # An empty run must not look like a passing run.
    s = junit_scores(junit(tmp_path, tests=0))
    assert s["test_pass_rate"] == 0.0


def test_junit_missing_file_refused(tmp_path):
    with pytest.raises(AdapterError):
        junit_scores(tmp_path / "nope.xml")


def test_junit_garbage_refused(tmp_path):
    p = tmp_path / "r.xml"
    p.write_text("<not xml")
    with pytest.raises(AdapterError):
        junit_scores(p)


# ------------------------------------------------------------ plugin-eval
def agg(**over):
    doc = {
        "schemaVersion": 1, "partial": False,
        "aggregates": {"overallScore": 0.9, "casesPassed": 2, "casesTotal": 3, "meanDelta": 0.3},
        "cases": [
            {"name": "a", "aggregates": {"score": 1.0, "delta": 0.5}},
            {"name": "b", "aggregates": {"score": 0.7, "delta": 0.1}},
            {"name": "c", "aggregates": {"score": 1.0}},   # delta omitted: arms not comparable
        ],
        "costUsd": 0.4, "claudeVersion": "2.1.300",
    }
    doc.update(over)
    return doc


def write_run(results_dir: Path, ts: str, doc: dict) -> Path:
    d = results_dir / ts
    d.mkdir(parents=True)
    f = d / "aggregate-result.json"
    f.write_text(json.dumps(doc))
    return f


def test_plugin_eval_scores_from_file(tmp_path):
    f = write_run(tmp_path, "2026-10-01T10-00-00", agg())
    s = plugin_eval_scores(f)
    assert s["plugin_eval_score"] == 0.9
    assert s["plugin_eval_mean_delta"] == 0.3
    assert s["plugin_eval_min_case_score"] == 0.7
    assert s["plugin_eval_min_case_delta"] == 0.1
    assert s["plugin_eval_cases_passed"] == 2 and s["plugin_eval_cases_total"] == 3


def test_plugin_eval_picks_latest_run_in_results_dir(tmp_path):
    write_run(tmp_path, "2026-10-01T10-00-00", agg(aggregates={
        "overallScore": 0.1, "casesPassed": 0, "casesTotal": 3}))
    write_run(tmp_path, "2026-10-02T10-00-00", agg())
    assert resolve_plugin_eval_result(tmp_path).parent.name == "2026-10-02T10-00-00"
    assert plugin_eval_scores(tmp_path)["plugin_eval_score"] == 0.9


def test_plugin_eval_partial_run_is_refused(tmp_path):
    f = write_run(tmp_path, "t", agg(partial=True, partialReason="cost_ceiling"))
    with pytest.raises(AdapterError, match="partial"):
        plugin_eval_scores(f)


def test_plugin_eval_not_a_result_refused(tmp_path):
    f = tmp_path / "x.json"
    f.write_text(json.dumps({"hello": 1}))
    with pytest.raises(AdapterError, match="aggregates"):
        plugin_eval_scores(f)


def test_plugin_eval_empty_results_dir_refused(tmp_path):
    with pytest.raises(AdapterError, match="no aggregate-result.json"):
        plugin_eval_scores(tmp_path)


def test_plugin_eval_nan_score_refused(tmp_path):
    f = write_run(tmp_path, "t", agg(aggregates={
        "overallScore": float("nan"), "casesPassed": 0, "casesTotal": 3}))
    # json.dumps writes NaN; the adapter must refuse it rather than pass it on
    with pytest.raises(AdapterError, match="finite"):
        plugin_eval_scores(f)


# -------------------------------------------------------------- promptfoo
def test_promptfoo_nested_stats(tmp_path):
    f = tmp_path / "o.json"
    f.write_text(json.dumps({"results": {"stats": {"successes": 8, "failures": 2}}}))
    s = promptfoo_scores(f)
    assert s == {"promptfoo_pass_rate": 0.8, "promptfoo_total": 10, "promptfoo_failures": 2}


def test_promptfoo_top_level_stats_with_errors(tmp_path):
    f = tmp_path / "o.json"
    f.write_text(json.dumps({"stats": {"successes": 7, "failures": 2, "errors": 1}}))
    s = promptfoo_scores(f)
    assert s["promptfoo_pass_rate"] == 0.7 and s["promptfoo_failures"] == 3


def test_promptfoo_without_stats_refused(tmp_path):
    f = tmp_path / "o.json"
    f.write_text(json.dumps({"results": []}))
    with pytest.raises(AdapterError):
        promptfoo_scores(f)


# ----------------------------------------------------------------- scores
def test_flat_scores_accepts_bare_and_wrapped(tmp_path):
    f = tmp_path / "s.json"
    f.write_text(json.dumps({"a": 1, "b": 0.5}))
    assert flat_scores(f) == {"a": 1.0, "b": 0.5}
    f.write_text(json.dumps({"scores": {"a": 1}}))
    assert flat_scores(f) == {"a": 1.0}


def test_flat_scores_refuses_non_numbers(tmp_path):
    f = tmp_path / "s.json"
    f.write_text(json.dumps({"a": "0.9"}))
    with pytest.raises(AdapterError):
        flat_scores(f)


# --------------------------------------------------------------- manifest
def test_build_candidate_attests_registry_hash(tmp_path):
    reg = tmp_path / "registry.yaml"
    reg.write_text("- name: x\n")
    import hashlib
    cand = build_candidate("junit", junit(tmp_path), reg)
    assert cand["manifest"]["registry_hash"] == hashlib.sha256(reg.read_bytes()).hexdigest()
    assert cand["manifest"]["source"].startswith("junit:")


def test_cli_exit_2_writes_nothing(tmp_path):
    out = tmp_path / "candidate.json"
    r = subprocess.run([sys.executable, str(ROOT / "core/adapters.py"), "junit",
                        str(tmp_path / "missing.xml"), "--out", str(out)],
                       capture_output=True, text=True)
    assert r.returncode == 2 and "FAIL" in r.stderr
    assert not out.exists()


def test_cli_junit_then_gate_promotes_and_blocks(tmp_path):
    """The pytest-profile first run, end to end: adapter -> promote.py."""
    reg = tmp_path / "evals/registry.yaml"
    reg.parent.mkdir()
    reg.write_text((ROOT / "templates/registry.pytest.yaml").read_text()
                   .replace("__TEST_COUNT__", "10"))
    out = tmp_path / "evals/candidate.json"
    r = subprocess.run([sys.executable, str(ROOT / "core/adapters.py"), "junit",
                        str(junit(tmp_path)), "--out", str(out), "--registry", str(reg)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    g = subprocess.run([sys.executable, str(ROOT / "core/promote.py"), "--registry", str(reg),
                        "--candidate", str(out), "--baseline", str(tmp_path / "none.json")],
                       capture_output=True, text=True)
    assert g.returncode == 0, g.stdout + g.stderr
    # one failing test -> BLOCK on test_pass_rate AND test_failures
    subprocess.run([sys.executable, str(ROOT / "core/adapters.py"), "junit",
                    str(junit(tmp_path, failures=1)), "--out", str(out), "--registry", str(reg)],
                   capture_output=True, text=True)
    g = subprocess.run([sys.executable, str(ROOT / "core/promote.py"), "--registry", str(reg),
                        "--candidate", str(out), "--baseline", str(tmp_path / "none.json")],
                       capture_output=True, text=True)
    assert g.returncode == 1 and "BLOCK" in g.stdout
    # a deleted test -> BLOCK on the test_count floor even though everything passes
    subprocess.run([sys.executable, str(ROOT / "core/adapters.py"), "junit",
                    str(junit(tmp_path, tests=9)), "--out", str(out), "--registry", str(reg)],
                   capture_output=True, text=True)
    g = subprocess.run([sys.executable, str(ROOT / "core/promote.py"), "--registry", str(reg),
                        "--candidate", str(out), "--baseline", str(tmp_path / "none.json")],
                       capture_output=True, text=True)
    assert g.returncode == 1 and "test_count" in g.stdout


def test_missing_registry_is_refused_not_silently_unattested(tmp_path):
    with pytest.raises(AdapterError, match="registry not found"):
        build_candidate("junit", junit(tmp_path), tmp_path / "evals/registry.yaml")


def test_junit_non_integer_counts_refused(tmp_path):
    p = tmp_path / "r.xml"
    p.write_text('<testsuite name="t" tests="x" failures="0"/>')
    with pytest.raises(AdapterError):
        junit_scores(p)
