"""End-to-end: /eval-init scaffold -> gate CLI -> baseline -> conductor, in a
fresh fake repo. This is the exact first-session path a plugin user takes."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[1]


def run(args, cwd, **kw):
    return subprocess.run([sys.executable, *args], cwd=cwd,
                          capture_output=True, text=True, **kw)


@pytest.fixture()
def repo(tmp_path):
    r = run([str(PLUGIN / "scripts/eval_init.py")], tmp_path)
    assert r.returncode == 0, r.stderr
    return tmp_path


def gate(repo, *extra):
    return run([str(repo / "evals/tools/promote.py"), *extra], repo)


def write_candidate(repo, scores, manifest=None, path="evals/candidate.json"):
    obj = {"scores": scores}
    if manifest is not None:
        obj["manifest"] = manifest
    (repo / path).write_text(json.dumps(obj))


HEALTHY = {"task_success_rate": 0.95, "json_schema_compliance": 1.0,
           "safety_pass_rate": 1.0, "latency_p95_s": 1.0, "cost_per_run_usd": 0.01}


def test_init_creates_expected_files(repo):
    for f in ("evals/registry.yaml", "evals/tools/promote.py",
              "evals/tools/conductor.py", "evals/tools/steps.yaml",
              "evals/fixtures/README.md", ".github/workflows/eval-gate.yml",
              "evals/candidate.example.json"):
        assert (repo / f).exists(), f


def test_init_is_idempotent_without_force(repo):
    marker = "# user edited\n"
    reg = repo / "evals/registry.yaml"
    reg.write_text(marker + reg.read_text())
    r = run([str(PLUGIN / "scripts/eval_init.py")], repo)
    assert r.returncode == 0
    assert reg.read_text().startswith(marker)  # not clobbered


def test_healthy_candidate_promotes_threshold_only(repo):
    write_candidate(repo, HEALTHY)
    r = gate(repo)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PROMOTE" in r.stdout and "threshold" in r.stdout  # no-baseline warning


def test_each_hard_metric_blocks_alone(repo):
    breaches = {"task_success_rate": 0.5, "json_schema_compliance": 0.9,
                "safety_pass_rate": 0.9}
    for metric, bad in breaches.items():
        write_candidate(repo, {**HEALTHY, metric: bad})
        r = gate(repo)
        assert r.returncode == 1, metric
        blocked = [ln for ln in r.stdout.splitlines()
                   if " BLOCK " in f" {ln} " and not ln.startswith("DECISION")]
        assert len(blocked) == 1 and metric in blocked[0], r.stdout


def test_lower_better_breach_is_above_threshold(repo):
    write_candidate(repo, {**HEALTHY, "latency_p95_s": 99.0})
    r = gate(repo)
    assert r.returncode == 0  # latency is soft in the template -> WARN not BLOCK
    assert "WARN" in r.stdout


def test_missing_metric_blocks(repo):
    scores = dict(HEALTHY)
    scores.pop("safety_pass_rate")
    write_candidate(repo, scores)
    assert gate(repo).returncode == 1


def test_nan_blocks_via_cli(repo):
    (repo / "evals/candidate.json").write_text(
        '{"scores": {"task_success_rate": NaN, "json_schema_compliance": 1.0, '
        '"safety_pass_rate": 1.0, "latency_p95_s": 1.0, "cost_per_run_usd": 0.01}}')
    assert gate(repo).returncode == 1


def test_registry_typo_is_exit_2(repo):
    reg = repo / "evals/registry.yaml"
    reg.write_text(reg.read_text().replace("higher_better", "higher_beter", 1))
    write_candidate(repo, HEALTHY)
    r = gate(repo)
    assert r.returncode == 2
    assert "lint" in r.stderr


def test_stale_baseline_blocks_before_judging(repo):
    (repo / "evals/baseline.json").write_text(json.dumps({
        "manifest": {"registry_hash": "aaaa", "dataset_hash": "bbbb"},
        "n_runs": 3, "metrics": {}}))
    write_candidate(repo, HEALTHY,
                    manifest={"registry_hash": "aaaa", "dataset_hash": "CHANGED"})
    r = gate(repo)
    assert r.returncode == 1 and "stale baseline" in r.stderr
    write_candidate(repo, HEALTHY)  # no manifest at all -> also fail closed
    r = gate(repo)
    assert r.returncode == 1 and "carries none" in r.stderr


def test_baseline_runner_and_regression(repo):
    runs = repo / "evals/runs"
    runs.mkdir()
    for i, v in enumerate((0.94, 0.95, 0.96)):
        (runs / f"r{i}.json").write_text(json.dumps({"scores": {**HEALTHY, "task_success_rate": v}}))
    r = run([str(repo / "evals/tools/baseline.py"), "--from", "evals/runs/*.json"], repo)
    assert r.returncode == 0, r.stderr
    base = json.loads((repo / "evals/baseline.json").read_text())
    assert base["n_runs"] == 3
    assert base["metrics"]["task_success_rate"]["band_2sigma"] > 0
    # in-band candidate promotes; far regression (still above threshold) blocks
    write_candidate(repo, {**HEALTHY, "task_success_rate": 0.945})
    assert gate(repo).returncode == 0
    write_candidate(repo, {**HEALTHY, "task_success_rate": 0.86})
    assert gate(repo).returncode == 1


def test_baseline_refuses_single_run(repo):
    runs = repo / "evals/runs"
    runs.mkdir()
    (runs / "r0.json").write_text(json.dumps({"scores": HEALTHY}))
    r = run([str(repo / "evals/tools/baseline.py"), "--from", "evals/runs/*.json"], repo)
    assert r.returncode != 0 and "2 runs" in (r.stdout + r.stderr)


def test_conductor_init_and_evidence_gate(tmp_path):
    r = run([str(PLUGIN / "scripts/eval_init.py"), "--conductor",
             "--project", "demo", "--archetype", "A2"], tmp_path)
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "evals/conductor_state.json").exists()
    c = tmp_path / "evals/tools/conductor.py"
    # audit passes fresh; placeholder evidence refused on a CI-kind step later
    assert run([str(c), "audit"], tmp_path).returncode == 0
    r = run([str(c), "check", "--evidence",
             "https://github.com/x/y/actions/runs/<PASTE-REAL-RUN-ID>"], tmp_path)
    assert r.returncode != 0


def test_registry_tamper_after_baseline_blocks(repo):
    """Attack: edit the registry (gut a threshold) after candidate/baseline
    were produced, keeping the old attested hash. Gate must recompute."""
    import hashlib
    reg = repo / "evals/registry.yaml"
    old_hash = hashlib.sha256(reg.read_bytes()).hexdigest()[:12]
    write_candidate(repo, HEALTHY,
                    manifest={"registry_hash": old_hash, "dataset_hash": "d1"})
    assert gate(repo).returncode == 0  # honest state passes
    reg.write_text(reg.read_text().replace("threshold: 0.85", "threshold: 0.10"))
    r = gate(repo)  # same candidate, stale attested hash
    assert r.returncode == 1 and "registry_hash mismatch" in r.stderr


def test_non_hex_registry_hash_blocks(repo):
    write_candidate(repo, HEALTHY,
                    manifest={"registry_hash": "REPLACE-me", "dataset_hash": "d1"})
    r = gate(repo)
    assert r.returncode == 1 and "not a sha256 hex" in r.stderr


def test_baseline_rejects_non_numeric_scores(repo):
    runs = repo / "evals/runs"; runs.mkdir()
    (runs / "r0.json").write_text(json.dumps({"scores": {**HEALTHY, "task_success_rate": "0.9"}}))
    (runs / "r1.json").write_text(json.dumps({"scores": HEALTHY}))
    r = run([str(repo / "evals/tools/baseline.py"), "--from", "evals/runs/*.json"], repo)
    assert r.returncode != 0 and "non-numeric" in (r.stdout + r.stderr)


# ---------------------------------------------------------------- profiles
def test_init_auto_detects_pytest_and_gates_real_numbers_first_run(tmp_path):
    """The zero-config path: a repo with tests gets a working gate on the
    first push, with the test_count floor measured at install time."""
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_a.py").write_text(
        "def test_one(): pass\ndef test_two(): pass\ndef test_three(): pass\n")
    r = run([str(PLUGIN / "scripts/eval_init.py")], tmp_path)
    assert r.returncode == 0, r.stderr
    assert "Profile: pytest" in r.stdout
    reg = (tmp_path / "evals/registry.yaml").read_text()
    assert "test_pass_rate" in reg and "threshold: 3\n" in reg   # measured floor
    wf = (tmp_path / ".github/workflows/eval-gate.yml").read_text()
    assert "adapters.py junit" in wf and "REPLACE ME" not in wf
    assert "|| true\n      - name: Gate" not in wf  # audit no longer silently optional
    # the exact CI producer, locally
    run(["-m", "pytest", "-q", "--junitxml=evals/junit.xml"], tmp_path)
    a = run([str(tmp_path / "evals/tools/adapters.py"), "junit", "evals/junit.xml"], tmp_path)
    assert a.returncode == 0, a.stderr
    g = gate(tmp_path)
    assert g.returncode == 0, g.stdout + g.stderr
    assert "PROMOTE" in g.stdout
    # delete a test -> the floor fires
    (tmp_path / "tests/test_a.py").write_text("def test_one(): pass\n")
    run(["-m", "pytest", "-q", "--junitxml=evals/junit.xml"], tmp_path)
    run([str(tmp_path / "evals/tools/adapters.py"), "junit", "evals/junit.xml"], tmp_path)
    g = gate(tmp_path)
    assert g.returncode == 1 and "test_count" in g.stdout


def test_init_auto_detects_claude_plugin(tmp_path):
    (tmp_path / ".claude-plugin").mkdir()
    (tmp_path / ".claude-plugin/plugin.json").write_text('{"name":"x"}')
    r = run([str(PLUGIN / "scripts/eval_init.py")], tmp_path)
    assert r.returncode == 0, r.stderr
    assert "Profile: plugin-eval" in r.stdout
    reg = (tmp_path / "evals/registry.yaml").read_text()
    assert "plugin_eval_mean_delta" in reg
    wf = (tmp_path / ".github/workflows/eval-gate.yml").read_text()
    assert "claude plugin eval" in wf and "adapters.py plugin-eval" in wf
    # registry lints clean
    r = run([str(tmp_path / "evals/tools/registry_lint.py"), "evals/registry.yaml"], tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr


def test_init_explicit_profile_overrides_detection(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_a.py").write_text("def test_one(): pass\n")
    r = run([str(PLUGIN / "scripts/eval_init.py"), "--profile", "llm"], tmp_path)
    assert r.returncode == 0 and "Profile: llm" in r.stdout
    assert "task_success_rate" in (tmp_path / "evals/registry.yaml").read_text()
    assert "REPLACE ME" in (tmp_path / ".github/workflows/eval-gate.yml").read_text()


def test_plugin_eval_profile_gate_blocks_on_zero_delta(tmp_path):
    """A plugin that scores 1.0 with and without itself is not helping; the
    delta row must BLOCK that."""
    (tmp_path / ".claude-plugin").mkdir()
    (tmp_path / ".claude-plugin/plugin.json").write_text('{"name":"x"}')
    run([str(PLUGIN / "scripts/eval_init.py")], tmp_path)
    res = tmp_path / "evals/results/2026-10-03T00-00-00"
    res.mkdir(parents=True)
    (res / "aggregate-result.json").write_text(json.dumps({
        "schemaVersion": 1, "partial": False,
        "aggregates": {"overallScore": 1.0, "casesPassed": 2, "casesTotal": 2, "meanDelta": 0.0},
        "cases": [{"name": "a", "aggregates": {"score": 1.0, "delta": 0.0}},
                  {"name": "b", "aggregates": {"score": 1.0, "delta": 0.0}}]}))
    a = run([str(tmp_path / "evals/tools/adapters.py"), "plugin-eval", "evals/results/"], tmp_path)
    assert a.returncode == 0, a.stderr
    g = gate(tmp_path)
    assert g.returncode == 1 and "plugin_eval_mean_delta" in g.stdout
