"""Hardening from the 1.4.3 audit. Each test here failed on 1.4.3 except the ones marked as guards.

- action.yml spliced ${{ inputs.* }} straight into `run:`, so a workflow that
  forwarded untrusted text (a PR title, a branch name) into `args` or
  `version` ran it as shell.
- verify accepted receipts carrying fields the signature does not cover.
- `python mcp_server.py` died with NameError: the __main__ guard ran before
  run() was defined.
"""
import ast
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

import eval_receipt as er  # noqa: E402

KEY = bytes.fromhex("9a" * 32)


# ------------------------------------------------------------------ action
def _step(i):
    return yaml.safe_load((ROOT / "action.yml").read_text())["runs"]["steps"][i]


# Imported by every python the step starts (via PYTHONPATH), on any OS: it
# stands in for pip (no network) and for the eval-conductor executable, so the
# test needs no POSIX shebang stubs and runs the same on the Windows job.
_SITECUSTOMIZE = """
import os, subprocess, sys
_argv = list(getattr(sys, "orig_argv", []))
if _argv[1:3] == ["-m", "pip"]:
    print("PIP " + " ".join(_argv[1:]), flush=True)
    os._exit(0)
_real_call = subprocess.call
def _call(cmd, *a, **kw):
    if isinstance(cmd, (list, tuple)) and cmd and cmd[0] == "eval-conductor":
        for x in cmd[1:]:
            print("ARG<%s>" % x, flush=True)
        return 0
    return _real_call(cmd, *a, **kw)
subprocess.call = _call
"""


def _bash():
    """The bash a GitHub runner uses for `shell: bash`: Git Bash on Windows.
    A bare "bash" there resolves to the WSL launcher in System32."""
    if sys.platform != "win32":
        return shutil.which("bash")
    git = shutil.which("git")
    if git:
        for up in Path(git).resolve().parents:
            cand = up / "bin" / "bash.exe"
            if cand.exists():
                return str(cand)
    found = shutil.which("bash")
    if found and "system32" not in found.lower():
        return found
    raise RuntimeError("Git Bash not found; GitHub's windows runners ship it")


def _run_step(step, env, tmp_path):
    """Run a composite step's script the way the runner does: inputs become
    env values, and anything still written as ${{ inputs.x }} is substituted
    textually, exactly as GitHub would before bash ever sees it."""
    script = step["run"]
    for k, v in env.items():
        script = script.replace("${{ inputs.%s }}" % k, v)
    stubdir = tmp_path / "stub"
    stubdir.mkdir(exist_ok=True)
    (stubdir / "sitecustomize.py").write_text(_SITECUSTOMIZE)
    step_env = {k: v.replace("${{ inputs.", "").replace(" }}", "")
                for k, v in (step.get("env") or {}).items()}
    full = dict(os.environ, PYTHONPATH=str(stubdir))
    if not shutil.which("python"):          # the runner always has `python`
        bindir = tmp_path / "bin"
        bindir.mkdir(exist_ok=True)
        shim = bindir / "python"
        shim.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
        shim.chmod(0o755)
        full["PATH"] = f"{bindir}{os.pathsep}{full['PATH']}"
    for name, ref in step_env.items():
        full[name] = env.get(ref, "")
    return subprocess.run([_bash(), "-c", script], env=full, cwd=tmp_path,
                          capture_output=True, text=True)


def test_args_cannot_run_shell(tmp_path):
    marker = tmp_path / "pwned"
    m = marker.as_posix()
    r = _run_step(_step(2), {"command": "prove",
                             "args": f'--junit r.xml $(touch {m}); touch {m}',
                             "receipt-key": ""}, tmp_path)
    assert not marker.exists(), r.stdout + r.stderr


# guard: must keep passing
def test_args_quoting_still_works(tmp_path):
    r = _run_step(_step(2), {"command": "prove",
                             "args": '--run "pytest --junitxml={junit}"',
                             "receipt-key": ""}, tmp_path)
    assert r.returncode == 0, r.stderr
    assert "ARG<pytest --junitxml={junit}>" in r.stdout


def test_command_is_allowlisted(tmp_path):
    marker = tmp_path / "pwned"
    r = _run_step(_step(2), {"command": f"prove; touch {marker.as_posix()}", "args": "",
                             "receipt-key": ""}, tmp_path)
    assert r.returncode != 0
    assert not marker.exists()


def test_version_cannot_run_shell(tmp_path):
    marker = tmp_path / "pwned"
    r = _run_step(_step(1), {"version": f'==1.0"; touch {marker.as_posix()}; echo "'},
                  tmp_path)
    assert not marker.exists(), r.stdout + r.stderr
    assert r.returncode != 0


# guard: must keep passing
def test_valid_version_installs(tmp_path):
    r = _run_step(_step(1), {"version": "==1.4.4"}, tmp_path)
    assert r.returncode == 0, r.stderr
    assert "eval-conductor==1.4.4" in r.stdout


# ------------------------------------------------------------------ receipts
@pytest.mark.parametrize("field", ["_meta", "_debug", "prev_receipt_hash_verified"])
def test_unsigned_field_fails_verify(tmp_path, field):
    rd = tmp_path / "receipts"
    er.emit("PROMOTE", [], registry_path=None, candidate_path=None,
            baseline_path=None, manifest={"source": "test"},
            receipts_dir=rd, key=KEY)
    assert er.verify(rd, key=KEY) == 0
    p = next(rd.rglob("*.json"))
    r = json.loads(p.read_text())
    r[field] = {"approved_by": "release manager"}
    p.write_text(json.dumps(r, indent=2))
    assert er.verify(rd, key=KEY) == 1


# ------------------------------------------------------------------ mcp
def test_mcp_main_guard_comes_after_run():
    src = (ROOT / "src" / "eval_conductor" / "mcp_server.py").read_text()
    tree = ast.parse(src)
    order = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "run":
            order.append("def")
        if isinstance(node, ast.If) and "__main__" in ast.unparse(node.test):
            order.append("guard")
    assert order == ["def", "guard"]
