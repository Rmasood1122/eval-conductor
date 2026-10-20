"""The GitHub token for --verify-evidence: read in core/gh_auth.py (no URLs),
sent by core/conductor.py (no environment reads) — and only to api.github.com."""
import io
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))

import conductor  # noqa: E402
import gh_auth  # noqa: E402


def test_token_comes_from_github_token(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "tok-123")
    assert gh_auth.github_token() == "tok-123"


def test_blank_or_unset_token_is_none(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "   ")
    assert gh_auth.github_token() is None
    monkeypatch.delenv("GITHUB_TOKEN")
    assert gh_auth.github_token() is None


def _capture_requests(monkeypatch):
    sent = []

    def fake_urlopen(req, timeout=None):
        sent.append(req)
        return io.BytesIO(b'{"id": 1}')
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    return sent


def test_token_is_sent_to_the_github_api(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "tok-123")
    sent = _capture_requests(monkeypatch)
    assert conductor.fetch_json("https://api.github.com/repos/a/b/actions/runs/1") == {"id": 1}
    assert sent[0].get_header("Authorization") == "Bearer tok-123"


def test_token_is_never_sent_anywhere_else(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "tok-123")
    sent = _capture_requests(monkeypatch)
    conductor.fetch_json("https://api.github.com.evil.example/repos/a/b")
    conductor.fetch_json("https://example.com/api.github.com/x")
    assert all(r.get_header("Authorization") is None for r in sent)


def test_anonymous_without_a_token(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    sent = _capture_requests(monkeypatch)
    conductor.fetch_json("https://api.github.com/repos/a/b/actions/runs/1")
    assert sent[0].get_header("Authorization") is None
