"""The PyPI package must run the same engine as the plugin.

core/ is what the plugin runs; src/eval_conductor/_core/ is a copy that ships on
PyPI as the `eval-conductor` CLI. Nothing kept them in step, and the copy drifted:
1.4.1 on PyPI still printed a brightgreen "PROVEN 0/0" badge for a run that
collected zero tests, a bug core/ had already fixed. Every core file must now
match its src twin byte-for-byte after normalizing line endings (Windows
checkouts use CRLF), except for differences listed in INTENDED with a reason.
"""
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "core"
SRC_CORE = ROOT / "src" / "eval_conductor" / "_core"

# file name -> why its src copy may differ from core/. Empty on purpose: add an
# entry only with a reason a reviewer can check.
INTENDED: dict[str, str] = {}

SHIPPED = sorted([*CORE.glob("*.py"), *CORE.glob("*.yaml")])


def _normalized(p: Path) -> bytes:
    return p.read_bytes().replace(b"\r\n", b"\n")


@pytest.mark.parametrize("core_file", SHIPPED, ids=[p.name for p in SHIPPED])
def test_src_twin_matches_core(core_file):
    if core_file.name in INTENDED:
        pytest.skip(INTENDED[core_file.name])
    twin = SRC_CORE / core_file.name
    assert twin.exists(), f"{core_file.name} is missing from the PyPI package"
    assert _normalized(twin) == _normalized(core_file), (
        f"src/eval_conductor/_core/{core_file.name} has drifted from "
        f"core/{core_file.name} — copy core over it")


def test_src_has_no_orphans():
    orphans = {p.name for p in SRC_CORE.glob("*.py")} - {p.name for p in SHIPPED} \
        - {"__init__.py"}
    assert not orphans, f"src/_core files with no core/ original: {sorted(orphans)}"


def test_intended_differences_name_real_files():
    assert set(INTENDED) <= {p.name for p in SHIPPED}


def test_pypi_prove_cannot_prove_zero_tests(tmp_path):
    junit = tmp_path / "zero.xml"
    junit.write_text('<testsuite tests="0" failures="0" errors="0" skipped="0">'
                     '</testsuite>')
    code = ("import sys; sys.path.insert(0, sys.argv.pop(1)); "
            "from eval_conductor.cli import main; raise SystemExit(main())")
    r = subprocess.run([sys.executable, "-c", code, str(ROOT / "src"), "prove",
                        "--junit", str(junit)],
                       cwd=tmp_path, capture_output=True, text=True)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "CANNOT PROVE" in r.stderr
    assert "brightgreen" not in r.stdout and "PROVEN" not in r.stdout
