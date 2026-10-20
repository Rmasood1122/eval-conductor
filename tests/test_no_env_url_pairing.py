"""No shipped .py file may both read the environment and contain a URL.

A file that reads a credential from the environment AND names an outbound URL
is the shape a credential-forwarding check looks for — the pattern a plugin
directory policy check has held plugins on. The token that /conductor
--verify-evidence sends is therefore read in core/gh_auth.py, which contains no
URL, and the request is built in core/conductor.py, which reads no environment.

The whole repository ships (the plugin installs the repo; src/ is the PyPI
package), so every .py file is checked, tests included. This file spells its
patterns so that it matches neither half itself.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", "__pycache__", "build", "dist", ".venv", "venv"}

ENV_READ = re.compile(r"\bos\s*\.\s*environ\b|\bgetenv\s*\("
                      r"|\bfrom\s+os\s+import\b[^\n]*\b(?:environ|getenv)\b")
URL = re.compile(r"\bhttps?:/{2}")


def pairs(text: str) -> bool:
    return bool(ENV_READ.search(text) and URL.search(text))


def shipped_py_files() -> list[Path]:
    return [p for p in ROOT.rglob("*.py")
            if not (set(p.relative_to(ROOT).parts) & SKIP_DIRS)
            and not any(part.endswith(".egg-info") for part in p.parts)]


def test_detector_catches_the_pairing():
    env = "os." + "environ"
    url = "https:" + "//" + "api.example.test/x"
    assert pairs(f"import os\ntok = {env}.get('T')\nu = '{url}'\n")
    assert pairs(f"import os\ntok = os.get{'env'}('T')\nu = '{url}'\n")
    assert not pairs(f"import os\ntok = {env}.get('T')\n")
    assert not pairs(f"u = '{url}'\n")


def test_no_shipped_file_reads_env_and_contains_a_url():
    files = shipped_py_files()
    assert any(p.name == "conductor.py" for p in files), "scan found nothing to check"
    offenders = sorted(str(p.relative_to(ROOT)) for p in files
                       if pairs(p.read_text(encoding="utf-8", errors="replace")))
    assert not offenders, (
        "these files both read the environment and contain a URL — move the env "
        f"read into a URL-free module (see core/gh_auth.py): {offenders}")
