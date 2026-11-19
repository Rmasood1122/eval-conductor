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


def _run_step(step, env, tmp_path):
    """Run a composite step's script the way the runner does: inputs become
    env values, and anything still written as ${{ inputs.x }} is substituted
    textually, exactly as GitHub would before bash ever sees it."""
    script = step["run"]
    for k, v in env.items():
        script = script.replace("${{ inputs.%s }}" % k, v)
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    stub = bindir / "eval-conductor"
    stub.write_text("#!/bin/sh\nfor a in \"$@\"; do echo \"ARG<$a>\"; done\n")
    stub.chmod(0o755)
    pip = bindir / "python"
    real = shutil.which("python3")
    # `python -m pip` must not hit the network; anything else is real python
    pip.write_text(f'#!/bin/sh\nif [ "$1" = "-m" ] && [ "$2" = "pip" ]; then '
                   f'echo "PIP $*"; exit 0; fi\nexec "{real}" "$@"\n')
    pip.chmod(0o755)
    step_env = {k: v.replace("${{ inputs.", "").replace(" }}", "")
                for k, v in (step.get("env") or {}).items()}
    full = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}")
    for name, ref in step_env.items():
        full[name] = env.get(ref, "")
    return subprocess.run(["bash", "-c", script], env=full, cwd=tmp_path,
                          capture_output=True, text=True)


def test_args_cannot_run_shell(tmp_path):
    marker = tmp_path / "pwned"
    r = _run_step(_step(2), {"command": "prove",
                             "args": f'--junit r.xml $(touch {marker}); touch {marker}',
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
    r = _run_step(_step(2), {"command": f"prove; touch {marker}", "args": "",
                             "receipt-key": ""}, tmp_path)
    assert r.returncode != 0
    assert not marker.exists()


def test_version_cannot_run_shell(tmp_path):
    marker = tmp_path / "pwned"
    r = _run_step(_step(1), {"version": f'==1.0"; touch {marker}; echo "'},
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
