"""/eval-prove must never leave its signing key stageable (B2).

The wedge writes evals/.receipt-key, evals/.wedge-baseline.json and
.eval-prove-junit.xml into the user's repo; a plain `git add -A` used to stage
the key. Runs the real command lines through tests/test_commands_live.py.
"""
import subprocess
from pathlib import Path

import pytest

from test_commands_live import (BASH, command_lines, default_path,  # noqa: F401
                                make_repo, run_line)

pytestmark = pytest.mark.skipif(BASH is None, reason="bash not available")

LOCAL_ONLY = ("evals/.receipt-key", "evals/.wedge-baseline.json", ".eval-prove-junit.xml")


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)


def _staged_after_add_all(repo: Path) -> set[str]:
    assert _git(repo, "add", "-A").returncode == 0
    return set(_git(repo, "diff", "--cached", "--name-only").stdout.split())


def test_prove_gitignores_the_key_on_first_run(tmp_path, default_path):
    repo = make_repo(tmp_path / "repo", "one_test")
    rc, out = run_line(command_lines("eval-prove")[0], repo, default_path)
    assert rc == 0, out
    assert (repo / "evals" / ".receipt-key").exists()
    for path in LOCAL_ONLY:
        assert _git(repo, "check-ignore", "-q", path).returncode == 0, path
    staged = _staged_after_add_all(repo)
    assert not staged & set(LOCAL_ONLY), staged
    assert ".gitignore" in staged
    assert any(p.startswith("evals/receipts/") for p in staged), \
        "receipts are the anchor — they must stay committable"


def test_cannot_prove_run_leaves_nothing_stageable(tmp_path, default_path):
    """Zero collected tests: pytest still wrote its JUnit before the refusal."""
    repo = make_repo(tmp_path / "repo", "zero_tests")
    rc, out = run_line(command_lines("eval-prove")[0], repo, default_path)
    assert rc == 2, out
    assert not _staged_after_add_all(repo) & set(LOCAL_ONLY)


def test_prove_gitignore_is_idempotent_and_keeps_existing_lines(tmp_path, default_path):
    repo = make_repo(tmp_path / "repo", "one_test")
    (repo / ".gitignore").write_text("node_modules/\n")
    for _ in range(2):
        assert run_line(command_lines("eval-prove")[0], repo, default_path)[0] == 0
    lines = (repo / ".gitignore").read_text().splitlines()
    assert lines[0] == "node_modules/"
    for path in LOCAL_ONLY:
        assert lines.count(path) == 1, lines


def test_init_ignores_where_prove_really_writes(tmp_path, default_path):
    repo = make_repo(tmp_path / "repo", "one_test")
    assert run_line(command_lines("eval-init")[0], repo, default_path)[0] == 0
    for path in LOCAL_ONLY:
        assert _git(repo, "check-ignore", "-q", path).returncode == 0, path


def test_vendored_prove_runs_after_init(tmp_path, default_path):
    """After /eval-init, the line picks evals/tools/wedge.py; it must have every
    sibling module it imports."""
    repo = make_repo(tmp_path / "repo", "one_test")
    assert run_line(command_lines("eval-init")[0], repo, default_path)[0] == 0
    rc, out = run_line(command_lines("eval-prove")[0], repo, default_path)
    assert rc == 0, out
    assert not _staged_after_add_all(repo) & set(LOCAL_ONLY)
