"""One version everywhere, from pyproject.toml (W-37; CONTRIBUTING.md, "Versioning").

pyproject.toml, uv.lock, plugin.json, the marketplace entry, the engine bundle's manifest, the zip's
engine/BUILD.txt stamp, the zip names, `dj status` and the newest CHANGELOG section all say the same
version: CI fails on drift. `scripts/bump_version.py patch|minor` moves them together, in a copy here.
"""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tomllib
from datetime import date
from pathlib import Path

import pytest
import xml_fixtures as fx
from typer.testing import CliRunner

from dj import cli, safety

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
VERSION = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def bv():
    return _load("bump_version")


# -- no drift ------------------------------------------------------------------------------------------


def test_every_file_says_pyprojects_version(bv):
    found = bv.versions()
    assert set(found.values()) == {VERSION}, f"version drift: {found} (scripts/bump_version.py moves them together)"


def test_the_zip_names_and_the_build_stamp_follow_pyproject():
    bz, mcpb = _load("build_plugin_zip"), _load("build_mcpb")
    assert bz.version() == VERSION and mcpb.versions() == (VERSION, VERSION)
    assert bz.zip_name(VERSION) == f"dj-librarian-plugin-{VERSION}.zip"
    assert bz.zip_name(VERSION, engine=False) == f"dj-librarian-plugin-{VERSION}-no-engine.zip"
    assert mcpb.NAME.format(version=VERSION) == f"dj-librarian-engine-{VERSION}.mcpb"
    assert re.fullmatch(rf"dj-librarian {re.escape(VERSION)} [0-9a-f]{{16}}\n", bz.stamp({}, bz.version()).decode())


def test_dj_status_reports_the_same_version(tmp_path, monkeypatch):
    """The installed engine's own version (package metadata): a stale one means `uv sync` after a bump."""
    live = fx.write_master_files(tmp_path / "rb")
    monkeypatch.setattr(safety, "find_master_db", lambda: live)
    monkeypatch.setattr(safety, "_connect", lambda db_path, quiet=False: fx.fake_db())
    monkeypatch.setattr(cli, "links_data", lambda db, paths: [])
    done = CliRunner().invoke(cli.app, ["status", "--json"])
    assert done.exit_code == 0, done.output
    assert json.loads(done.output)["dj_librarian"] == VERSION, "run `uv sync` after a version bump"
    human = CliRunner().invoke(cli.app, ["status"]).output
    assert f"dj-librarian:  {VERSION} (pyrekordbox " in human


def test_the_newest_changelog_section_is_this_version_and_dated():
    text = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
    headings = re.findall(r"^## \[([^\]]+)\](.*)$", text, re.MULTILINE)
    assert headings[0][0] == "Unreleased"
    version, rest = headings[1]
    assert version == VERSION and re.fullmatch(r" - \d{4}-\d{2}-\d{2}", rest), headings[1]


# -- scripts/bump_version.py, in a copy ----------------------------------------------------------------


CHANGES = "# Changelog\n\nIntro.\n\n## [Unreleased]\n\n### Added\n- A new thing.\n\n## [{old}] - 2026-10-25\n\n- Old.\n"


@pytest.fixture
def repo(tmp_path, bv):
    root = tmp_path / "repo"
    for rel in (bv.PYPROJECT, bv.UV_LOCK, bv.PLUGIN_JSON, bv.MARKETPLACE, bv.MCPB):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / rel, root / rel)
    (root / bv.CHANGELOG).write_text(CHANGES.format(old=VERSION), encoding="utf-8", newline="\n")
    return root


def _snap(root: Path, bv) -> dict[str, list[str]]:
    rels = (bv.PYPROJECT, bv.UV_LOCK, bv.PLUGIN_JSON, bv.MARKETPLACE, bv.MCPB, bv.CHANGELOG)
    return {rel.as_posix(): (root / rel).read_text(encoding="utf-8").splitlines() for rel in rels}


@pytest.mark.parametrize("old, part, new", [("0.1.0", "patch", "0.1.1"), ("0.1.1", "minor", "0.2.0"),
                                            ("1.9.9", "patch", "1.9.10"), ("0.9.3", "minor", "0.10.0")])  # fmt: skip
def test_next_version(bv, old, part, new):
    assert bv.next_version(old, part) == new


@pytest.mark.parametrize("old, part", [("0.1", "patch"), ("v0.1.0", "patch"), ("0.1.0", "major")])
def test_next_version_refuses(bv, old, part):
    with pytest.raises(bv.BumpError):
        bv.next_version(old, part)


def test_a_patch_bump_moves_every_file_and_dates_the_changelog(repo, bv):
    new = bv.next_version(VERSION, "patch")
    before = _snap(repo, bv)
    out = bv.bump("patch", root=repo, today=date(2026, 11, 2))
    assert out == {"old": VERSION, "new": new, "zip": f"dj-librarian-plugin-{new}.zip",
                   "files": ["pyproject.toml", "uv.lock", "plugin/.claude-plugin/plugin.json",
                             ".claude-plugin/marketplace.json", "mcpb/manifest.json", "CHANGELOG.md"]}  # fmt: skip
    assert set(bv.versions(repo).values()) == {new}
    after = _snap(repo, bv)
    for rel in ("pyproject.toml", "uv.lock", "plugin/.claude-plugin/plugin.json", ".claude-plugin/marketplace.json",
                "mcpb/manifest.json"):  # one line each, the rest of the file as it was
        changed = [(a, b) for a, b in zip(before[rel], after[rel]) if a != b]
        assert len(before[rel]) == len(after[rel]) and len(changed) == 1, rel
        assert changed[0][1] == changed[0][0].replace(VERSION, new), rel
    assert "manifest_version" in "\n".join(after["mcpb/manifest.json"])  # "manifest_version" untouched
    text = (repo / "CHANGELOG.md").read_text(encoding="utf-8")
    assert text == (f"# Changelog\n\nIntro.\n\n## [Unreleased]\n\n## [{new}] - 2026-11-02\n\n### Added\n- A new thing.\n\n"
                    f"## [{VERSION}] - 2026-10-25\n\n- Old.\n")  # fmt: skip


def test_a_minor_bump(repo, bv):
    assert bv.bump("minor", root=repo, today=date(2026, 11, 2))["new"] == bv.next_version(VERSION, "minor")


def _drift(root, bv):
    path = root / bv.MCPB
    path.write_text(path.read_text(encoding="utf-8").replace(f'"version": "{VERSION}"', '"version": "9.9.9"'),
                    encoding="utf-8")  # fmt: skip


def _no_entries(root, bv):
    (root / bv.CHANGELOG).write_text(CHANGES.format(old=VERSION).replace("- A new thing.\n", ""), encoding="utf-8")


def _section_exists(root, bv):
    (root / bv.CHANGELOG).write_text(CHANGES.format(old=VERSION) + f"\n## [{bv.next_version(VERSION, 'patch')}]\n",
                                     encoding="utf-8")  # fmt: skip


@pytest.mark.parametrize("break_it, message", [(_drift, "the versions disagree"), (_no_entries, "holds no entry"),
                                               (_section_exists, "already has a")])  # fmt: skip
def test_a_refused_bump_changes_nothing(repo, bv, break_it, message):
    break_it(repo, bv)
    before = _snap(repo, bv)
    with pytest.raises(bv.BumpError, match=message):
        bv.bump("patch", root=repo)
    assert _snap(repo, bv) == before


def test_the_script_prints_one_json_line_and_exits_1_on_a_refusal(repo):
    script = SCRIPTS / "bump_version.py"
    done = subprocess.run([sys.executable, "-I", str(script), "patch", "--root", str(repo), "--today", "2026-11-02"],
                          capture_output=True, text=True, encoding="utf-8", timeout=60)  # fmt: skip
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout)["new"] == _load("bump_version").next_version(VERSION, "patch")
    again = subprocess.run([sys.executable, "-I", str(script), "patch", "--root", str(repo)], capture_output=True,
                           text=True, encoding="utf-8", timeout=60)  # fmt: skip
    assert again.returncode == 1 and again.stderr.startswith("bump_version: ") and again.stdout == ""
