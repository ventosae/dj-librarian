"""Build the plugin zip a DJ uploads: the plugin at the zip's root plus engine/, the engine's source.

    uv run python scripts/build_plugin_zip.py [--out DIR]

Writes `<out>/dj-librarian-plugin-<version>.zip` (default `dist/`, where git tracks it so it can be
downloaded from GitHub: tests/test_dist.py) and prints one JSON object: the zip, its file count and
size, and the version. Standard library only.

What goes in, and nothing else:
- every file git tracks under `plugin/`, at the zip's root: claude.ai's Upload plugin wants
  `.claude-plugin/plugin.json` there and refuses a zip with the plugin under a top folder,
- `engine/`: the files git tracks under `src/dj/`, `pyproject.toml`, `uv.lock`, `.python-version`,
  `README.md`, `LICENSE`, `examples/`, `scripts/merge_desktop_config.py` and
  `scripts/library_init.py`, plus `engine/BUILD.txt` (the version and a hash of those files: the
  install command copies a new engine whenever it differs, even under the same version).
  `/dj-librarian:install` copies engine/ to `~/dj-librarian` and runs `uv sync` there.

Caches and OS files never go in. A file under `plugin/` or `src/dj/` that git does not track (a
`.env`, notes, local settings, ignored or not) stops the build instead of shipping: the zip is the
code the tests ran on (hard rules 6 and 7). Track it (`git add`) or move it.

The version comes from pyproject.toml and must equal plugin.json's. A zip over 15 MB is refused.
The zip is the same bytes for the same files (sorted entries, fixed time stamps). The files are read
from the working copy, so a checkout with CRLF line endings (git's core.autocrlf on Windows) zips
other bytes than an LF checkout: build the zip that is committed to dist/ from an LF checkout.
Nothing is uploaded or published: the release workflow only drafts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import tomllib
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PLUGIN = "plugin"
PACKAGE = "src/dj"
ENGINE = "engine"  # the zip's engine/ folder: the engine's source
# The engine's files besides the package. pyproject.toml names README.md and LICENSE (readme,
# license-files), so `uv sync` needs both; the two scripts are what the install command runs.
ENGINE_FILES = ("pyproject.toml", "uv.lock", ".python-version", "README.md", "LICENSE", "examples",
                "scripts/merge_desktop_config.py", "scripts/library_init.py")  # fmt: skip
STAMP_FILE = "BUILD.txt"  # engine/BUILD.txt: the version and a hash of the engine's files
SKIP_DIRS = {"__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache"}
SKIP_FILES = {".DS_Store", "Thumbs.db", "desktop.ini"}
SKIP_SUFFIXES = (".pyc", ".pyo")
STAMP = (2026, 1, 1, 0, 0, 0)  # every entry's time: the same files give the same zip
MAX_BYTES = 15 * 1024 * 1024  # a zip over 15 MB is refused


class BuildError(RuntimeError):
    """The zip cannot be built as it must be. Nothing was written."""


def version() -> str:
    """pyproject.toml's version; plugin.json must say the same (CLAUDE.md, Conventions)."""
    project = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    manifest = json.loads((REPO / PLUGIN / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))["version"]
    if project != manifest:
        raise BuildError(f"pyproject.toml says {project}, plugin.json says {manifest}: make them equal first.")
    return str(project)


def _shipped(rel: str) -> bool:
    """False for caches and OS files, which never go in."""
    parts = rel.split("/")
    return not (any(part in SKIP_DIRS for part in parts) or parts[-1] in SKIP_FILES or rel.endswith(SKIP_SUFFIXES))


def _git(*args: str) -> list[str]:
    """`git ls-files -z <args>` at the repo root: repo-relative POSIX paths, caches left out."""
    try:
        done = subprocess.run(["git", "-C", str(REPO), "ls-files", "-z", *args], capture_output=True, timeout=120)
    except OSError as exc:
        raise BuildError(f"git is needed to list the zip's files: {exc}") from None
    if done.returncode != 0:
        raise BuildError("the repo is not a git checkout: the zip is built from the files git tracks. "
                         + done.stderr.decode("utf-8", "replace").strip())  # fmt: skip
    return sorted(name for name in done.stdout.decode("utf-8").split("\0") if name and _shipped(name))


def _tracked(*paths: str) -> dict[str, Path]:
    """{repo-relative path: file} for what git tracks under `paths`, as it is on disk. A path git
    tracks nothing under is refused."""
    names = _git("--cached", "--", *paths)
    for path in paths:
        if not any(name == path or name.startswith(f"{path}/") for name in names):
            raise BuildError(f"{path} is not tracked by git: the zip needs it.")
    return {name: REPO / name for name in names if (REPO / name).is_file() and not (REPO / name).is_symlink()}


def plugin_files() -> dict[str, Path]:
    """{path under plugin/: file}: exactly what git tracks there."""
    return {name.removeprefix(f"{PLUGIN}/"): path for name, path in _tracked(PLUGIN).items()}


def engine_files() -> dict[str, Path]:
    """{path under engine/: file}: the tracked src/dj/** and ENGINE_FILES."""
    return _tracked(PACKAGE, *ENGINE_FILES)


def stamp(files: dict[str, Path], ver: str) -> bytes:
    """engine/BUILD.txt: `dj-librarian <version> <sha256 of the files, names and bytes>`."""
    digest = hashlib.sha256()
    for rel, path in sorted(files.items()):
        digest.update(rel.encode("utf-8") + b"\0" + path.read_bytes() + b"\0")
    return f"dj-librarian {ver} {digest.hexdigest()[:16]}\n".encode("utf-8")


def entries() -> dict[str, Path | bytes]:
    """{name in the zip: source file, or the bytes that go in}: the plugin at the zip's root
    (`.claude-plugin/plugin.json`, `skills/...`) and `engine/...`."""
    stray = _git("--others", "--", PLUGIN, PACKAGE)  # first: a stray file refuses before anything else
    if stray:
        raise BuildError(f"{PLUGIN}/ and {PACKAGE}/ hold files git does not track, which would ship in the zip: "
                         + ", ".join(stray) + ". Track them (git add) to ship them, or move them out.")  # fmt: skip
    names: dict[str, Path | bytes] = dict(plugin_files())
    taken = sorted(name for name in names if name.split("/")[0] == ENGINE)
    if taken:
        raise BuildError(f"{PLUGIN}/{ENGINE}/ is the zip's engine folder: move " + ", ".join(taken) + ".")
    files = engine_files()
    names.update({f"{ENGINE}/{rel}": path for rel, path in files.items()})
    names[f"{ENGINE}/{STAMP_FILE}"] = stamp(files, version())
    return dict(sorted(names.items()))


def zip_name(ver: str) -> str:
    return f"dj-librarian-plugin-{ver}.zip"


def build(out_dir: Path) -> dict[str, object]:
    """Write the zip into `out_dir` (a temp file first, then its name) and say what is in it.
    Nothing is written when the zip would be over MAX_BYTES."""
    ver = version()
    names = entries()
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / zip_name(ver)
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
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build dist/dj-librarian-plugin-<version>.zip (nothing is uploaded).")
    parser.add_argument("--out", type=Path, default=REPO / "dist", help="folder for the zip (default: dist/)")
    args = parser.parse_args(argv)
    try:
        result = build(args.out.resolve())
    except BuildError as exc:
        print(json.dumps({"error": str(exc)}))
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
