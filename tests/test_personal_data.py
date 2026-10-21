"""scripts/check_personal.py: the widened personal-data grep (R-1206, C-05, Q-26).

The grep covers src, tests, plugin, examples, README.md, CONTRIBUTING.md, templates, docs/samples
and .claude-plugin. The owner's name may stand in exactly two fields, `author.name` in
plugin.json and `owner.name` in marketplace.json; anything else fails. The names are read from
plugin.json and docs/requirements.md, so none is written in this file (it is grepped too).
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "check_personal.py"
NAME = "Ada Lovelace"  # an invented owner for the synthetic repos below


@pytest.fixture(scope="module")
def cp():
    spec = importlib.util.spec_from_file_location("check_personal", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _git_checkout() -> bool:
    if shutil.which("git") is None or not (REPO / ".git").exists():
        return False
    done = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--is-inside-work-tree"], capture_output=True,
                          text=True, timeout=60)  # fmt: skip
    return done.returncode == 0 and done.stdout.strip() == "true"


def test_the_repo_holds_the_owners_name_only_in_the_two_allowed_fields(cp):
    if not _git_checkout():
        pytest.skip("not a git checkout")
    words = cp.names()
    hits = cp.grep(REPO, words)
    assert cp.problems(REPO, words, hits) == []
    assert {path for path, _n, _t in hits} <= set(cp.ALLOWED)


def test_the_grep_covers_the_widened_paths(cp):
    for path in ("src", "tests", "plugin", "examples", "README.md", "templates", "docs/samples", ".claude-plugin"):
        assert path in cp.PATHS, path


def test_the_names_come_from_plugin_json_and_the_named_personas(cp):
    words = cp.names()
    author = json.loads((REPO / cp.PLUGIN_JSON).read_text(encoding="utf-8"))["author"]["name"]
    assert set(author.split()) <= set(words)
    assert "Contributor" not in words  # a role, not a person
    assert len(words) >= 3  # the owner's two names and the test DJ's


def test_ci_runs_the_check():
    ci = (REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "scripts/check_personal.py" in ci


# -- the rule, on synthetic repos -------------------------------------------------------------------


def _repo(tmp_path: Path, *, plugin: dict | None = None, marketplace: dict | None = None) -> Path:
    root = tmp_path / "repo"
    (root / "plugin" / ".claude-plugin").mkdir(parents=True)
    (root / ".claude-plugin").mkdir()
    plugin = plugin or {"name": "x", "author": {"name": NAME}, "description": "A tool."}
    marketplace = marketplace or {"name": "x", "owner": {"name": NAME}, "plugins": [{"name": "x"}]}
    (root / "plugin" / ".claude-plugin" / "plugin.json").write_text(json.dumps(plugin, indent=2), encoding="utf-8")
    (root / ".claude-plugin" / "marketplace.json").write_text(json.dumps(marketplace, indent=2), encoding="utf-8")
    return root


def _hits(root: Path, words: list[str]) -> list[tuple[str, int, str]]:
    """What git grep would give, read straight from the files (no git needed)."""
    out = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if any(w.casefold() in line.casefold() for w in words):
                out.append((path.relative_to(root).as_posix(), n, line))
    return out


def test_the_two_allowed_fields_pass(cp, tmp_path):
    root = _repo(tmp_path)
    words = NAME.split()
    assert cp.problems(root, words, _hits(root, words)) == []


def test_a_name_anywhere_else_fails(cp, tmp_path):
    root = _repo(tmp_path)
    (root / "src").mkdir()
    (root / "src" / "a.py").write_text("# written by ada\n", encoding="utf-8")
    words = NAME.split()
    assert cp.problems(root, words, _hits(root, words)) == ["src/a.py:1: a real person's name"]


def test_a_second_field_in_an_allowed_file_fails(cp, tmp_path):
    root = _repo(tmp_path, plugin={"name": "x", "author": {"name": NAME}, "description": f"By {NAME}."})
    words = NAME.split()
    found = cp.problems(root, words, _hits(root, words))
    assert any("also found in description" in line for line in found), found
    assert any("2 lines hold the name" in line for line in found), found


def test_the_name_under_another_key_fails(cp, tmp_path):
    root = _repo(tmp_path, marketplace={"name": "x", "owner": {"email": "x"}, "maintainer": {"name": NAME}})
    words = NAME.split()
    found = cp.problems(root, words, _hits(root, words))
    assert found and all(".claude-plugin/marketplace.json" in line for line in found)


def test_git_grep_finds_new_files_and_skips_ignored_ones(cp, tmp_path):
    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    root = _repo(tmp_path)
    subprocess.run(["git", "init", "-q", str(root)], check=True, capture_output=True, timeout=60)
    (root / ".gitignore").write_text("STATE.md\n", encoding="utf-8")
    (root / "STATE.md").write_text(f"{NAME}'s own notes\n", encoding="utf-8")
    (root / "src").mkdir()
    (root / "src" / "b.py").write_text("x = 'lovelace'\n", encoding="utf-8")
    words = NAME.split()
    hits = cp.grep(root, words)
    paths = {path for path, _n, _t in hits}
    assert "src/b.py" in paths and "STATE.md" not in paths
    assert cp.problems(root, words, hits) == ["src/b.py:1: a real person's name"]
