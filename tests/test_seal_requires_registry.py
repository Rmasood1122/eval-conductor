"""/eval-seal with no registry: exit 2, write nothing, point at /eval-init (B1).

It used to exit 0 and write an unsigned seal with registry_sha256 null — a
pre-registration of no bar at all, sitting in the chain as if it were one.
Runs the real command line through the harness in tests/test_commands_live.py.
"""
import pytest

from test_commands_live import (BASH, SCENARIOS, command_lines,  # noqa: F401
                                default_path, make_repo, run_line)

pytestmark = pytest.mark.skipif(BASH is None, reason="bash not available")


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_seal_without_registry_refuses_and_writes_nothing(tmp_path, default_path,
                                                         scenario):
    repo = make_repo(tmp_path / "repo", scenario)
    rc, out = run_line(command_lines("eval-seal")[0], repo, default_path)
    assert rc == 2, out
    assert "registry not found" in out and "/eval-init" in out, out
    assert "sealed [" not in out and "Traceback" not in out, out
    assert not (repo / "evals").exists(), "a failed seal must leave no seal behind"
