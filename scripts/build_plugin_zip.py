"""Build the plugin zip a DJ uploads for a private test install: plugin/ plus the Door-1 core
vendored inside it (D-17, D-22, Q-21).

    uv run python scripts/build_plugin_zip.py [--out DIR] [--flat]

Writes `<out>/dj-librarian-plugin-<version>.zip` (default `dist/`, gitignored) and prints one
JSON object: the zip, its file count and size, the version, the vendored core modules.

What goes in, under the top folder `plugin/` (with `--flat`, at the zip's root instead: which
layout Claude's "Upload plugin" wants is unverified until the first upload, Q-21):
- every file git tracks under `plugin/` except caches (`__pycache__/`, `*.pyc`, `.mcpb-cache/`,
  OS files). A file under `plugin/` that git does not track (a `.env`, notes, local settings,
  ignored or not) stops the build instead of shipping: hard rules 6 and 7,
- `plugin/vendor/dj/`: the Door-1 core and nothing else. The modules `tests/test_door1_imports.py`
  guards (its DOOR1_MODULES list, read from that file, so the two never drift), the W-31 modules
  the identity and the report need (CORE_EXTRA), every `dj` module those import when they load
  (found by importing them with the engine packages blocked, so no engine module can get in),
  the package `__init__.py` files, and the data files in CORE_DATA. No tests, no engine.

The skill scripts find the core in this order: an importable `dj` (the engine venv, later PyPI),
then `../../../../src` (a clone of the repo), then `../../../vendor` (this zip).

The version comes from pyproject.toml and must equal plugin.json's. The zip is the same bytes
for the same files (sorted entries, fixed time stamps). Nothing is uploaded or published: the
release step that would (W-27) waits for the owner's yes.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import tomllib
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PLUGIN = REPO / "plugin"
SRC = REPO / "src"
DOOR1_TEST = REPO / "tests" / "test_door1_imports.py"
TOP = "plugin"  # the zip's one top folder: the plugin as it sits in the repo
VENDOR = "vendor"  # plugin/vendor/dj/ holds the core
# Engine-only packages (Door 2). A vendored module must import without them: the same list the
# Door-1 test blocks.
ENGINE_PACKAGES = ("pyrekordbox", "rapidfuzz", "httpx", "typer", "mcp")
# Added by W-30b to what DOOR1_MODULES guards: the identity, the sleeve and the report's charts.
CORE_EXTRA = ("dj.analysis.identity", "dj.sleeve", "dj.design", "dj.report_charts")
# Data files the core reads next to its modules (paths relative to src/).
CORE_DATA = ("dj/analysis/archetypes.yaml",)
SKIP_DIRS = {"__pycache__", ".mcpb-cache"}
SKIP_FILES = {".DS_Store", "Thumbs.db", "desktop.ini"}
STAMP = (2026, 1, 1, 0, 0, 0)  # every entry's time: the same files give the same zip


class BuildError(RuntimeError):
    """The zip cannot be built as it must be. Nothing was written."""


def version() -> str:
    """pyproject.toml's version; plugin.json must say the same (CLAUDE.md, Conventions)."""
    project = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    manifest = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))["version"]
    if project != manifest:
        raise BuildError(f"pyproject.toml says {project}, plugin.json says {manifest}: make them equal first.")
    return str(project)


def door1_modules(path: Path = DOOR1_TEST) -> list[str]:
    """The DOOR1_MODULES list of tests/test_door1_imports.py, read without importing the test."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "DOOR1_MODULES" for t in node.targets):
            return list(ast.literal_eval(node.value))
    raise BuildError(f"{path.name} has no DOOR1_MODULES list.")


def core_modules(modules: list[str]) -> dict[str, Path]:
    """Every `dj` module that loads when `modules` are imported with the engine packages blocked:
    {module name: its file}. An engine module cannot be among them: it would not import."""
    code = textwrap.dedent(f"""
        import importlib, json, sys
        for name in {ENGINE_PACKAGES!r}:
            sys.modules[name] = None  # `import name` raises ImportError
        for mod in {modules!r}:
            importlib.import_module(mod)
        found = {{n: m.__file__ for n, m in sys.modules.items()
                 if (n == "dj" or n.startswith("dj.")) and getattr(m, "__file__", None)}}
        print(json.dumps(found))
    """)
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(SRC), os.environ.get("PYTHONPATH", "")]).rstrip(os.pathsep))
    done = subprocess.run([sys.executable, "-c", code], cwd=REPO, env=env, capture_output=True, text=True,
                          encoding="utf-8", timeout=120)  # fmt: skip
    if done.returncode != 0:
        raise BuildError(f"the core does not import without the engine packages:\n{done.stderr.strip()}")
    found = {name: Path(file).resolve() for name, file in json.loads(done.stdout).items()}
    for name, file in found.items():
        if not file.is_relative_to(SRC.resolve() / "dj"):
            raise BuildError(f"{name} loaded from {file}, not from src/dj: run from the repo.")
    return dict(sorted(found.items()))


def _shipped(rel: str) -> bool:
    """False for what never goes in: caches, OS files, and a `vendor/` left by a local test (the
    core is vendored fresh from src/)."""
    parts = rel.split("/")
    return not (parts[0] == VENDOR or any(part in SKIP_DIRS for part in parts) or parts[-1] in SKIP_FILES
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
    minus caches, OS files and a local `vendor/`. A file git does not track (a `.env`, notes,
    local settings, ignored or not) is refused, not shipped: hard rules 6 and 7. Track it to ship
    it, or move it out of plugin/."""
    stray = sorted(rel for rel in _git_files("--others") if _shipped(rel))
    if stray:
        raise BuildError("plugin/ holds files git does not track, which would ship in the zip: "
                         + ", ".join(stray) + ". Track them to ship them, or move them out of plugin/.")  # fmt: skip
    out = []
    for rel in sorted(set(_git_files("--cached"))):
        path = PLUGIN / rel
        if _shipped(rel) and path.is_file() and not path.is_symlink():  # a tracked file deleted on disk: gone
            out.append(path)
    return out


def entries(*, flat: bool = False) -> tuple[dict[str, Path], list[str]]:
    """{name in the zip: source file}, and the vendored module names. `flat`: no top folder."""
    top = "" if flat else f"{TOP}/"
    names: dict[str, Path] = {}
    for path in plugin_files():  # first: a stray file refuses before the slower import check
        names[f"{top}{path.relative_to(PLUGIN).as_posix()}"] = path
    modules = core_modules(sorted(set(door1_modules()) | set(CORE_EXTRA)))
    for file in modules.values():
        names[f"{top}{VENDOR}/{file.relative_to(SRC.resolve()).as_posix()}"] = file
    for rel in CORE_DATA:
        source = SRC / rel
        if not source.is_file():
            raise BuildError(f"src/{rel} is missing.")
        names[f"{top}{VENDOR}/{rel}"] = source
    return dict(sorted(names.items())), list(modules)


def build(out_dir: Path, *, flat: bool = False) -> dict[str, object]:
    """Write the zip into `out_dir` (a temp file first, then its name) and say what is in it."""
    ver = version()
    names, modules = entries(flat=flat)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"dj-librarian-plugin-{ver}.zip"
    fd, tmp = tempfile.mkstemp(dir=out_dir, prefix=f".{target.name}.", suffix=".tmp")
    os.close(fd)
    try:
        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
            for name, source in names.items():
                info = zipfile.ZipInfo(name, date_time=STAMP)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                zf.writestr(info, source.read_bytes())
        os.replace(tmp, target)
    finally:
        Path(tmp).unlink(missing_ok=True)
    return {
        "zip": target.as_posix() if not target.is_relative_to(REPO) else target.relative_to(REPO).as_posix(),
        "files": len(names),
        "bytes": target.stat().st_size,
        "version": ver,
        "core_modules": modules,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build dist/dj-librarian-plugin-<version>.zip (nothing is uploaded).")
    parser.add_argument("--out", type=Path, default=REPO / "dist", help="folder for the zip (default: dist/)")
    parser.add_argument("--flat", action="store_true", help="the plugin's files at the zip's root, no plugin/ folder")
    args = parser.parse_args(argv)
    try:
        result = build(args.out.resolve(), flat=args.flat)
    except BuildError as exc:
        print(json.dumps({"error": str(exc)}))
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
