"""Build the plugin zip a DJ uploads: plugin/ and one copy of the core inside it, plugin/engine/
(D-17, D-29, Q-21).

    uv run python scripts/build_plugin_zip.py [--out DIR] [--no-engine]

Writes `<out>/dj-librarian-plugin-<version>.zip` (default `dist/`, gitignored) and prints one
JSON object: the zip, its file count and size, the version, and whether the engine is in it.

What goes in, at the zip's root: claude.ai's Upload plugin wants `.claude-plugin/plugin.json` there
and refuses a zip with the plugin under a top folder (Q-21, answered at the first upload):
- every file git tracks under `plugin/` except caches (`__pycache__/`, `*.pyc`, `.mcpb-cache/`,
  OS files) and anything a local build or an older zip layout left there (`engine/`, `vendor/`,
  `engine.mcpb`). A file under `plugin/` that git does not track (a `.env`, notes, local
  settings, ignored or not) stops the build instead of shipping: hard rules 6 and 7,
- `plugin/engine/`: the engine's source, the one copy of the core. `src/dj/**`, `pyproject.toml`,
  `uv.lock`, `.python-version`, `README.md` and `LICENSE` (the files git tracks, the same list as
  the engine bundle: scripts/build_mcpb.py `members`), plus `examples/` and
  `scripts/merge_desktop_config.py`, and `BUILD.txt` (the version and a hash of those files: the
  install command copies a new engine whenever it differs, even under the same version).
  `/dj-librarian:install` copies it to `~/dj-librarian` and runs `uv sync` there (D-29); the Door-1
  skill scripts import the core from `engine/src`.

`--no-engine`: the light zip `dj-librarian-plugin-<version>-no-engine.zip` for Door 1 only. It
keeps `engine/src` (the skills need the core) and leaves out what installs the engine:
the install and uninstall skills, and engine/'s project files, examples and script.

The skill scripts find the core in this order: an importable `dj` (the engine venv), then
`../../../../src` (a clone of the repo), then `../../../engine/src` (this zip).

The version comes from pyproject.toml and must equal plugin.json's. A zip over 15 MB is refused.
The zip is the same bytes for the same files (sorted entries, fixed time stamps). The engine
bundle (`.mcpb`) is not in the zip: it is the standalone fallback, scripts/build_mcpb.py. Nothing
is uploaded or published: the release workflow only drafts (W-32).
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import tomllib
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PLUGIN = REPO / "plugin"
ENGINE = "engine"  # plugin/engine/: the engine's source
ENGINE_EXTRA = ("examples", "scripts/merge_desktop_config.py")  # beside the bundle's files
STAMP_FILE = "BUILD.txt"  # engine/BUILD.txt: the version and a hash of the engine's files
INSTALL_ONLY = ("skills/install/", "skills/uninstall/")  # what the light zip leaves out
LOCAL = {ENGINE, "vendor", "engine.mcpb"}  # left by a local build or an older layout: never shipped
SKIP_DIRS = {"__pycache__", ".mcpb-cache"}
SKIP_FILES = {".DS_Store", "Thumbs.db", "desktop.ini"}
STAMP = (2026, 1, 1, 0, 0, 0)  # every entry's time: the same files give the same zip
MAX_BYTES = 15 * 1024 * 1024  # a zip over 15 MB is refused


def _load_mcpb():
    """scripts/build_mcpb.py, loaded from beside this file: its `members` lists the engine's files."""
    spec = importlib.util.spec_from_file_location("build_mcpb", Path(__file__).resolve().with_name("build_mcpb.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mcpb = _load_mcpb()


class BuildError(RuntimeError):
    """The zip cannot be built as it must be. Nothing was written."""


def version() -> str:
    """pyproject.toml's version; plugin.json must say the same (CLAUDE.md, Conventions)."""
    project = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    manifest = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))["version"]
    if project != manifest:
        raise BuildError(f"pyproject.toml says {project}, plugin.json says {manifest}: make them equal first.")
    return str(project)


def _shipped(rel: str) -> bool:
    """False for caches, OS files and what a local build left at the plugin's top."""
    parts = rel.split("/")
    return not (parts[0] in LOCAL or any(part in SKIP_DIRS for part in parts) or parts[-1] in SKIP_FILES
                or rel.endswith(".pyc"))  # fmt: skip


def _git_files(*args: str) -> list[str]:
    """`git ls-files -z <args>` run in plugin/: paths relative to plugin/, POSIX."""
    try:
        done = subprocess.run(["git", "-C", str(PLUGIN), "ls-files", "-z", *args, "--", "."], capture_output=True,
                              timeout=120)  # fmt: skip
    except OSError as exc:
        raise BuildError(f"git is needed to list the plugin's files: {exc}") from None
    if done.returncode != 0:
        raise BuildError("plugin/ is not in a git checkout: the zip is built from the files git tracks. "
                         + done.stderr.decode("utf-8", "replace").strip())  # fmt: skip
    return [name for name in done.stdout.decode("utf-8").split("\0") if name]


def plugin_files() -> list[Path]:
    """The plugin's own files, sorted: exactly what git tracks under plugin/ (as it is on disk),
    minus caches and local build output. A file git does not track is refused, not shipped."""
    stray = sorted(rel for rel in _git_files("--others") if _shipped(rel))
    if stray:
        raise BuildError("plugin/ holds files git does not track, which would ship in the zip: "
                         + ", ".join(stray) + ". Track them to ship them, or move them out of plugin/.")  # fmt: skip
    return [PLUGIN / rel for rel in sorted(set(_git_files("--cached")))
            if _shipped(rel) and (PLUGIN / rel).is_file() and not (PLUGIN / rel).is_symlink()]  # fmt: skip


def engine_files(*, full: bool = True) -> dict[str, Path]:
    """{path under engine/: source file}: the engine bundle's files minus its manifest (src/dj/**
    and the project files), plus examples/ and the config script. Not `full`: src/ only."""
    try:
        names = {name: path for name, path in mcpb.members(REPO).items() if name != "manifest.json"}
    except mcpb.BuildError as exc:
        raise BuildError(f"the engine: {exc}") from None
    if not full:
        return {name: path for name, path in names.items() if name.startswith("src/")}
    tracked = mcpb._git(REPO, "--cached", "--", *ENGINE_EXTRA)
    for rel in ENGINE_EXTRA:
        if not any(name == rel or name.startswith(f"{rel}/") for name in tracked):
            raise BuildError(f"{rel} is not tracked by git: the engine copy needs it.")
    for rel in tracked:
        if mcpb._shipped(rel) and (REPO / rel).is_file():
            names[rel] = REPO / rel
    return dict(sorted(names.items()))


def stamp(files: dict[str, Path], ver: str) -> bytes:
    """engine/BUILD.txt: `dj-librarian <version> <sha256 of the files, names and bytes>`."""
    digest = hashlib.sha256()
    for rel, path in sorted(files.items()):
        digest.update(rel.encode("utf-8") + b"\0" + path.read_bytes() + b"\0")
    return f"dj-librarian {ver} {digest.hexdigest()[:16]}\n".encode("utf-8")


def entries(*, engine: bool = True) -> dict[str, Path | bytes]:
    """{name in the zip: source file, or the bytes that go in}, every name at the zip's root
    (`.claude-plugin/plugin.json`, `skills/...`, `engine/...`). Not `engine`: the light zip."""
    top = ""
    names: dict[str, Path | bytes] = {}
    for path in plugin_files():  # first: a stray file refuses before anything else
        rel = path.relative_to(PLUGIN).as_posix()
        if engine or not rel.startswith(INSTALL_ONLY):
            names[f"{top}{rel}"] = path
    files = engine_files(full=engine)
    for rel, path in files.items():
        names[f"{top}{ENGINE}/{rel}"] = path
    if engine:
        names[f"{top}{ENGINE}/{STAMP_FILE}"] = stamp(files, version())
    return dict(sorted(names.items()))


def zip_name(ver: str, *, engine: bool = True) -> str:
    """dj-librarian-plugin-<version>.zip, or ...-no-engine.zip for the light zip."""
    return f"dj-librarian-plugin-{ver}.zip" if engine else f"dj-librarian-plugin-{ver}-no-engine.zip"


def build(out_dir: Path, *, engine: bool = True) -> dict[str, object]:
    """Write the zip into `out_dir` (a temp file first, then its name) and say what is in it.
    Nothing is written when the zip would be over MAX_BYTES."""
    ver = version()
    names = entries(engine=engine)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / zip_name(ver, engine=engine)
    fd, tmp = tempfile.mkstemp(dir=out_dir, prefix=f".{target.name}.", suffix=".tmp")
    os.close(fd)
    try:
        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
            for name, source in names.items():
                info = zipfile.ZipInfo(name, date_time=STAMP)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 3  # the same header on every OS
                info.external_attr = 0o100644 << 16
                zf.writestr(info, source if isinstance(source, bytes) else source.read_bytes())
        size = Path(tmp).stat().st_size
        if size > MAX_BYTES:
            raise BuildError(f"the zip would be {size / 2**20:.1f} MB, over the {MAX_BYTES / 2**20:g} MB limit: "
                             "nothing was written.")  # fmt: skip
        os.replace(tmp, target)
    finally:
        Path(tmp).unlink(missing_ok=True)
    return {
        "zip": target.as_posix() if not target.is_relative_to(REPO) else target.relative_to(REPO).as_posix(),
        "files": len(names),
        "bytes": target.stat().st_size,
        "version": ver,
        "engine": engine,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build dist/dj-librarian-plugin-<version>.zip (nothing is uploaded).")
    parser.add_argument("--out", type=Path, default=REPO / "dist", help="folder for the zip (default: dist/)")
    parser.add_argument("--no-engine", action="store_true",
                        help="the light zip ...-no-engine.zip: Door 1 only, no install command")  # fmt: skip
    args = parser.parse_args(argv)
    try:
        result = build(args.out.resolve(), engine=not args.no_engine)
    except BuildError as exc:
        print(json.dumps({"error": str(exc)}))
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
