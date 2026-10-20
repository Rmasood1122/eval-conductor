"""core/py.sh — how every command line picks its Python, tested for real.

Windows' trap: `python3` on PATH is often the Microsoft Store alias stub.
`command -v` finds it, then it prints an install hint and exits 9009 (49 once
truncated to a byte) instead of running Python. py.sh must probe each candidate
by running it. These tests put fake interpreters first on PATH and run the real
command lines through the harness in tests/test_commands_live.py.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

from test_commands_live import (BASH, CASES, COMMANDS, ROOT, command_lines,  # noqa: F401
                                default_path, make_repo, real_python, run_line,
                                write_shim)

pytestmark = pytest.mark.skipif(BASH is None, reason="bash not available")

STORE_STUB = ('echo "Python was not found; run without arguments to install from '
              'the Microsoft Store, or disable this shortcut from Settings > Apps > '
              'Advanced app settings > App execution aliases." >&2; exit 49')
NO_PYTHON_MSG = "no working Python 3.10+"


@pytest.fixture
def store_stub_path(tmp_path):
    shim = tmp_path / "shim"
    write_shim(shim, "python3", STORE_STUB)
    real_python(shim, "python")
    return f"{shim}{os.pathsep}{os.environ.get('PATH', '')}"


@pytest.fixture
def py_launcher_path(tmp_path):
    """Only the Windows `py` launcher works: python3 is the stub, python is absent."""
    shim = tmp_path / "shim"
    write_shim(shim, "python3", STORE_STUB)
    write_shim(shim, "python", "exit 127")
    write_shim(shim, "py", '[ "$1" = "-3" ] || exit 2\nshift\n'
                           f'exec "{Path(sys.executable).as_posix()}" "$@"')
    return f"{shim}{os.pathsep}{os.environ.get('PATH', '')}"


@pytest.fixture
def no_python_path(tmp_path):
    """PATH with a shell and nothing else — no python3, python or py anywhere."""
    shim = tmp_path / "bare"
    write_shim(shim, "sh", 'exec /bin/sh "$@"')
    return str(shim)


STUB_CASES = [c for c in CASES
              if c.values[3] == "empty" or c.values[0] in ("eval-prove", "eval-init")]


@pytest.mark.parametrize("cmd,idx,args,scenario,exit_code,has,lacks", STUB_CASES)
def test_command_line_survives_store_stub(tmp_path, store_stub_path, cmd, idx, args,
                                          scenario, exit_code, has, lacks):
    repo = make_repo(tmp_path / "repo", scenario)
    rc, out = run_line(command_lines(cmd)[idx], repo, store_stub_path, args)
    assert rc == exit_code, f"exit {rc}, want {exit_code}:\n{out}"
    assert "Microsoft Store" not in out, out
    for s in has:
        assert s in out, f"missing {s!r}:\n{out}"


ALL_LINES = [pytest.param(p.stem, i, id=f"{p.stem}[{i}]")
             for p in sorted(COMMANDS.glob("*.md"))
             for i in range(len(command_lines(p.stem)))]


@pytest.mark.parametrize("cmd,idx", ALL_LINES)
def test_no_python_exits_127_with_one_message(tmp_path, no_python_path, cmd, idx):
    repo = make_repo(tmp_path / "repo", "empty")
    rc, out = run_line(command_lines(cmd)[idx], repo, no_python_path)
    assert rc == 127, out
    assert out.count(NO_PYTHON_MSG) == 1, out
    assert "not found" not in out.replace(NO_PYTHON_MSG, ""), out


def _py_sh(path: str, *args: str) -> tuple[int, str]:
    quoted = " ".join("'" + a.replace("'", "'\\''") + "'" for a in args)
    return run_line(f'sh "{(ROOT / "core" / "py.sh").as_posix()}" {quoted}',
                    ROOT, path)


def test_py_sh_skips_the_store_stub_and_passes_args_through(store_stub_path):
    rc, out = _py_sh(store_stub_path, "-c",
                     "import os, sys; print(sys.argv[1:], os.environ['EVAL_CONDUCTOR_PY'])",
                     "a b", "c")
    assert rc == 0, out
    assert "['a b', 'c'] python" in out, out


def test_py_sh_falls_back_to_the_py_launcher(py_launcher_path):
    rc, out = _py_sh(py_launcher_path, "-c",
                     "import os; print(os.environ['EVAL_CONDUCTOR_PY'])")
    assert rc == 0, out
    assert out.strip() == "py -3", out


def test_py_sh_passes_the_tool_exit_code_through(store_stub_path):
    rc, _ = _py_sh(store_stub_path, "-c", "raise SystemExit(3)")
    assert rc == 3


def test_next_steps_name_the_interpreter_that_ran(tmp_path, py_launcher_path):
    repo = make_repo(tmp_path / "repo", "one_test")
    rc, out = run_line(command_lines("eval-init")[0], repo, py_launcher_path)
    assert rc == 0, out
    assert "py -3 -m pytest" in out and "py -3 evals/tools/promote.py" in out, out
    assert "python evals/tools" not in out, out


def test_command_lines_use_py_sh():
    for p in COMMANDS.glob("*.md"):
        for line in command_lines(p.stem):
            assert 'sh "${CLAUDE_PLUGIN_ROOT}/core/py.sh" "$TOOL"' in line, (p.name, line)
            assert "python3 " not in line, (p.name, line)


def test_py_sh_is_lf_only():
    assert b"\r" not in (ROOT / "core" / "py.sh").read_bytes()


@pytest.fixture
def pytestless_python3_path(tmp_path):
    """python3 is a real Python 3.10+ without the plugin's packages; python has them.

    Found on a Windows machine with two installs: python3 = 3.14 without pytest,
    python = 3.13 with it. py.sh took the first Python 3.10+, so /eval-prove said
    CANNOT PROVE and /eval-init lowered the test-count floor to 1. A bare venv is
    the faithful stand-in: its own subprocesses can't import pytest either."""
    venv = tmp_path / "bare-venv"
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(venv)], check=True)
    exe = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    shim = tmp_path / "shim"
    write_shim(shim, "python3", f'exec "{exe.as_posix()}" "$@"')
    real_python(shim, "python")
    return f"{shim}{os.pathsep}{os.environ.get('PATH', '')}"


def test_prove_runs_under_the_python_that_has_pytest(tmp_path, pytestless_python3_path):
    repo = make_repo(tmp_path / "repo", "one_test")
    rc, out = run_line(command_lines("eval-prove")[0], repo, pytestless_python3_path)
    assert rc == 0, out
    assert "PROVEN" in out and "CANNOT PROVE" not in out, out


def test_init_counts_the_real_suite_when_python3_lacks_pytest(tmp_path, pytestless_python3_path):
    repo = make_repo(tmp_path / "repo", "one_test")
    rc, out = run_line(command_lines("eval-init")[0], repo, pytestless_python3_path)
    assert rc == 0, out
    assert "pytest collection failed" not in out, out


def test_output_is_utf8_so_dashes_survive(tmp_path, default_path):
    """Tools print em dashes; on Windows a piped stdout defaulted to cp1252 and
    Claude Code showed them as U+FFFD."""
    repo = make_repo(tmp_path / "repo", "one_test")
    rc, out = run_line(command_lines("eval-prove")[0], repo, default_path)
    assert rc == 0, out
    assert "\u2014" in out and "\ufffd" not in out, out
