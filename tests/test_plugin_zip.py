"""scripts/build_plugin_zip.py: the plugin zip with the Door-1 core vendored inside (D-22, Q-21).

The zip holds plugin/ and plugin/vendor/dj/ (the core the Door-1 test guards, plus the identity,
sleeve, design and report-chart modules and archetypes.yaml), never an engine module or a test.
Unzipped where there is no src/ and `dj` cannot be imported, the skill scripts find the core in
vendor/ and run the whole first-contact chain to the report. Nothing is uploaded.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

import pytest
import xml_fixtures as fx
import yaml

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "build_plugin_zip.py"
DAY = "2026-10-20"
ENGINE = ("dj/cli.py", "dj/mcp_server.py", "dj/readers/db.py", "dj/tree.py", "dj/library.py", "dj/spotify.py",
          "dj/intake.py", "dj/match.py", "dj/push.py", "dj/playlist_copy.py", "dj/analyze.py")  # fmt: skip
W30B_EXTRA = ("dj/analysis/identity.py", "dj/sleeve.py", "dj/design.py", "dj/report_charts.py",
              "dj/analysis/archetypes.yaml")  # fmt: skip


@pytest.fixture(scope="module")
def bz():
    spec = importlib.util.spec_from_file_location("build_plugin_zip", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _git_checkout() -> bool:
    if shutil.which("git") is None or not (REPO / ".git").exists():
        return False
    done = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--is-inside-work-tree"], capture_output=True,
                          text=True, timeout=60)  # fmt: skip
    return done.returncode == 0 and done.stdout.strip() == "true"


@pytest.fixture(scope="module")
def built(bz, tmp_path_factory):
    if not _git_checkout():
        pytest.skip("not a git checkout: the zip is built from the files git tracks")
    out = tmp_path_factory.mktemp("dist")
    result = bz.build(out)
    return result, out / f"dj-librarian-plugin-{result['version']}.zip"


def _version() -> str:
    return tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]


def _names(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as zf:
        return zf.namelist()


def test_the_zip_is_named_for_the_version_in_pyproject_and_plugin_json(built):
    result, path = built
    manifest = json.loads((REPO / "plugin" / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert result["version"] == _version() == manifest["version"]
    assert path.is_file() and path.name == f"dj-librarian-plugin-{_version()}.zip"
    assert result["files"] == len(_names(path)) and result["bytes"] == path.stat().st_size


def test_the_zip_holds_the_plugin_and_the_door1_core_only(built, bz):
    _result, path = built
    names = _names(path)
    assert all(name.startswith("plugin/") for name in names)
    plugin = {f"plugin/{p.relative_to(REPO / 'plugin').as_posix()}" for p in bz.plugin_files()}
    assert plugin <= set(names) and "plugin/.claude-plugin/plugin.json" in plugin and "plugin/.mcp.json" in plugin
    vendored = {name.removeprefix("plugin/vendor/") for name in names if name.startswith("plugin/vendor/")}
    assert set(names) == plugin | {f"plugin/vendor/{v}" for v in vendored}
    for module in bz.door1_modules():  # the set tests/test_door1_imports.py guards
        stem = module.replace(".", "/")
        assert f"{stem}.py" in vendored or f"{stem}/__init__.py" in vendored, module
    assert set(W30B_EXTRA) <= vendored  # W-30b: identity, sleeve, design, report charts, archetypes
    assert {"dj/__init__.py", "dj/analysis/__init__.py", "dj/readers/__init__.py", "dj/writers/__init__.py"} <= vendored
    assert not set(ENGINE) & vendored, set(ENGINE) & vendored
    assert not any("test" in Path(v).name or "__pycache__" in v or v.endswith(".pyc") for v in vendored)
    for v in vendored:  # byte for byte what src/ holds
        with zipfile.ZipFile(path) as zf:
            assert zf.read(f"plugin/vendor/{v}") == (REPO / "src" / v).read_bytes(), v


def test_the_vendored_modules_import_without_the_engine_packages(bz):
    found = bz.core_modules(bz.door1_modules())
    assert "dj.readers.db" not in found and "dj.cli" not in found and "dj.mcp_server" not in found
    assert all(f.is_relative_to((REPO / "src" / "dj").resolve()) for f in found.values())


def test_the_same_files_give_the_same_zip(bz, built, tmp_path):
    _result, first = built
    again = bz.build(tmp_path)
    assert (tmp_path / first.name).read_bytes() == first.read_bytes()
    assert again["files"] == _result["files"]
    assert [p.name for p in tmp_path.iterdir()] == [first.name]  # its temp file is gone


def test_flat_puts_the_plugin_at_the_zip_root(bz, tmp_path):
    if not _git_checkout():
        pytest.skip("not a git checkout: the zip is built from the files git tracks")
    bz.build(tmp_path, flat=True)
    names = _names(tmp_path / f"dj-librarian-plugin-{_version()}.zip")
    assert ".claude-plugin/plugin.json" in names and "vendor/dj/libfolder.py" in names
    assert not any(name.startswith("plugin/") for name in names)


def test_build_refuses_when_plugin_json_and_pyproject_disagree(bz, tmp_path, monkeypatch):
    fake = tmp_path / "plugin"
    (fake / ".claude-plugin").mkdir(parents=True)
    (fake / ".claude-plugin" / "plugin.json").write_text('{"version": "9.9.9"}', encoding="utf-8")
    monkeypatch.setattr(bz, "PLUGIN", fake)
    with pytest.raises(bz.BuildError, match="9.9.9"):
        bz.build(tmp_path / "out")
    assert not (tmp_path / "out").exists()


def _fake_plugin_repo(tmp_path: Path) -> Path:
    """A git checkout holding a small tracked plugin/, a .gitignore that ignores `.env`, and the
    caches a local run leaves (never shipped, never a reason to refuse)."""
    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True, timeout=60)
    (repo / ".gitignore").write_text(".env\n__pycache__/\n/plugin/vendor/\n", encoding="utf-8")
    plugin = repo / "plugin"
    manifest = json.dumps({"name": "dj-librarian", "version": _version()}) + "\n"
    for rel, text in ((".claude-plugin/plugin.json", manifest), ("skills/dj-start/SKILL.md", "# start\n"),
                      ("skills/dj-start/scripts/start.py", "print(1)\n")):  # fmt: skip
        (plugin / rel).parent.mkdir(parents=True, exist_ok=True)
        (plugin / rel).write_text(text, encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True, capture_output=True, timeout=60)
    for rel in ("skills/dj-start/scripts/__pycache__/start.cpython-313.pyc", "vendor/dj/libfolder.py", ".DS_Store"):
        (plugin / rel).parent.mkdir(parents=True, exist_ok=True)
        (plugin / rel).write_bytes(b"cache")
    return plugin


def test_plugin_files_are_what_git_tracks(bz, tmp_path, monkeypatch):
    plugin = _fake_plugin_repo(tmp_path)
    monkeypatch.setattr(bz, "PLUGIN", plugin)
    assert [p.relative_to(plugin).as_posix() for p in bz.plugin_files()] == [
        ".claude-plugin/plugin.json", "skills/dj-start/SKILL.md", "skills/dj-start/scripts/start.py"]  # fmt: skip


def test_an_untracked_file_in_plugin_stops_the_build_instead_of_shipping(bz, tmp_path, monkeypatch):
    """A local `.env` (gitignored) or a notes file (untracked) under plugin/ never goes into the
    zip a DJ uploads (hard rules 6 and 7): the build refuses and names them."""
    plugin = _fake_plugin_repo(tmp_path)
    (plugin / ".env").write_text("PLACEHOLDER=1\n", encoding="utf-8")
    (plugin / "skills" / "dj-start" / "notes.local.md").write_text("notes\n", encoding="utf-8")
    monkeypatch.setattr(bz, "PLUGIN", plugin)
    with pytest.raises(bz.BuildError) as refused:
        bz.plugin_files()
    message = str(refused.value)
    assert ".env" in message and "skills/dj-start/notes.local.md" in message
    assert "__pycache__" not in message and "vendor/" not in message and ".DS_Store" not in message
    with pytest.raises(bz.BuildError, match="notes.local.md"):
        bz.build(tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_plugin_files_refuse_outside_a_git_checkout(bz, tmp_path, monkeypatch):
    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    plugin = tmp_path / "plugin"
    (plugin / ".claude-plugin").mkdir(parents=True)
    monkeypatch.setattr(bz, "PLUGIN", plugin)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))  # never find a repo above tmp
    with pytest.raises(bz.BuildError, match="git checkout"):
        bz.plugin_files()


def test_door1_modules_is_read_from_the_test_file(bz, tmp_path):
    from test_door1_imports import DOOR1_MODULES

    assert bz.door1_modules() == DOOR1_MODULES
    (tmp_path / "t.py").write_text("X = 1\n", encoding="utf-8")
    with pytest.raises(bz.BuildError, match="DOOR1_MODULES"):
        bz.door1_modules(tmp_path / "t.py")


def test_every_skill_script_looks_for_the_core_in_the_same_order():
    """An importable dj (engine venv or PyPI), then ../../../../src (a clone), then ../../../vendor
    (the zip): the same block in every script, so none is left on the old clone-only lookup."""
    scripts = sorted((REPO / "plugin" / "skills").glob("*/scripts/*.py"))
    assert len(scripts) >= 9
    blocks = set()
    for script in scripts:
        text = script.read_text(encoding="utf-8")
        start = text.index("try:  # the dj core")
        blocks.add(text[start : text.index("break\n", start)])
    (block,) = blocks
    assert block.index("import dj") < block.index("../../../../src") < block.index("../../../vendor")
    for script in scripts:  # the paths, from the script's own folder, land on src/ and plugin/vendor
        here = script.resolve().parent
        assert (here / "../../../../src").resolve() == (REPO / "src").resolve()
        assert (here / "../../../vendor").resolve() == (REPO / "plugin" / "vendor").resolve()


def test_dist_is_gitignored():
    lines = (REPO / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "dist/" in lines


# -- the zip, unzipped where there is no clone and no installed dj ---------------------------------


def _run(script: Path, *args: str, cwd: Path, env: dict) -> dict:
    done = subprocess.run([sys.executable, "-S", str(script), *args], cwd=cwd, env=env, capture_output=True,
                          text=True, encoding="utf-8", timeout=180)  # fmt: skip
    assert "Traceback" not in done.stderr, (script.name, done.stderr)
    lines = done.stdout.splitlines()
    assert len(lines) >= 1, (script.name, done.stdout, done.stderr)
    out = json.loads(done.stdout)
    assert done.returncode == 0, (script.name, out, done.stderr)
    return out


def test_unzipped_without_src_the_scripts_run_the_chain_from_vendor(built, tmp_path):
    """dj-start find-xml and init, profile, structure, taste, identity and report, all from the
    unzipped plugin, with a Python that cannot import dj (no src/, -S skips the editable .pth)."""
    site = Path(yaml.__file__).resolve().parents[1]
    if (site / "dj").exists():
        pytest.skip("dj is installed as a package here; the vendored branch is not reachable")
    _result, path = built
    unzipped = tmp_path / "upload"
    with zipfile.ZipFile(path) as zf:
        zf.extractall(unzipped)
    skills = unzipped / "plugin" / "skills"
    assert not list(tmp_path.rglob("src"))  # no clone anywhere: only vendor/ can serve the core
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["PYTHONPATH"] = str(site)  # PyYAML, but no dj: the .pth is not read under -S
    env["PYTHONUTF8"] = "1"
    probe = subprocess.run([sys.executable, "-S", "-c", "import dj"], cwd=tmp_path, env=env, capture_output=True,
                           text=True, timeout=120)  # fmt: skip
    assert probe.returncode != 0, "dj is importable without the vendored core"

    library = tmp_path / "dj-library"
    library.mkdir()
    fx.write_xml(library / "collection.xml")
    lib = ["--library", str(library)]
    found = _run(skills / "dj-start" / "scripts" / "start.py", "find-xml", *lib, cwd=tmp_path, env=env)
    assert found["found"]
    init = _run(skills / "dj-start" / "scripts" / "start.py", "init", *lib, "--device", "mac", "--today", DAY,
                cwd=tmp_path, env=env)  # fmt: skip
    assert init["counts"] == fx.EXPECTED_COUNTS
    for skill, script in (("dj-profile", "profile.py"), ("dj-structure", "structure.py"), ("dj-taste", "taste.py")):
        _run(skills / skill / "scripts" / script, *lib, "--today", DAY, cwd=tmp_path, env=env)
    identity = _run(skills / "dj-identity" / "scripts" / "identity.py", *lib, "--today", DAY, cwd=tmp_path, env=env)
    assert identity["written"]
    report = _run(skills / "dj-report" / "scripts" / "report.py", *lib, "--today", DAY, cwd=tmp_path, env=env)
    html = library / report["report"]
    assert html.is_file() and html.name == f"{DAY}-library.html"
    assert "<html" in html.read_text(encoding="utf-8").lower()
    assert not list(library.rglob("*.tmp"))
