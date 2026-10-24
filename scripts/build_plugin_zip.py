"""Build the plugin zip a DJ uploads: plugin/, the Door-1 core vendored inside it, and the
engine bundle (D-17, D-22, D-28, Q-21, Q-31).

    uv run python scripts/build_plugin_zip.py [--out DIR] [--flat] [--no-engine]

Writes `<out>/dj-librarian-plugin-<version>.zip` (default `dist/`, gitignored) and prints one
JSON object: the zip, its file count and size, the version, the vendored core modules, whether
the engine is in it (`engine`) and the engine bundle's size in bytes (`engine_size`).

Which zip gives what:
- the full zip (default): the skills (Door 1) and the engine as `plugin/engine.mcpb`, which
  plugin.json's `mcpServers` names, so one upload brings the MCP tools too (Door 2). Whether a
  host starts a `uv` bundle from inside a plugin is open (Q-31): Claude Code 2.1.299 refuses it
  and still loads the skills,
- `--no-engine`: the light zip `dj-librarian-plugin-<version>-no-engine.zip`, the skills only;
  its plugin.json has no `mcpServers`. The engine then comes from the standalone
  `dj-librarian-engine-<version>.mcpb` (scripts/build_mcpb.py; in the Claude desktop app:
  Settings -> Extensions -> drag it in -> Install).

What goes in, under the top folder `plugin/` (with `--flat`, at the zip's root instead: which
layout Claude's "Upload plugin" wants is unverified until the first upload, Q-21):
- every file git tracks under `plugin/` except caches (`__pycache__/`, `*.pyc`, `.mcpb-cache/`,
  OS files) and a local `engine.mcpb` (the engine is built fresh, below). A file under `plugin/`
  that git does not track (a `.env`, notes, local settings, ignored or not) stops the build
  instead of shipping: hard rules 6 and 7,
- `plugin/vendor/dj/`: the Door-1 core and nothing else. The modules `tests/test_door1_imports.py`
  guards (its DOOR1_MODULES list, read from that file, so the two never drift), the W-31 modules
  the identity and the report need (CORE_EXTRA), every `dj` module those import when they load
  (found by importing them with the engine packages blocked, so no engine module can get in),
  the package `__init__.py` files, and the data files in CORE_DATA. No tests, no engine module,
- `plugin/engine.mcpb` (not with `--no-engine`): the engine bundle, built here from the tracked
  files by scripts/build_mcpb.py's functions (never a local copy), the same bytes as
  `dist/dj-librarian-engine-<version>.mcpb`.

The skill scripts find the core in this order: an importable `dj` (the engine venv, later PyPI),
then `../../../../src` (a clone of the repo), then `../../../vendor` (this zip).

The version comes from pyproject.toml and must equal plugin.json's (and the bundle manifest's).
A zip over 15 MB is refused. The zip is the same bytes for the same files (sorted entries, fixed
time stamps). Nothing is uploaded or published: the release workflow only drafts (W-32).
"""

from __future__ import annotations

import argparse
import ast
import importlib.util
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
ENGINE = "engine.mcpb"  # the engine bundle at the plugin's root, where plugin.json's mcpServers points
MCP_SERVERS = f"./{ENGINE}"
MANIFEST = ".claude-plugin/plugin.json"
MAX_BYTES = 15 * 1024 * 1024  # a zip over 15 MB is refused (W-34)


def _load_mcpb():
    """scripts/build_mcpb.py, loaded from beside this file: its functions build the engine."""
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
    """False for what never goes in: caches (a `.mcpb-cache/` Claude Code extracted the engine
    into among them), OS files, a `vendor/` left by a local test (the core is vendored fresh from
    src/) and a local `engine.mcpb` (the engine is built fresh)."""
    parts = rel.split("/")
    return not (parts[0] == VENDOR or rel == ENGINE or any(part in SKIP_DIRS for part in parts)
                or parts[-1] in SKIP_FILES or rel.endswith(".pyc"))  # fmt: skip


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


def zipped_manifest(path: Path, *, engine: bool) -> bytes:
    """plugin.json as it goes in the zip. With the engine: as it is, and it must name
    `./engine.mcpb` under mcpServers. Without: the same object minus `mcpServers`, so the light
    zip does not point at a bundle it lacks (and still validates)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if engine:
        if data.get("mcpServers") != MCP_SERVERS:
            raise BuildError(f'plugin.json must say "mcpServers": "{MCP_SERVERS}" for the zip with the engine.')
        return path.read_bytes()
    data.pop("mcpServers", None)
    return (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def entries(*, flat: bool = False, engine: bool = True) -> tuple[dict[str, Path | bytes], list[str], int | None]:
    """{name in the zip: source file, or the bytes that go in}, the vendored module names, and the
    engine bundle's size (None without it). `flat`: no top folder. `engine`: plugin/engine.mcpb,
    built fresh by scripts/build_mcpb.py's functions."""
    top = "" if flat else f"{TOP}/"
    names: dict[str, Path | bytes] = {}
    for path in plugin_files():  # first: a stray file refuses before the slower import check
        rel = path.relative_to(PLUGIN).as_posix()
        names[f"{top}{rel}"] = zipped_manifest(path, engine=engine) if rel == MANIFEST else path
    modules = core_modules(sorted(set(door1_modules()) | set(CORE_EXTRA)))
    for file in modules.values():
        names[f"{top}{VENDOR}/{file.relative_to(SRC.resolve()).as_posix()}"] = file
    for rel in CORE_DATA:
        source = SRC / rel
        if not source.is_file():
            raise BuildError(f"src/{rel} is missing.")
        names[f"{top}{VENDOR}/{rel}"] = source
    engine_size = None
    if engine:
        try:
            data, _info = mcpb.bundle()
        except mcpb.BuildError as exc:
            raise BuildError(f"the engine bundle: {exc}") from None
        names[f"{top}{ENGINE}"] = data
        engine_size = len(data)
    return dict(sorted(names.items())), list(modules), engine_size


def zip_name(ver: str, *, engine: bool = True) -> str:
    """dj-librarian-plugin-<version>.zip, or ...-no-engine.zip for the light zip."""
    return f"dj-librarian-plugin-{ver}.zip" if engine else f"dj-librarian-plugin-{ver}-no-engine.zip"


def build(out_dir: Path, *, flat: bool = False, engine: bool = True) -> dict[str, object]:
    """Write the zip into `out_dir` (a temp file first, then its name) and say what is in it.
    Nothing is written when the zip would be over MAX_BYTES."""
    ver = version()
    names, modules, engine_size = entries(flat=flat, engine=engine)
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
        "core_modules": modules,
        "engine": engine,
        "engine_size": engine_size,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build dist/dj-librarian-plugin-<version>.zip (nothing is uploaded).")
    parser.add_argument("--out", type=Path, default=REPO / "dist", help="folder for the zip (default: dist/)")
    parser.add_argument("--flat", action="store_true", help="the plugin's files at the zip's root, no plugin/ folder")
    parser.add_argument("--no-engine", action="store_true",
                        help="leave the engine out: the light zip ...-no-engine.zip, skills only")  # fmt: skip
    args = parser.parse_args(argv)
    try:
        result = build(args.out.resolve(), flat=args.flat, engine=not args.no_engine)
    except BuildError as exc:
        print(json.dumps({"error": str(exc)}))
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
