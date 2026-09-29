"""Plugin-structure self-validation — the plugin gates itself.

Mirrors the checks `claude plugin validate --strict` performs, so CI catches
a broken manifest or frontmatter before any submission: manifest schema,
kebab-case name, component files present, YAML frontmatter parses with a
description, no CLAUDE.md at plugin root, templates lint clean.
"""
import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))
from registry_lint import lint_registry  # noqa: E402


def test_manifest_schema():
    m = json.loads((ROOT / ".claude-plugin/plugin.json").read_text())
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", m["name"])
    for key in ("version", "description", "license", "repository", "homepage"):
        assert m.get(key), key
    assert m["author"]["name"]
    assert m["homepage"].startswith("https://")
    assert re.fullmatch(r"\d+\.\d+\.\d+", m["version"])


def frontmatter(path: Path) -> dict:
    text = path.read_text()
    assert text.startswith("---\n"), path
    fm = text.split("---\n", 2)[1]
    data = yaml.safe_load(fm)
    assert isinstance(data, dict), path
    return data


def test_commands_frontmatter():
    cmds = sorted((ROOT / "commands").glob("*.md"))
    assert {c.stem for c in cmds} == {"eval-init", "eval-gate", "eval-baseline", "conductor"}
    for c in cmds:
        data = frontmatter(c)
        assert data.get("description"), c
        assert len(data["description"]) < 200, c


def test_skills_frontmatter():
    skills = sorted((ROOT / "skills").glob("*/SKILL.md"))
    assert {s.parent.name for s in skills} == {"eval-gates", "evidence-discipline"}
    for s in skills:
        data = frontmatter(s)
        assert data.get("description"), s


def test_core_files_present_and_stdlib_plus_yaml_only():
    core = {p.name for p in (ROOT / "core").iterdir()}
    assert {"promote.py", "compare.py", "registry_lint.py", "baseline.py",
            "conductor.py", "steps.yaml"} <= core
    banned = re.compile(r"^\s*(import|from)\s+(requests|numpy|pandas|pydantic|httpx)\b", re.M)
    for p in (ROOT / "core").glob("*.py"):
        assert not banned.search(p.read_text()), p


def test_template_registry_lints_clean():
    assert lint_registry(yaml.safe_load((ROOT / "templates/registry.yaml").read_text())) == []


def test_no_claude_md_at_root():
    assert not (ROOT / "CLAUDE.md").exists()


def test_no_personal_or_client_strings():
    banned = re.compile(r"appealforge|rehanrana11", re.I)
    for p in ROOT.rglob("*"):
        if p.is_file() and p.suffix in {".py", ".md", ".yaml", ".yml", ".json"} \
                and ".git" not in p.parts and p.name != "test_plugin_structure.py":
            assert not banned.search(p.read_text(errors="ignore")), p
