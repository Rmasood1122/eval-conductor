"""Zero-config wedge (/eval-prove): one command turns a repo's existing test
suite into a signed proof + a pasteable PR badge, with NO registry authoring.
First run captures the bar; a later regression BLOCKs. Reuses the v1.2 receipt
engine and the existing junit/compare code.

Runs standalone or under pytest.
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "scripts"))

import wedge  # noqa: E402
import eval_receipt as er  # noqa: E402

KEY = bytes.fromhex("ef" * 32)


def _junit(tmp, tests, failures=0, errors=0, skipped=0, name="suite"):
    """Write a minimal JUnit XML and return its path."""
    xml = (f'<testsuite name="{name}" tests="{tests}" failures="{failures}" '
           f'errors="{errors}" skipped="{skipped}"></testsuite>')
    p = tmp / "junit.xml"
    p.write_text(xml)
    return p


def _run(tmp, junit, **kw):
    """Invoke the wedge against a prepared JUnit file in tmp."""
    return wedge.run(
        work_dir=tmp,
        junit_path=junit,
        receipts_dir=tmp / "evals" / "receipts",
        baseline_file=tmp / "evals" / ".wedge-baseline.json",
        key_path=tmp / "evals" / ".receipt-key",
        **kw,
    )


# --------------------------------------------------------------- first run
def test_first_run_all_pass_promotes_and_captures(tmp_path):
    j = _junit(tmp_path, tests=10, failures=0)
    res = _run(tmp_path, j)
    assert res["decision"] == "PROMOTE"
    assert res["scores"]["test_pass_rate"] == 1.0
    assert res["scores"]["test_count"] == 10
    # baseline captured
    bl = json.loads((tmp_path / "evals" / ".wedge-baseline.json").read_text())
    assert bl["test_pass_rate"] == 1.0 and bl["test_count"] == 10
    # receipt emitted
    assert res["receipt_path"] is not None
    assert Path(res["receipt_path"]).exists()
    # pasteable badge present
    assert "img.shields.io/badge/" in res["badge"]


def test_first_run_with_failures_does_not_false_block(tmp_path):
    """A flaky/failing suite on run one must still PROMOTE at its measured rate —
    a hardcoded 1.0 floor would kill the wedge."""
    j = _junit(tmp_path, tests=10, failures=2)
    res = _run(tmp_path, j)
    assert res["decision"] == "PROMOTE"
    assert res["scores"]["test_pass_rate"] == 0.8
    bl = json.loads((tmp_path / "evals" / ".wedge-baseline.json").read_text())
    assert bl["test_pass_rate"] == 0.8


def test_zero_tests_is_zero_rate(tmp_path):
    j = _junit(tmp_path, tests=0)
    res = _run(tmp_path, j)
    assert res["scores"]["test_pass_rate"] == 0.0


# --------------------------------------------------------------- regression
def test_second_run_pass_rate_drop_blocks(tmp_path):
    _run(tmp_path, _junit(tmp_path, tests=10, failures=0))      # bar: 1.0, 10
    res = _run(tmp_path, _junit(tmp_path, tests=10, failures=3))  # 0.7 now
    assert res["decision"] == "BLOCK"
    assert any("test_pass_rate" in v.get("metric", "") for v in res["verdicts"])


def test_second_run_test_count_drop_blocks(tmp_path):
    _run(tmp_path, _junit(tmp_path, tests=10, failures=0))      # bar: 10 tests
    res = _run(tmp_path, _junit(tmp_path, tests=7, failures=0))   # lost 3 tests
    assert res["decision"] == "BLOCK"


def test_bar_ratchets_up_not_down(tmp_path):
    _run(tmp_path, _junit(tmp_path, tests=10, failures=2))      # bar: 0.8
    _run(tmp_path, _junit(tmp_path, tests=10, failures=0))      # 1.0 -> PROMOTE, bar up
    bl = json.loads((tmp_path / "evals" / ".wedge-baseline.json").read_text())
    assert bl["test_pass_rate"] == 1.0
    # now a dip to 0.9 must BLOCK against the ratcheted 1.0, not the old 0.8
    res = _run(tmp_path, _junit(tmp_path, tests=10, failures=1))
    assert res["decision"] == "BLOCK"


def test_block_does_not_lower_the_bar(tmp_path):
    _run(tmp_path, _junit(tmp_path, tests=10, failures=0))      # bar 1.0
    _run(tmp_path, _junit(tmp_path, tests=10, failures=5))      # BLOCK, 0.5
    bl = json.loads((tmp_path / "evals" / ".wedge-baseline.json").read_text())
    assert bl["test_pass_rate"] == 1.0, "a BLOCK must never ratchet the bar down"


# --------------------------------------------------------------- proof
def test_receipt_verifies_and_records_decision(tmp_path):
    _run(tmp_path, _junit(tmp_path, tests=5, failures=0))
    rc = er.verify(tmp_path / "evals" / "receipts",
                   key=er.load_key_from(str(tmp_path / "evals" / ".receipt-key")))
    assert rc == 0


def test_auto_key_generated_and_signs(tmp_path):
    assert not (tmp_path / "evals" / ".receipt-key").exists()
    _run(tmp_path, _junit(tmp_path, tests=3, failures=0))
    assert (tmp_path / "evals" / ".receipt-key").exists(), "wedge must auto-gen a key"
    rp = next((tmp_path / "evals" / "receipts").rglob("*.json"))
    r = json.loads(rp.read_text())
    assert r.get("signing_version") == er.SIGNING and r.get("signature")


# --------------------------------------------------------------- zero-config
def test_no_registry_file_anywhere(tmp_path):
    _run(tmp_path, _junit(tmp_path, tests=4, failures=0))
    assert not list(tmp_path.rglob("registry.yaml")), "wedge must need no registry"


# --------------------------------------------------------------- guidance
def test_undetectable_suite_exits_2_with_guidance(tmp_path):
    # empty dir, no --junit: can't measure -> exit 2, helpful message, no traceback
    script = str(ROOT / "core" / "wedge.py")
    r = subprocess.run([sys.executable, script, "--dir", str(tmp_path)],
                       capture_output=True, text=True)
    assert r.returncode == 2
    assert "Traceback" not in r.stderr
    assert ("junit" in (r.stdout + r.stderr).lower()
            or "test" in (r.stdout + r.stderr).lower())


# --------------------------------------------------------------- CLI
def test_cli_junit_end_to_end(tmp_path):
    j = _junit(tmp_path, tests=6, failures=0)
    script = str(ROOT / "core" / "wedge.py")
    r = subprocess.run(
        [sys.executable, script, "--junit", str(j),
         "--receipts-dir", str(tmp_path / "r"),
         "--baseline-file", str(tmp_path / "bl.json"),
         "--receipt-key", str(tmp_path / "k")],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "img.shields.io/badge/" in r.stdout
    assert "PROVEN" in r.stdout.upper() or "PROMOTE" in r.stdout.upper()


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
