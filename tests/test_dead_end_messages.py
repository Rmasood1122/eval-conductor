"""No command may strand a new user: every refusal names what to run next (B3).

Runs the real command lines through the harness in tests/test_commands_live.py.
The matrix there pins the no-setup case for /eval-gate, /eval-explain and
/eval-verify; these cover ordering, the after-/eval-init case, and /eval-prove.
"""
import sys
from pathlib import Path

import pytest

from test_commands_live import (BASH, command_lines, default_path,  # noqa: F401
                                make_repo, run_line)

pytestmark = pytest.mark.skipif(BASH is None, reason="bash not available")


def test_gate_without_candidate_leads_with_the_candidate_error(tmp_path, default_path):
    repo = make_repo(tmp_path / "repo", "empty")
    rc, out = run_line(command_lines("eval-gate")[0], repo, default_path)
    assert rc == 2
    assert out.lstrip().startswith("FAIL: candidate not found"), out


@pytest.mark.parametrize("cmd", ["eval-gate", "eval-explain"])
def test_missing_candidate_after_init_points_at_the_example(tmp_path, default_path, cmd):
    """Once /eval-init ran, the example exists and re-running init is no answer."""
    repo = make_repo(tmp_path / "repo", "one_test")
    assert run_line(command_lines("eval-init")[0], repo, default_path)[0] == 0
    rc, out = run_line(command_lines(cmd)[0], repo, default_path)
    assert rc == 2, out
    assert "candidate.example.json" in out and "/eval-import" in out, out
    assert "/eval-init" not in out and "no baseline" not in out, out


@pytest.mark.parametrize("cmd", ["eval-gate", "eval-explain"])
def test_candidate_without_registry_names_eval_init(tmp_path, default_path, cmd):
    repo = make_repo(tmp_path / "repo", "empty")
    (repo / "evals").mkdir()
    (repo / "evals" / "candidate.json").write_text('{"scores": {"m": 1.0}}')
    rc, out = run_line(command_lines(cmd)[0], repo, default_path)
    assert rc == 2, out
    assert "registry not found" in out and "/eval-init" in out, out
    assert "Traceback" not in out and "no baseline" not in out, out


def test_prove_run_works_without_a_detectable_pytest_suite(tmp_path, default_path):
    """--run is the documented answer to "no suite detected" (a jest repo, a
    Makefile target), so it must not be refused for that very reason."""
    repo = make_repo(tmp_path / "repo", "empty")
    (repo / "write_junit.py").write_text(
        "import sys\n"
        "open(sys.argv[1], 'w').write('<testsuite tests=\"2\" failures=\"0\" "
        "errors=\"0\" skipped=\"0\"></testsuite>')\n")
    args = f"--run '\"{Path(sys.executable).as_posix()}\" write_junit.py {{junit}}'"
    rc, out = run_line(command_lines("eval-prove")[0], repo, default_path, args)
    assert rc == 0, out
    assert "PROVEN" in out and "2/2" in out, out
