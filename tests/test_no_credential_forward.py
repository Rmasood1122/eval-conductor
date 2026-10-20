"""/conductor --verify-evidence is anonymous: the plugin reads no credential and
sends none. The one outbound request carries no Authorization header, even when
the installer has GITHUB_TOKEN set."""
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

import conductor  # noqa: E402

SHIPPED = [p for d in ("core", "scripts", "src", "mcp") for p in (ROOT / d).rglob("*.py")
           if "__pycache__" not in p.parts]


def test_request_is_anonymous_even_with_a_token_in_the_environment(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "must-not-be-sent")
    seen = {}

    class Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b'{"id": 1}'

    def fake_urlopen(req, timeout=None):
        seen["headers"] = {k.lower(): v for k, v in req.header_items()}
        return Resp()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    assert conductor.fetch_json("https://api.github.com/repos/o/r/actions/runs/1") == {"id": 1}
    assert "authorization" not in seen["headers"]
    assert "must-not-be-sent" not in repr(seen["headers"])


def test_no_shipped_code_reads_github_token_or_sets_authorization():
    assert any(p.name == "conductor.py" for p in SHIPPED), "scan found nothing to check"
    offenders = sorted(str(p.relative_to(ROOT)) for p in SHIPPED
                       if any(s in p.read_text(encoding="utf-8", errors="replace")
                              for s in ("GITHUB_TOKEN", "Authorization")))
    assert not offenders, f"credential read or forward in: {offenders}"


def test_private_or_unreachable_run_fails_closed_and_says_why():
    problem = conductor.verify_ci_run(
        "https://github.com/o/r/actions/runs/42", "o/r", fetch=lambda url: None)
    assert problem and "fail closed" in problem and "private repo" in problem
