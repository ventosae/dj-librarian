"""scripts/build_plugin_zip.py: the plugin zip with one copy of the core inside, plugin/engine/
(D-29, Q-21).

The zip holds the plugin at its root (with the install and uninstall commands) and engine/: the tracked
src/dj/**, the project files, examples/ and the config script, byte for byte, never a test, a doc,
vendor/ or the engine bundle. `--no-engine` gives the light zip: engine/src for Door 1, no install
pieces. A zip over 15 MB is refused. Unzipped where there is no clone and `dj` cannot be imported,
the skill scripts find the core in engine/src and run the whole first-contact chain to the report.
Nothing is uploaded.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
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


@pytest.fixture(scope="module")
def light(bz, tmp_path_factory):
    if not _git_checkout():
        pytest.skip("not a git checkout: the zip is built from the files git tracks")
    out = tmp_path_factory.mktemp("dist-light")
    result = bz.build(out, engine=False)
    return result, out / f"dj-librarian-plugin-{result['version']}-no-engine.zip"


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


def _engine_rel() -> set[str]:
    """What plugin/engine/ must hold: the tracked src/dj/**, the project files, examples/ and the
    config script (D-29)."""
    done = subprocess.run(["git", "-C", str(REPO), "ls-files", "-z", "--", "src/dj", "examples",
                           "scripts/merge_desktop_config.py", "scripts/library_init.py"], capture_output=True,
                          timeout=60)  # fmt: skip
    tracked = {n for n in done.stdout.decode("utf-8").split("\0") if n and (REPO / n).is_file()}
    tracked = {n for n in tracked if "__pycache__" not in n and not n.endswith(".pyc")}
    return tracked | {"pyproject.toml", "uv.lock", ".python-version", "README.md", "LICENSE"}


def test_the_zip_holds_the_plugin_and_one_copy_of_the_core(built, bz):
    _result, path = built
    names = set(_names(path))
    assert ".claude-plugin/plugin.json" in names  # at the root: Upload plugin wants it there (Q-21)
    assert not any(name.startswith("plugin/") for name in names)
    plugin = {p.relative_to(REPO / "plugin").as_posix() for p in bz.plugin_files()}
    engine = {f"engine/{rel}" for rel in _engine_rel()}
    assert names == plugin | engine | {"engine/BUILD.txt"}
    assert {"skills/install/SKILL.md", "skills/uninstall/SKILL.md", "engine/src/dj/installer.py",
            "engine/scripts/merge_desktop_config.py", "engine/uv.lock"} <= names  # fmt: skip
    for gone in (".mcp.json", "engine.mcpb"):  # D-29: no bundle inside, no vendor/
        assert gone not in names
    assert not any(n.startswith(("vendor/", "engine/tests/", "engine/docs/")) for n in names)
    with zipfile.ZipFile(path) as zf:
        for rel in _engine_rel():  # byte for byte what the repo holds
            assert zf.read(f"engine/{rel}") == (REPO / rel).read_bytes(), rel
        assert "mcpServers" not in json.loads(zf.read(".claude-plugin/plugin.json"))
        assert re.fullmatch(rf"dj-librarian {_version()} [0-9a-f]{{16}}\n", zf.read("engine/BUILD.txt").decode())


def test_the_same_files_give_the_same_zip(bz, built, tmp_path):
    _result, first = built
    again = bz.build(tmp_path)
    assert (tmp_path / first.name).read_bytes() == first.read_bytes()
    assert again["files"] == _result["files"]
    assert [p.name for p in tmp_path.iterdir()] == [first.name]  # its temp file is gone


def test_the_plugin_sits_at_the_zip_root():
    """claude.ai's Upload plugin refused a zip with a top `plugin/` folder: it wants
    `.claude-plugin/plugin.json` at the root (Q-21)."""
    assert "--flat" not in SCRIPT.read_text(encoding="utf-8")


def test_no_engine_gives_the_light_zip_for_door1(built, light):
    _full_result, full = built
    result, path = light
    assert path.is_file() and path.name == f"dj-librarian-plugin-{_version()}-no-engine.zip"
    assert result["engine"] is False
    names, everything = set(_names(path)), set(_names(full))
    assert names < everything and result["files"] == len(names)
    for name in everything - names:  # only what installs the engine is left out
        assert name.startswith(("skills/install/", "skills/uninstall/")) or (name.startswith("engine/") and not name.startswith("engine/src/")), name
    assert {n for n in everything if n.startswith("engine/src/")} <= names  # Door 1 needs the core


def test_main_no_engine_prints_the_light_zip(bz, tmp_path, capsys):
    if not _git_checkout():
        pytest.skip("not a git checkout: the zip is built from the files git tracks")
    assert bz.main(["--out", str(tmp_path), "--no-engine"]) == 0
    assert json.loads(capsys.readouterr().out)["engine"] is False
    assert [p.name for p in tmp_path.iterdir()] == [f"dj-librarian-plugin-{_version()}-no-engine.zip"]


def test_a_zip_over_the_limit_is_refused_and_not_written(bz, tmp_path, monkeypatch):
    if not _git_checkout():
        pytest.skip("not a git checkout: the zip is built from the files git tracks")
    assert bz.MAX_BYTES == 15 * 1024 * 1024
    monkeypatch.setattr(bz, "MAX_BYTES", 10_000)
    with pytest.raises(bz.BuildError, match="over the"):
        bz.build(tmp_path)
    assert list(tmp_path.iterdir()) == []  # neither the zip nor its temp file


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
    caches a local run leaves (never shipped, never a reason to refuse): among them a local
    engine.mcpb (scripts/build_mcpb.py --plugin) and the .mcpb-cache/ Claude Code extracts it to."""
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
    for rel in ("skills/dj-start/scripts/__pycache__/start.cpython-313.pyc", "vendor/dj/libfolder.py", ".DS_Store",
                "engine.mcpb", ".mcpb-cache/dj-librarian/manifest.json", "engine/src/dj/x.py"):  # fmt: skip
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
    assert "engine.mcpb" not in message and ".mcpb-cache" not in message and "engine/" not in message
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


def test_every_skill_script_looks_for_the_core_in_the_same_order():
    """An importable dj (the engine venv), then ../../../../src (a clone), then ../../../engine/src
    (the zip, D-29): the same block in every script."""
    scripts = sorted((REPO / "plugin" / "skills").glob("*/scripts/*.py"))
    assert len(scripts) >= 9
    blocks = set()
    for script in scripts:
        text = script.read_text(encoding="utf-8")
        start = text.index("try:  # the dj core")
        blocks.add(text[start : text.index("break\n", start)])
    (block,) = blocks
    assert block.index("import dj") < block.index("../../../../src") < block.index("../../../engine/src")
    assert "vendor" not in block
    for script in scripts:  # the paths, from the script's own folder, land on src/ and plugin/engine/src
        here = script.resolve().parent
        assert (here / "../../../../src").resolve() == (REPO / "src").resolve()
        assert (here / "../../../engine/src").resolve() == (REPO / "plugin" / "engine" / "src").resolve()


def test_dist_keeps_the_plugin_zip_only():
    """dist/ holds the tracked plugin zip (tests/test_dist.py); the light zip and the rest are ignored."""
    lines = (REPO / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "dist/*" in lines and "!dist/dj-librarian-plugin-*.zip" in lines and "dist/" not in lines
    assert lines.index("dist/dj-librarian-plugin-*-no-engine.zip") > lines.index("!dist/dj-librarian-plugin-*.zip")


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


def test_unzipped_without_a_clone_the_scripts_run_the_chain_from_engine_src(built, tmp_path):
    """dj-start find-xml and init, profile, structure, taste, identity and report, all from the
    unzipped plugin, with a Python that cannot import dj (no src/, -S skips the editable .pth)."""
    site = Path(yaml.__file__).resolve().parents[1]
    if (site / "dj").exists():
        pytest.skip("dj is installed as a package here; the engine/src branch is not reachable")
    _result, path = built
    unzipped = tmp_path / "upload"
    with zipfile.ZipFile(path) as zf:
        zf.extractall(unzipped)
    skills = unzipped / "skills"
    assert not (tmp_path / "src").exists()  # no clone: only plugin/engine/src can serve the core
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["PYTHONPATH"] = str(site)  # PyYAML, but no dj: the .pth is not read under -S
    env["PYTHONUTF8"] = "1"
    probe = subprocess.run([sys.executable, "-S", "-c", "import dj"], cwd=tmp_path, env=env, capture_output=True,
                           text=True, timeout=120)  # fmt: skip
    assert probe.returncode != 0, "dj is importable without the zip's core"

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
