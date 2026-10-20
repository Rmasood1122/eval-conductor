"""Live command harness — run every slash command exactly the way Claude does.

Each commands/*.md carries a fenced shell line that Claude runs through its Bash
tool. The Python behind a line can pass every unit test while the line itself is
broken (wrong interpreter, wrong path, an error that strands the user), so this
harness runs the LINE: extract it, substitute ${CLAUDE_PLUGIN_ROOT} with this
checkout and $ARGUMENTS with the case's arguments, and `bash -c` it inside a
fresh temporary git repo.

Repos covered: empty, one passing pytest test, and a tests/ dir with zero test
functions. Each case asserts the exit code AND, where the user would otherwise
be stuck, that the output names the next command to run.

A `python3` shim pointing at the interpreter running this suite goes first on
PATH, so every line runs an interpreter that has pytest + PyYAML on every
machine.
"""
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
COMMANDS = ROOT / "commands"
FENCE = re.compile(r"^```[^\n]*\n(.*?)^```", re.M | re.S)
SCENARIOS = ("empty", "one_test", "zero_tests")


def command_lines(name: str) -> list[str]:
    """Every non-blank line inside a fenced block of commands/<name>.md."""
    text = (COMMANDS / f"{name}.md").read_text(encoding="utf-8")
    return [ln for block in FENCE.findall(text) for ln in block.splitlines()
            if ln.strip()]


def _find_bash() -> str | None:
    """Git Bash on Windows (the shell Claude Code uses there) — never the
    System32 WSL launcher; plain bash elsewhere."""
    if os.name != "nt":
        return shutil.which("bash")
    roots = []
    git = shutil.which("git")
    if git:
        roots += list(Path(git).resolve().parents)[:3]
    roots.append(Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git")
    for root in roots:
        for rel in ("bin/bash.exe", "usr/bin/bash.exe"):
            if (root / rel).is_file():
                return str(root / rel)
    return None


BASH = _find_bash()
pytestmark = pytest.mark.skipif(BASH is None, reason="bash not available")


# --------------------------------------------------------------- fixtures
def write_shim(shim_dir: Path, name: str, body: str) -> None:
    """An executable POSIX sh script on PATH. LF only: a CRLF shebang breaks sh."""
    shim_dir.mkdir(parents=True, exist_ok=True)
    p = shim_dir / name
    p.write_bytes(f"#!/bin/sh\n{body}\n".encode())
    p.chmod(0o755)


def real_python(shim_dir: Path, name: str) -> None:
    write_shim(shim_dir, name, f'exec "{Path(sys.executable).as_posix()}" "$@"')


def make_repo(path: Path, scenario: str) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    if scenario == "one_test":
        (path / "tests").mkdir()
        (path / "tests" / "test_one.py").write_text(
            "def test_one():\n    assert 1 + 1 == 2\n")
    elif scenario == "zero_tests":
        (path / "tests").mkdir()
        (path / "tests" / "test_helpers.py").write_text(
            "def helper():\n    return 1\n")
    return path


@pytest.fixture
def default_path(tmp_path):
    shim = tmp_path / "shim"
    real_python(shim, "python3")
    return f"{shim}{os.pathsep}{os.environ.get('PATH', '')}"


def run_line(line: str, repo: Path, path: str, args: str = "") -> tuple[int, str]:
    """Run one command line the way Claude's Bash tool does. Returns (exit code,
    merged stdout+stderr in program order)."""
    cmd = (line.replace("${CLAUDE_PLUGIN_ROOT}", ROOT.as_posix())
               .replace("$ARGUMENTS", args))
    env = {k: v for k, v in os.environ.items()
           if k not in ("EVAL_RECEIPT_KEY", "GITHUB_TOKEN")}
    env["PATH"] = path
    env["PYTHONUNBUFFERED"] = "1"   # keep stdout/stderr interleaving in program order
    r = subprocess.run([BASH, "-c", cmd], cwd=repo, env=env,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=600)
    return r.returncode, r.stdout.decode("utf-8", "replace")


# --------------------------------------------------------------- the matrix
def _case(cmd, exit_code, has=(), lacks=(), idx=0, args="", scenarios=SCENARIOS):
    return [pytest.param(cmd, idx, args, s, exit_code, has, lacks,
                         id=f"{cmd}[{idx}]{'-' + args if args else ''}-{s}")
            for s in scenarios]


CASES = [
    *_case("conductor", 2, has=["init"]),
    *_case("conductor", 1, has=["init"], args="status"),
    *_case("eval-baseline", 2, has=["--cmd", "--from"]),
    *_case("eval-import", 2, has=["junit", "promptfoo"]),
    *_case("eval-explain", 2, has=["candidate"]),
    *_case("eval-gate", 2, has=["candidate not found"]),
    *_case("eval-verify", 2, has=["no receipts"]),
    *_case("eval-seal", 2, idx=1, has=["no seal on record"]),
    *_case("eval-init", 0, has=["Profile: llm", "NEXT STEPS"], scenarios=["empty"]),
    *_case("eval-init", 0, has=["Profile: pytest", "detected 1 tests", "NEXT STEPS"],
           scenarios=["one_test"]),
    *_case("eval-init", 0, has=["collects 0 tests", "NEXT STEPS"],
           scenarios=["zero_tests"]),
    *_case("eval-prove", 2, has=["CANNOT PROVE", "--junit", "--run"],
           scenarios=["empty"]),
    *_case("eval-prove", 0, has=["PROVEN", "1/1", "img.shields.io/badge/", "/eval-init"],
           scenarios=["one_test"]),
    *_case("eval-prove", 2, has=["CANNOT PROVE", "zero tests"],
           lacks=["PROVEN", "brightgreen"], scenarios=["zero_tests"]),
]


@pytest.mark.parametrize("cmd,idx,args,scenario,exit_code,has,lacks", CASES)
def test_command_line(tmp_path, default_path, cmd, idx, args, scenario, exit_code,
                      has, lacks):
    repo = make_repo(tmp_path / "repo", scenario)
    rc, out = run_line(command_lines(cmd)[idx], repo, default_path, args)
    assert rc == exit_code, f"exit {rc}, want {exit_code}:\n{out}"
    assert "Traceback" not in out, out
    for s in has:
        assert s in out, f"missing {s!r}:\n{out}"
    for s in lacks:
        assert s not in out, f"unexpected {s!r}:\n{out}"


def test_every_command_has_a_line():
    for p in COMMANDS.glob("*.md"):
        assert command_lines(p.stem), f"{p.name} has no fenced command line"


# Lines the journey tests below run after setup, on top of the matrix.
JOURNEY_LINES = {("eval-prove", 0), ("eval-verify", 0), ("eval-init", 0),
                 ("eval-seal", 0), ("eval-seal", 1)}


def test_every_command_line_is_exercised():
    want = {(p.stem, i) for p in COMMANDS.glob("*.md")
            for i in range(len(command_lines(p.stem)))}
    have = {(c.values[0], c.values[1]) for c in CASES} | JOURNEY_LINES
    assert want <= have, f"untested command lines: {sorted(want - have)}"


# --------------------------------------------------------------- journeys
def test_prove_then_verify(tmp_path, default_path):
    repo = make_repo(tmp_path / "repo", "one_test")
    rc, out = run_line(command_lines("eval-prove")[0], repo, default_path)
    assert rc == 0, out
    rc, out = run_line(command_lines("eval-verify")[0], repo, default_path)
    assert rc == 0, out
    assert "chain OK" in out, out


def test_init_then_seal_then_check(tmp_path, default_path):
    repo = make_repo(tmp_path / "repo", "one_test")
    seal, check = command_lines("eval-seal")
    assert run_line(command_lines("eval-init")[0], repo, default_path)[0] == 0
    rc, out = run_line(seal, repo, default_path)
    assert rc == 0 and "sealed [signed]" in out, out
    rc, out = run_line(check, repo, default_path)
    assert rc == 0 and "pre-registration OK" in out, out
