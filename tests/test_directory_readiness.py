"""Directory-readiness battery — 72 grounded checks that must pass before this
plugin is submitted to (and approved in) Anthropic's plugin directory.

This is the verifiable-evals discipline turned on our own submission: instead of
asserting "it's fine," every claim a reviewer cares about is a mechanical check
that runs in CI. Grouped into ten categories (manifest, userConfig, layout,
secrets, network, code-safety, file-writes, docs/listing, functional smoke, and
a self-count). Each check is a (id, description, fn) triple; fn returns
(ok: bool, detail: str).

Grounded in the Claude Code plugin manifest reference and the directory
submission rules. Filesystem-based (no git dependency) so it also holds for a
vendored copy.
"""
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import pytest

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "core"
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(CORE))

# ---- shared source snapshots (read once) ---------------------------------
PLUGIN = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())
MARKET = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text())
PY_FILES = {p: p.read_text(encoding="utf-8")
            for p in list(CORE.glob("*.py")) + list(SCRIPTS.glob("*.py"))}
ALL_SRC = "\n".join(PY_FILES.values())
RESERVED_PREFIXES = ("claude-", "anthropic-", "anthropics-", "cc-plugin-")
RESERVED_EXACT = {"claude", "anthropic", "anthropics", "claude-code", "claude-mods"}
UCFG_ALLOWED = {"type", "title", "description", "required", "default",
                "options", "multiple", "sensitive", "min", "max"}
UCFG_TYPES = {"string", "number", "boolean", "directory", "file"}
EXPECTED_COMMANDS = {"eval-init", "eval-gate", "eval-baseline", "eval-import",
                     "eval-explain", "eval-verify", "eval-prove", "eval-seal",
                     "conductor"}


def _frontmatter(text):
    m = re.search(r"^---\n(.*?)\n---", text, re.S)
    return m.group(1) if m else ""


def _desc(fm):
    m = re.search(r"description:\s*(.+)", fm)
    return m.group(1).strip() if m else ""


# ==========================================================================
# A. MANIFEST VALIDITY (12)
# ==========================================================================
def m_valid_json(_): return True, "plugin.json parsed"
def m_name(_): return bool(PLUGIN.get("name")), f"name={PLUGIN.get('name')!r}"
def m_kebab(_):
    n = PLUGIN.get("name", "")
    return bool(re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", n)), f"name={n!r}"
def m_not_reserved(_):
    n = PLUGIN.get("name", "").lower()
    bad = n in RESERVED_EXACT or n.startswith(RESERVED_PREFIXES)
    return not bad, f"name={n!r}"
def m_version(_): return bool(PLUGIN.get("version")), f"v={PLUGIN.get('version')}"
def m_description(_):
    d = PLUGIN.get("description", "")
    return 30 <= len(d) <= 2000, f"len={len(d)}"
def m_author(_):
    return bool((PLUGIN.get("author") or {}).get("name")), "author.name"
def m_homepage_url(_):
    u = urlparse(PLUGIN.get("homepage", ""))
    return u.scheme == "https" and bool(u.netloc), PLUGIN.get("homepage", "")
def m_repository(_): return bool(PLUGIN.get("repository")), "repository set"
def m_license(_):
    return PLUGIN.get("license") == "MIT" and (ROOT / "LICENSE").exists(), "MIT + LICENSE"
def m_keywords(_):
    k = PLUGIN.get("keywords")
    return isinstance(k, list) and all(isinstance(x, str) for x in k) and bool(k), f"{len(k or [])} tags"
def m_icon_exists(_):
    icon = PLUGIN.get("icon", "")
    rel = icon[2:] if icon.startswith("./") else icon
    p = (ROOT / rel) if icon else None
    return bool(p and p.exists()), icon


# ==========================================================================
# B. USERCONFIG CORRECTNESS (6)
# ==========================================================================
def u_present(_): return isinstance(PLUGIN.get("userConfig"), dict), "userConfig block"
def u_keys(_):
    return set(PLUGIN.get("userConfig", {})) == {"receipt_key", "github_token"}, \
        str(set(PLUGIN.get("userConfig", {})))
def u_strict_keys(_):
    for k, v in PLUGIN.get("userConfig", {}).items():
        bad = set(v) - UCFG_ALLOWED
        if bad:
            return False, f"{k} has disallowed keys {bad}"
    return True, "all options strict"
def u_types(_):
    return all(v.get("type") in UCFG_TYPES for v in PLUGIN.get("userConfig", {}).values()), "types ok"
def u_sensitive(_):
    return all(v.get("sensitive") is True for v in PLUGIN.get("userConfig", {}).values()), \
        "both sensitive"
def u_title_desc(_):
    return all(v.get("title") and v.get("description") for v in PLUGIN.get("userConfig", {}).values()), \
        "title+description present"


# ==========================================================================
# C. LAYOUT & COMPONENTS (11)
# ==========================================================================
def c_no_bin(_): return not (ROOT / "bin").is_dir(), "no top-level bin/ (claude.ai would refuse)"
def c_no_root_claudemd(_): return not (ROOT / "CLAUDE.md").exists(), "no root CLAUDE.md"
def c_commands_dir(_): return (ROOT / "commands").is_dir(), "commands/ exists"
def c_command_set(_):
    got = {p.stem for p in (ROOT / "commands").glob("*.md")}
    return got == EXPECTED_COMMANDS, f"got {sorted(got)}"
def c_cmd_frontmatter(_):
    for p in (ROOT / "commands").glob("*.md"):
        if not _desc(_frontmatter(p.read_text())):
            return False, f"{p.name} missing description"
    return True, "all commands have a description"
def c_cmd_desc_len(_):
    for p in (ROOT / "commands").glob("*.md"):
        d = _desc(_frontmatter(p.read_text()))
        if len(d) >= 200:
            return False, f"{p.name} description {len(d)}>=200"
    return True, "all command descriptions < 200"
def c_skills_dir(_): return (ROOT / "skills").is_dir(), "skills/ exists"
def c_skills_have_md(_):
    dirs = [d for d in (ROOT / "skills").iterdir() if d.is_dir()]
    return bool(dirs) and all((d / "SKILL.md").exists() for d in dirs), f"{len(dirs)} skills"
def c_skills_frontmatter(_):
    for s in (ROOT / "skills").glob("*/SKILL.md"):
        fm = _frontmatter(s.read_text())
        if not re.search(r"name:\s*\S", fm) or not _desc(fm):
            return False, f"{s.parent.name} missing name/description"
    return True, "skills have name+description"
def c_no_undeclared_mcp(_):
    return not (ROOT / ".mcp.json").exists() and "mcpServers" not in PLUGIN, "no MCP servers"
def c_no_autoexec(_):
    hits = [p for p in ("hooks/hooks.json", "monitors/monitors.json", "settings.json")
            if (ROOT / p).exists()]
    keys = [k for k in ("hooks", "experimental", "settings") if k in PLUGIN]
    return not hits and not keys, f"files={hits} keys={keys}"


# ==========================================================================
# D. SECRETS (8)
# ==========================================================================
def s_no_keyfile(_):
    return not list(ROOT.rglob(".receipt-key")), "no .receipt-key in tree"
def s_no_key_pem(_):
    bad = [p for p in list(ROOT.rglob("*.key")) + list(ROOT.rglob("*.pem"))
           if ".git/" not in str(p)]
    return not bad, f"{bad}"
def s_no_committed_receipts(_):
    # a receipts/ or seals/ dir with real receipts does not belong in THIS repo
    bad = [p for p in list(ROOT.rglob("evals/receipts")) + list(ROOT.rglob("evals/seals"))
           if p.is_dir() and ".git/" not in str(p)]
    return not bad, f"{bad}"
def s_gitignore_key(_):
    gi = (ROOT / ".gitignore").read_text() if (ROOT / ".gitignore").exists() else ""
    return "evals/.receipt-key" in gi, "key gitignored"
def s_gitignore_wedge(_):
    gi = (ROOT / ".gitignore").read_text() if (ROOT / ".gitignore").exists() else ""
    return ".wedge-baseline.json" in gi and ".eval-prove-junit.xml" in gi, "wedge artifacts gitignored"
def s_no_real_gh_token(_):
    return not re.search(r"ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}", ALL_SRC), \
        "no GitHub token literal"
def s_no_pem_block(_):
    return "-----BEGIN" not in ALL_SRC, "no PEM private-key block"
def s_hexkeys_are_fixtures(_):
    # any 64-hex literal in source must be an obvious repeated-byte TEST fixture
    for h in re.findall(r"[0-9a-f]{64}", ALL_SRC):
        if len(set(h[i:i+2] for i in range(0, 64, 2))) > 1:  # not a single repeated byte
            return False, f"high-entropy 64-hex literal: {h[:12]}…"
    return True, "only repeated-byte test fixtures"


# ==========================================================================
# E. NETWORK (6)
# ==========================================================================
def n_no_other_http_libs(_):
    return not re.search(r"\bimport\s+(requests|httpx|aiohttp|socket|smtplib|ftplib)\b", ALL_SRC), \
        "only urllib"
def n_urlopen_only_conductor(_):
    users = [p.name for p, t in PY_FILES.items() if "urlopen" in t]
    return users == ["conductor.py"], f"urlopen in {users}"
def n_github_host(_):
    return "api.github.com" in PY_FILES.get(CORE / "conductor.py", ""), "targets api.github.com"
def n_gated_by_flag(_):
    t = PY_FILES.get(CORE / "conductor.py", "")
    return "verify_evidence" in t and "fetch_json" in t, "behind --verify-evidence"
def n_shields_is_string(_):
    t = PY_FILES.get(CORE / "wedge.py", "")
    # shields.io appears, but never passed to a request/urlopen
    return "shields.io" in t and "urlopen" not in t and "urllib" not in t, "badge URL is plain text"
def n_documented(_):
    sec = (ROOT / "SECURITY.md").read_text()
    return "api.github.com" in sec and "telemetry" in sec.lower(), "outbound call documented"


# ==========================================================================
# F. CODE SAFETY (8)
# ==========================================================================
def x_no_eval_exec(_):
    return not re.search(r"\beval\(|\bexec\(|os\.system\(", ALL_SRC), "no eval/exec/os.system"
def x_shelltrue_only_two(_):
    users = sorted(p.name for p, t in PY_FILES.items() if "shell=True" in t)
    return users == ["baseline.py", "wedge.py"], f"shell=True in {users}"
def x_shelltrue_commented(_):
    for p, t in PY_FILES.items():
        if "shell=True" in t and "SECURITY:" not in t:
            return False, f"{p.name} shell=True lacks SECURITY note"
    return True, "every shell=True carries a SECURITY note"
def x_yaml_safe(_):
    return "yaml.load(" not in ALL_SRC or "Loader" in ALL_SRC, "yaml.safe_load only"
def x_no_pickle(_):
    return "pickle.load" not in ALL_SRC, "no pickle deserialization"
def x_wedge_run_timeout(_):
    t = PY_FILES.get(CORE / "wedge.py", "")
    return "shell=True, timeout=" in t, "user --run bounded by timeout"
def x_no_rmrf(_):
    return not re.search(r"rm\s+-rf|shutil\.rmtree", ALL_SRC), "no recursive delete"
def x_no_download_run_in_core(_):
    core_src = "\n".join(t for p, t in PY_FILES.items() if p.parent.name == "core")
    return not re.search(r"curl\s|wget\s|\|\s*bash|\|\s*sh\b", core_src), "no download-and-run in core/"


# ==========================================================================
# G. FILE-WRITE SCOPE (6)
# ==========================================================================
def f_no_abs_write(_):
    return not re.search(r"""open\(\s*['"]/|Path\(\s*['"]/[^)]*\)\.write""", ALL_SRC), \
        "no absolute-path writes"
def f_no_home_write(_):
    return not re.search(r"expanduser|Path\.home\(\)", ALL_SRC), "no writes under $HOME"
def f_key_chmod(_):
    return "chmod(0o600)" in PY_FILES.get(CORE / "eval_receipt.py", ""), "key file chmod 600"
def f_init_guards_overwrite(_):
    t = PY_FILES.get(SCRIPTS / "eval_init.py", "")
    return "force" in t and "not key_path.exists()" in t, "eval_init guards overwrite"
def f_receipts_relative(_):
    t = PY_FILES.get(CORE / "eval_receipt.py", "")
    return 'DEFAULT_RECEIPTS_DIR = "evals/receipts"' in t, "receipts under evals/ (relative)"
def f_no_tmp_etc(_):
    return not re.search(r"""['"]/tmp/|['"]/etc/|['"]/var/""", ALL_SRC), "no /tmp /etc /var writes"


# ==========================================================================
# H. DOCS & LISTING INTEGRITY (9)
# ==========================================================================
def d_readme(_): return (ROOT / "README.md").exists(), "README.md"
def d_license(_): return (ROOT / "LICENSE").exists(), "LICENSE"
def d_privacy(_): return (ROOT / "PRIVACY.md").exists(), "PRIVACY.md"
def d_security(_): return (ROOT / "SECURITY.md").exists(), "SECURITY.md"
def d_casestudy_link(_):
    rm = (ROOT / "README.md").read_text()
    if "docs/CASE_STUDY_verifiable_evals.md" not in rm:
        return True, "no case-study link (ok)"
    return (ROOT / "docs" / "CASE_STUDY_verifiable_evals.md").exists(), "case-study target exists"
def d_readme_cmd_refs(_):
    rm = (ROOT / "README.md").read_text()
    # command invocations look like `/eval-gate` (backtick-wrapped); exclude the
    # plugin/marketplace name "eval-conductor", which is not a command.
    refs = set(re.findall(r"`/(eval-[a-z]+)`", rm)) - {"eval-conductor"}
    if "`/conductor`" in rm:
        refs.add("conductor")
    missing = {r for r in refs if not (ROOT / "commands" / f"{r}.md").exists()}
    return not missing, f"refs={sorted(refs)} missing={missing}"
def d_install_marketplace(_):
    rm = (ROOT / "README.md").read_text()
    return MARKET["name"] in rm, f"install cites {MARKET['name']}"
def d_marketplace_entry(_):
    names = [p["name"] for p in MARKET.get("plugins", [])]
    return names == [PLUGIN["name"]], f"entry {names}"
def d_listing_urls_https(_):
    for k in ("documentationUrl", "supportUrl", "privacyPolicyUrl"):
        u = urlparse(PLUGIN.get(k, ""))
        if u.scheme != "https" or not u.netloc:
            return False, f"{k} not https"
    return True, "listing URLs are https"


# ==========================================================================
# I. FUNCTIONAL SMOKE (6)
# ==========================================================================
def _write_junit(d, tests, failures=0):
    p = Path(d) / "j.xml"
    p.write_text(f'<testsuite tests="{tests}" failures="{failures}" errors="0" skipped="0"></testsuite>')
    return p

def p_compile_all(_):
    import py_compile
    for p in PY_FILES:
        py_compile.compile(str(p), doraise=True)
    return True, "all core/scripts .py compile"
def p_wedge_promote(_):
    import wedge
    d = tempfile.mkdtemp()
    res = wedge.run(work_dir=d, junit_path=_write_junit(d, 5, 0),
                    receipts_dir=Path(d)/"r", baseline_file=Path(d)/"bl.json",
                    key_path=Path(d)/"k")
    return bool(res["decision"] == "PROMOTE" and res["receipt_path"]), "wedge first run PROMOTE + receipt"
def p_wedge_block(_):
    import wedge
    d = tempfile.mkdtemp()
    kw = dict(receipts_dir=Path(d)/"r", baseline_file=Path(d)/"bl.json", key_path=Path(d)/"k")
    wedge.run(work_dir=d, junit_path=_write_junit(d, 10, 0), **kw)
    res = wedge.run(work_dir=d, junit_path=_write_junit(d, 10, 4), **kw)
    return res["decision"] == "BLOCK", "wedge regression BLOCK"
def p_receipt_verify(_):
    import wedge, eval_receipt as er
    d = tempfile.mkdtemp()
    wedge.run(work_dir=d, junit_path=_write_junit(d, 3, 0),
              receipts_dir=Path(d)/"r", baseline_file=Path(d)/"bl.json", key_path=Path(d)/"k")
    rc = er.verify(Path(d)/"r", key=er.load_key_from(str(Path(d)/"k")))
    return rc == 0, "signed receipt chain verifies"
def p_prereg_drift(_):
    import prereg
    d = Path(tempfile.mkdtemp()); reg = d/"registry.yaml"
    reg.write_text("- name: m\n  direction: higher_better\n  threshold: 0.9\n  noise_band: 0.0\n  blocking: hard\n")
    prereg.create_seal(registry_path=reg, seals_dir=d/"seals", bands=None, key=None)
    reg.write_text("- name: m\n  direction: higher_better\n  threshold: 0.8\n  noise_band: 0.0\n  blocking: hard\n")
    st = prereg.check_drift(reg, seals_dir=d/"seals", key=None)
    return st["registry_match"] is False, "pre-reg catches a drifted bar"
def p_nan_blocks(_):
    from compare import decide
    reg = [{"name": "m", "direction": "higher_better", "threshold": 0.5,
            "noise_band": 0.0, "blocking": "hard"}]
    dec, _v = decide(reg, {"m": float("nan")}, None)
    return dec == "BLOCK", "NaN score fails closed (BLOCK)"


# ==========================================================================
# Registry — exactly 72 checks
# ==========================================================================
CHECKS = [
    ("M1", "plugin.json is valid JSON", m_valid_json),
    ("M2", "name is present", m_name),
    ("M3", "name is kebab-case", m_kebab),
    ("M4", "name is not reserved (claude/anthropic)", m_not_reserved),
    ("M5", "version is set", m_version),
    ("M6", "description present, reasonable length", m_description),
    ("M7", "author.name present", m_author),
    ("M8", "homepage parses as https URL", m_homepage_url),
    ("M9", "repository set", m_repository),
    ("M10", "license MIT + LICENSE file", m_license),
    ("M11", "keywords is a non-empty string list", m_keywords),
    ("M12", "icon path exists on disk", m_icon_exists),
    ("U1", "userConfig block present", u_present),
    ("U2", "userConfig keys == {receipt_key, github_token}", u_keys),
    ("U3", "userConfig options use only allowed keys", u_strict_keys),
    ("U4", "userConfig option types valid", u_types),
    ("U5", "credential options are sensitive:true", u_sensitive),
    ("U6", "userConfig options have title+description", u_title_desc),
    ("C1", "no top-level bin/ (claude.ai refuses it)", c_no_bin),
    ("C2", "no CLAUDE.md at plugin root", c_no_root_claudemd),
    ("C3", "commands/ directory exists", c_commands_dir),
    ("C4", "exactly the expected 9 commands", c_command_set),
    ("C5", "every command has a description", c_cmd_frontmatter),
    ("C6", "every command description < 200 chars", c_cmd_desc_len),
    ("C7", "skills/ directory exists", c_skills_dir),
    ("C8", "every skill has SKILL.md", c_skills_have_md),
    ("C9", "every skill has name+description", c_skills_frontmatter),
    ("C10", "no undeclared MCP servers", c_no_undeclared_mcp),
    ("C11", "no auto-executing components (hooks/monitors/settings)", c_no_autoexec),
    ("S1", "no .receipt-key committed", s_no_keyfile),
    ("S2", "no .key/.pem files in tree", s_no_key_pem),
    ("S3", "no real receipts/seals committed in this repo", s_no_committed_receipts),
    ("S4", "signing key is gitignored", s_gitignore_key),
    ("S5", "wedge artifacts are gitignored", s_gitignore_wedge),
    ("S6", "no GitHub token literal in source", s_no_real_gh_token),
    ("S7", "no PEM private-key block in source", s_no_pem_block),
    ("S8", "64-hex literals are repeated-byte test fixtures only", s_hexkeys_are_fixtures),
    ("N1", "no requests/httpx/socket/smtplib imports", n_no_other_http_libs),
    ("N2", "urlopen appears only in conductor.py", n_urlopen_only_conductor),
    ("N3", "network call targets api.github.com", n_github_host),
    ("N4", "network call is behind --verify-evidence", n_gated_by_flag),
    ("N5", "shields.io badge URL is plain text, never fetched", n_shields_is_string),
    ("N6", "the single outbound call is documented in SECURITY.md", n_documented),
    ("X1", "no eval()/exec()/os.system", x_no_eval_exec),
    ("X2", "shell=True only in wedge.py and baseline.py", x_shelltrue_only_two),
    ("X3", "every shell=True carries a SECURITY note", x_shelltrue_commented),
    ("X4", "yaml.safe_load only (no yaml.load)", x_yaml_safe),
    ("X5", "no pickle deserialization", x_no_pickle),
    ("X6", "user --run command is bounded by a timeout", x_wedge_run_timeout),
    ("X7", "no rm -rf / shutil.rmtree", x_no_rmrf),
    ("X8", "no download-and-run in executed core/ code", x_no_download_run_in_core),
    ("F1", "no absolute-path file writes", f_no_abs_write),
    ("F2", "no writes under $HOME", f_no_home_write),
    ("F3", "signing key file chmod 600", f_key_chmod),
    ("F4", "eval_init never clobbers without --force", f_init_guards_overwrite),
    ("F5", "receipts written under evals/ (relative)", f_receipts_relative),
    ("F6", "no writes to /tmp /etc /var", f_no_tmp_etc),
    ("D1", "README.md exists", d_readme),
    ("D2", "LICENSE exists", d_license),
    ("D3", "PRIVACY.md exists", d_privacy),
    ("D4", "SECURITY.md exists", d_security),
    ("D5", "case-study link target exists", d_casestudy_link),
    ("D6", "every README command ref maps to a command file", d_readme_cmd_refs),
    ("D7", "install instructions cite the real marketplace name", d_install_marketplace),
    ("D8", "marketplace entry name matches the plugin", d_marketplace_entry),
    ("D9", "directory-listing URL fields are https", d_listing_urls_https),
    ("P1", "all core/scripts .py compile", p_compile_all),
    ("P2", "wedge first run PROMOTE + emits a receipt", p_wedge_promote),
    ("P3", "wedge regression run BLOCKs", p_wedge_block),
    ("P4", "signed receipt chain verifies", p_receipt_verify),
    ("P5", "pre-registration catches a drifted bar", p_prereg_drift),
    ("P6", "NaN score fails closed (BLOCK)", p_nan_blocks),
]


def test_exactly_72_checks():
    assert len(CHECKS) == 72, f"battery must hold exactly 72 checks, has {len(CHECKS)}"
    assert len({c[0] for c in CHECKS}) == 72, "check ids must be unique"


@pytest.mark.parametrize("check_id,desc,fn", CHECKS, ids=[c[0] for c in CHECKS])
def test_directory_readiness(check_id, desc, fn):
    ok, detail = fn(ROOT)
    assert ok, f"[{check_id}] {desc} — {detail}"


if __name__ == "__main__":
    # Standalone battery report: one line per check, pass/fail, then a summary.
    passed = 0
    for cid, desc, fn in CHECKS:
        try:
            ok, detail = fn(ROOT)
        except Exception as exc:  # noqa: BLE001
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        print(f"  {'PASS' if ok else 'FAIL'}  [{cid}] {desc}" + ("" if ok else f"  — {detail}"))
        passed += ok
    print(f"\n{passed}/{len(CHECKS)} checks passed")
    raise SystemExit(0 if passed == len(CHECKS) else 1)
