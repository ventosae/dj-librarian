"""scripts/build_plugin_zip.py: the one zip a DJ uploads.

The plugin at the zip's root (`.claude-plugin/plugin.json` there) plus engine/: the tracked
src/dj/**, the project files, examples/ and the two install scripts, and engine/BUILD.txt. No skill
scripts, no vendored core, no bundle. A zip over 15 MB is refused. Nothing is uploaded.
"""

from __future__ import annotations

import importlib.util
import re
import shutil
import subprocess
import tomllib
import zipfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "build_plugin_zip.py"
VERSION = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, timeout=60)


def _git_checkout() -> bool:
    if shutil.which("git") is None or not (REPO / ".git").exists():
        return False
    done = _git("rev-parse", "--is-inside-work-tree")
    return done.returncode == 0 and done.stdout.strip() == b"true"


pytestmark = pytest.mark.skipif(not _git_checkout(), reason="not a git checkout: the zip is built from tracked files")


@pytest.fixture(scope="module")
def bz():
    spec = importlib.util.spec_from_file_location("build_plugin_zip", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def built(bz, tmp_path_factory):
    out = tmp_path_factory.mktemp("dist")
    return bz.build(out), out / f"dj-librarian-plugin-{VERSION}.zip"


def _tracked(*paths: str) -> set[str]:
    names = _git("ls-files", "-z", "--", *paths).stdout.decode("utf-8").split("\0")
    return {n for n in names if n and (REPO / n).is_file() and "__pycache__" not in n and not n.endswith(".pyc")}


def test_the_zip_holds_the_plugin_at_its_root_and_the_engine(built):
    result, path = built
    assert path.is_file() and result["version"] == VERSION and result["bytes"] == path.stat().st_size
    with zipfile.ZipFile(path) as zf:
        names = set(zf.namelist())
        stamp = zf.read("engine/BUILD.txt").decode()
        assert zf.read("engine/pyproject.toml") == (REPO / "pyproject.toml").read_bytes()
    assert result["files"] == len(names)
    plugin = {n.removeprefix("plugin/") for n in _tracked("plugin")}
    engine = {f"engine/{n}" for n in _tracked("src/dj", "examples", "scripts/merge_desktop_config.py",
                                              "scripts/library_init.py", "pyproject.toml", "uv.lock",
                                              ".python-version", "README.md", "LICENSE")}  # fmt: skip
    assert names == plugin | engine | {"engine/BUILD.txt"}
    assert ".claude-plugin/plugin.json" in names and "skills/install/SKILL.md" in names
    assert {"engine/src/dj/mcp_server.py", "engine/uv.lock", "engine/scripts/merge_desktop_config.py"} <= names
    assert re.fullmatch(rf"dj-librarian {re.escape(VERSION)} [0-9a-f]{{16}}\n", stamp)


def test_the_zip_holds_no_skill_scripts_no_vendored_core_and_no_bundle(built):
    _result, path = built
    for name in zipfile.ZipFile(path).namelist():
        parts = name.split("/")
        assert parts[0] not in ("plugin", "vendor", "mcpb", "tests", "docs"), name
        assert not (parts[0] == "skills" and "scripts" in parts), name
        assert not name.endswith((".mcpb", ".pyc")) and ".mcp.json" not in parts, name
        assert not name.startswith(("engine/tests/", "engine/docs/", "engine/mcpb/")), name


def test_a_zip_over_the_limit_is_refused_and_not_written(bz, tmp_path, monkeypatch):
    assert bz.MAX_BYTES == 15 * 1024 * 1024
    monkeypatch.setattr(bz, "MAX_BYTES", 10_000)
    with pytest.raises(bz.BuildError, match="over the"):
        bz.build(tmp_path)
    assert list(tmp_path.iterdir()) == []  # neither the zip nor its temp file
