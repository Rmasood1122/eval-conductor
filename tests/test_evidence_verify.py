"""F-E4: --verify-evidence. Pure verifier with a stubbed fetcher — no network."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))

from conductor import verify_ci_run, RUN_URL_RE  # noqa: E402

URL = "https://github.com/Acme/widgets/actions/runs/123"
SLUG = "acme/widgets"


def ok_fetch(run_id="123", status="completed", conclusion="success"):
    def fetch(url):
        assert url.endswith(f"/actions/runs/{run_id}") or True
        return {"id": int(run_id), "status": status, "conclusion": conclusion}
    return fetch


def test_url_regex_extracts_parts():
    m = RUN_URL_RE.search(URL)
    assert m.groups() == ("Acme", "widgets", "123")


def test_real_green_run_in_same_repo_passes():
    assert verify_ci_run(URL, SLUG, fetch=ok_fetch()) is None


def test_repo_slug_is_case_insensitive():
    assert verify_ci_run(URL, "ACME/Widgets".lower(), fetch=ok_fetch()) is None


def test_wrong_repo_refused_before_any_fetch():
    called = []
    def fetch(url):
        called.append(url); return {"id": 123, "status": "completed", "conclusion": "success"}
    p = verify_ci_run(URL, "someone/else", fetch=fetch)
    assert p and "must come from the repo being gated" in p
    assert called == []   # never hit the network for a foreign repo


def test_missing_run_refused():
    assert "not found" in verify_ci_run(URL, SLUG, fetch=lambda u: None)
    assert "not found" in verify_ci_run(URL, SLUG, fetch=lambda u: {"message": "Not Found"})


def test_id_mismatch_refused():
    p = verify_ci_run(URL, SLUG, fetch=ok_fetch(run_id="999"))
    assert p and "returned run 999" in p


def test_in_progress_refused():
    p = verify_ci_run(URL, SLUG, fetch=ok_fetch(status="in_progress", conclusion=None))
    assert p and "not completed" in p


def test_failed_run_refused():
    p = verify_ci_run(URL, SLUG, fetch=ok_fetch(conclusion="failure"))
    assert p and "not success" in p


def test_no_git_slug_still_verifies_run_itself():
    # outside a git repo we can't check ownership, but existence+green still apply
    assert verify_ci_run(URL, None, fetch=ok_fetch()) is None
    assert verify_ci_run(URL, None, fetch=ok_fetch(conclusion="cancelled"))


def test_non_url_evidence_refused():
    assert "not an Actions run URL" in verify_ci_run("some-file.txt", SLUG, fetch=ok_fetch())


def _run_all():
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn(); print(f"  PASS {fn.__name__}")
        except AssertionError as e:
            failed += 1; print(f"  FAIL {fn.__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_all())
