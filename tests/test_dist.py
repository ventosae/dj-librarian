"""dist/ in the repo: the plugin zip of the current version (the full one, with the engine inside) is
tracked, so it can be downloaded from GitHub and installed on any laptop (W-37). It must be what
`scripts/build_plugin_zip.py` makes of the code beside it: a stale zip installs old code.

The content check compares the files in the committed zip with a fresh `entries()` (names and bytes,
not the zip's own bytes, which depend on zlib). It runs on a git checkout with LF line endings
(Ubuntu and macOS in CI); a Windows checkout with autocrlf has CRLF files, so the bytes differ there
by design and the check is skipped.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import tomllib
import zipfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
DIST = REPO / "dist"
VERSION = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
ZIP = f"dj-librarian-plugin-{VERSION}.zip"
REBUILD = f"dist/{ZIP} is stale: run `uv run python scripts/build_plugin_zip.py`, then commit it"


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True, timeout=60)


def _git_checkout() -> bool:
    if shutil.which("git") is None or not (REPO / ".git").exists():
        return False
    done = _git("rev-parse", "--is-inside-work-tree")
    return done.returncode == 0 and done.stdout.strip() == "true"


GIT = pytest.mark.skipif(not _git_checkout(), reason="not a git checkout: the zip is made from tracked files")


def test_the_current_versions_zip_is_in_dist():
    assert (DIST / ZIP).is_file(), f"dist/{ZIP} is missing: run `uv run python scripts/build_plugin_zip.py`"


@GIT
def test_dist_tracks_the_plugin_zip_and_ignores_the_rest():
    assert f"dist/{ZIP}" in _git("ls-files", "--", "dist").stdout.split(), f"commit dist/{ZIP}"
    others = ["dist/notes.txt", f"dist/.{ZIP}.x1y2.tmp", f"dist/dj-librarian-plugin-{VERSION}-no-engine.zip",
              f"dist/dj-librarian-engine-{VERSION}.mcpb"]  # fmt: skip
    assert _git("check-ignore", "--no-index", *others).stdout.split() == others
    assert _git("check-ignore", "--no-index", f"dist/{ZIP}").stdout.split() == []


@GIT
@pytest.mark.skipif(b"\r\n" in (REPO / "pyproject.toml").read_bytes(),
                    reason="a CRLF checkout (Windows autocrlf): the files differ from the LF ones zipped")  # fmt: skip
def test_the_plugin_zip_in_dist_is_current():
    spec = importlib.util.spec_from_file_location("build_plugin_zip", REPO / "scripts" / "build_plugin_zip.py")
    bz = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bz)
    want = {name: src if isinstance(src, bytes) else src.read_bytes() for name, src in bz.entries().items()}
    with zipfile.ZipFile(DIST / ZIP) as zf:
        got = {name: zf.read(name) for name in zf.namelist()}
    missing, extra = sorted(want.keys() - got.keys()), sorted(got.keys() - want.keys())
    changed = sorted(name for name in want.keys() & got.keys() if got[name] != want[name])
    assert not (missing or extra or changed), f"{REBUILD} (changed {changed[:5]}, missing {missing[:5]}, extra {extra[:5]})"
