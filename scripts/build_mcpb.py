"""Build the engine as an MCP bundle (.mcpb) a DJ installs by drag-and-drop (W-34, D-28, Q-31).

    python3 scripts/build_mcpb.py [--out DIR] [--plugin] [--npx] [--smoke]

Writes `<out>/dj-librarian-engine-<version>.mcpb` (default `dist/`, gitignored) and prints one JSON
object: the bundle's path, size in bytes, file count and version. Standard library only, so it
runs with a plain `python3` >= 3.11 (CI runs it without uv).

A bundle is a zip with `manifest.json` at its root (modelcontextprotocol/mcpb, MANIFEST.md). The
manifest is `mcpb/manifest.json`, server type `uv`: the host provides Python and the dependencies
from `pyproject.toml` and `uv.lock`, so the DJ installs nothing else. What goes in, and nothing
else (a member outside this list stops the build):
- `manifest.json` (from `mcpb/manifest.json`),
- `pyproject.toml`, `uv.lock`, `.python-version`, `LICENSE`, `README.md` (pyproject.toml names
  the last two, so `uv run` needs them to build the project),
- every file git tracks under `src/dj/` (code and package data), minus caches.
A file under `src/dj/` that git does not track and does not ignore stops the build: the bundle
would not be the code the tests ran on. Track it (`git add`) or move it.

The manifest is checked first, as strictly as the MCPB 0.4 schema the host installs it with
(`src/schemas/0.4.ts`: a key the schema does not name is refused, `server.mcp_config` and its
`command` are required, URLs must be URLs), plus this project's rules: `manifest_version` 0.4,
`server.type` uv, every `${user_config.KEY}` in `mcp_config` declared under `user_config`, the
version equal to pyproject.toml's and plugin.json's, and `server.entry_point` among the bundle's
files. CI also runs the official check (`npx @anthropic-ai/mcpb@<MCPB_CLI's pin> validate`).

The bundle is the same bytes for the same files with the same Python (sorted entries, fixed time
stamps, deflate). The files are read from the working copy, so a checkout with CRLF line endings
(git's core.autocrlf on Windows) or another Python's zlib gives other bytes than the release
built on CI; the files inside are the same code either way.
`--plugin` also writes it to `plugin/engine.mcpb`, where `plugin.json`'s `mcpServers` points (a
build product, gitignored; `claude plugin validate ./plugin` needs it). `--npx` packs the same
staged files with the official CLI at a pinned version (`npx @anthropic-ai/mcpb@<pin> pack`) instead,
when Node's npx is on PATH (it fetches that package from npm; the built-in writer needs no
network). `--smoke` starts the bundle the way a host does before anything is written: unpacked
in a temp folder, `server.mcp_config` run with uv, `initialize` and `tools/list` over stdio, and
the tools compared with the manifest's (needs uv; the first start downloads Python and the
dependencies). Nothing is uploaded or published.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import tomllib
import zipfile
from pathlib import Path
from typing import IO, Any, Iterable
from urllib.parse import urlsplit

REPO = Path(__file__).resolve().parents[1]
MANIFEST = REPO / "mcpb" / "manifest.json"
PLUGIN = REPO / "plugin"
PLUGIN_JSON = Path("plugin") / ".claude-plugin" / "plugin.json"
IN_PLUGIN = "engine.mcpb"  # plugin/engine.mcpb: what plugin.json's mcpServers names
NAME = "dj-librarian-engine-{version}.mcpb"
# The official CLI, pinned: the first release line whose schemas include 0.4 (server type uv).
# CI's manifest check uses the same pin (tests/test_mcpb.py holds them equal).
MCPB_CLI = "@anthropic-ai/mcpb@2.1.2"
# The bundle's files besides manifest.json and the package. pyproject.toml names README.md and
# LICENSE (readme, license-files): `uv run` builds the project and needs both.
TOP_FILES = ("pyproject.toml", "uv.lock", ".python-version", "LICENSE", "README.md")
PACKAGE = "src/dj"
SKIP_DIRS = {"__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache"}
SKIP_FILES = {".DS_Store", "Thumbs.db", "desktop.ini"}
SKIP_SUFFIXES = (".pyc", ".pyo")
STAMP = (2026, 1, 1, 0, 0, 0)  # every entry's time: the same files give the same bundle
MANIFEST_VERSION = "0.4"  # the first manifest version with server.type "uv"
REQUIRED = ("manifest_version", "name", "version", "description", "author", "server")
PLATFORMS = {"darwin", "win32", "linux"}
# Every key the MCPB 0.4 schema allows, object by object (modelcontextprotocol/mcpb
# src/schemas/0.4.ts, the same in MCPB_CLI). Its objects are strict: the host refuses a manifest
# with any other key at install, so the build refuses it first.
ROOT_KEYS = frozenset({
    "$schema", "dxt_version", "manifest_version", "name", "display_name", "version", "description",
    "long_description", "author", "repository", "homepage", "documentation", "support", "icon", "icons",
    "screenshots", "localization", "server", "tools", "tools_generated", "prompts", "prompts_generated",
    "keywords", "license", "privacy_policies", "compatibility", "user_config", "_meta",
})  # fmt: skip
AUTHOR_KEYS = frozenset({"name", "email", "url"})
REPOSITORY_KEYS = frozenset({"type", "url"})
SERVER_KEYS = frozenset({"type", "entry_point", "mcp_config"})
SERVER_TYPES = frozenset({"python", "node", "binary", "uv"})
MCP_CONFIG_KEYS = frozenset({"command", "args", "env", "platform_overrides"})
OVERRIDE_KEYS = frozenset({"command", "args", "env"})
COMPATIBILITY_KEYS = frozenset({"claude_desktop", "platforms", "runtimes"})
RUNTIME_KEYS = frozenset({"python", "node"})
TOOL_KEYS = frozenset({"name", "description"})
PROMPT_KEYS = frozenset({"name", "description", "arguments", "text"})
ICON_KEYS = frozenset({"src", "size", "theme"})
LOCALIZATION_KEYS = frozenset({"resources", "default_locale"})
CONFIG_TYPES = {"string", "number", "boolean", "directory", "file"}
CONFIG_KEYS = {"type", "title", "description", "required", "default", "multiple", "sensitive", "min", "max"}
_REF = re.compile(r"\$\{user_config\.([A-Za-z0-9_]+)\}")
_VAR = re.compile(r"\$\{([^}]+)\}")
_SCHEME = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*")
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
_BCP47 = re.compile(r"[A-Za-z0-9]{2,8}(?:-[A-Za-z0-9]{1,8})*")
_ICON_SIZE = re.compile(r"\d+x\d+")
SMOKE_SECONDS = 900.0  # --smoke: the first start may download Python and every dependency
PROTOCOL = "2025-06-18"  # the MCP protocol version --smoke asks for


class BuildError(RuntimeError):
    """The bundle cannot be built as it must be. Nothing was written."""


def _json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise BuildError(f"{path.name} is missing ({path}).") from None
    except ValueError as exc:
        raise BuildError(f"{path.name} is not valid JSON: {exc}") from None


def load_manifest(path: Path = MANIFEST) -> dict[str, Any]:
    manifest = _json(path)
    if not isinstance(manifest, dict):
        raise BuildError(f"{path.name} must hold one JSON object.")
    return manifest


def versions(repo: Path = REPO) -> tuple[str, str]:
    """(pyproject.toml's version, plugin.json's version)."""
    try:
        project = tomllib.loads((repo / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    except (OSError, KeyError, tomllib.TOMLDecodeError) as exc:
        raise BuildError(f"pyproject.toml has no readable project.version: {exc}") from None
    plugin = _json(repo / PLUGIN_JSON)
    return str(project), str(plugin.get("version", "")) if isinstance(plugin, dict) else ""


def _text(value: Any) -> bool:
    return isinstance(value, str) and value.strip() != ""


def _strings(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _url(value: Any) -> bool:
    """A URL as the schema's z.string().url() means it, read a little stricter: scheme://host..."""
    if not isinstance(value, str) or value != value.strip() or any(ch.isspace() for ch in value):
        return False
    try:
        parts = urlsplit(value)
    except ValueError:
        return False
    return bool(_SCHEME.fullmatch(parts.scheme) and parts.netloc)


def _unknown(out: list[str], where: str, obj: dict[str, Any], allowed: frozenset[str] | set[str]) -> None:
    extra = sorted(set(obj) - set(allowed))
    if extra:
        out.append(f"{where} has unknown fields {extra} (the MCPB 0.4 schema allows no others)")


def _object(out: list[str], where: str, value: Any, allowed: frozenset[str] | set[str]) -> dict[str, Any] | None:
    """`value` when it is an object (its unknown keys reported), else None and a line."""
    if not isinstance(value, dict):
        out.append(f"{where} must be an object")
        return None
    _unknown(out, where, value, allowed)
    return value


def _check_user_config(out: list[str], config: dict[str, Any]) -> None:
    for key, option in config.items():
        if not isinstance(option, dict):
            out.append(f"user_config.{key} must be an object")
            continue
        kind = option.get("type")
        if kind not in CONFIG_TYPES:
            out.append(f"user_config.{key}.type must be one of {sorted(CONFIG_TYPES)}, not {kind!r}")
        for field in ("title", "description"):
            if not _text(option.get(field)):
                out.append(f"user_config.{key}.{field} is missing")
        if set(option) - CONFIG_KEYS:
            out.append(f"user_config.{key} has unknown fields {sorted(set(option) - CONFIG_KEYS)}")
        for field in ("required", "multiple", "sensitive"):
            if field in option and not isinstance(option[field], bool):
                out.append(f"user_config.{key}.{field} must be true or false")
        for field in ("min", "max"):
            if field in option and not _number(option[field]):
                out.append(f"user_config.{key}.{field} must be a number")
        default = option.get("default")
        if "default" in option and not (isinstance(default, (str, bool)) or _number(default) or _strings(default)):
            out.append(f"user_config.{key}.default must be a string, a number, true/false or a list of strings")
        if option.get("sensitive") and kind != "string":
            out.append(f"user_config.{key}: only a string can be sensitive")
        if kind == "boolean" and "default" in option and not isinstance(default, bool):
            out.append(f"user_config.{key}.default must be true or false")


def _check_launch(out: list[str], where: str, mcp: dict[str, Any], *, partial: bool) -> None:
    """command / args / env of `mcp_config` or of one of its platform_overrides (`partial`)."""
    if "command" not in mcp:
        if not partial:
            out.append(f"{where}.command is missing")
    elif not _text(mcp["command"]):
        out.append(f"{where}.command must be a non-empty string")
    if "args" in mcp and not _strings(mcp["args"]):
        out.append(f"{where}.args must be a list of strings")
    env = mcp.get("env", {})
    if not (isinstance(env, dict) and all(isinstance(k, str) and isinstance(v, str) for k, v in env.items())):
        out.append(f"{where}.env must map names to strings")


def _check_server(out: list[str], server: Any, config: dict[str, Any], names: Iterable[str] | None) -> None:
    server = _object(out, "server", server, SERVER_KEYS)
    if server is None:
        return
    if server.get("type") != "uv":
        out.append(f"server.type must be 'uv' (the host runs Python and the dependencies), not {server.get('type')!r}")
    entry = server.get("entry_point")
    if not _text(entry):
        out.append("server.entry_point is missing")
    elif names is not None and entry not in set(names):
        out.append(f"server.entry_point {entry} is not in the bundle")
    if "mcp_config" not in server:
        out.append("server.mcp_config is missing (the 0.4 schema requires it)")
        return
    mcp = _object(out, "server.mcp_config", server["mcp_config"], MCP_CONFIG_KEYS)
    if mcp is None:
        return
    _check_launch(out, "server.mcp_config", mcp, partial=False)
    overrides = mcp.get("platform_overrides", {})
    if not isinstance(overrides, dict):
        out.append("server.mcp_config.platform_overrides must be an object")
    else:
        for platform, override in overrides.items():
            where = f"server.mcp_config.platform_overrides.{platform}"
            if (override := _object(out, where, override, OVERRIDE_KEYS)) is not None:
                _check_launch(out, where, override, partial=True)
    for key in sorted(set(_REF.findall(json.dumps(mcp))) - set(config)):
        out.append(f"server.mcp_config uses ${{user_config.{key}}}, which user_config does not declare")


def _check_lists(out: list[str], manifest: dict[str, Any]) -> None:
    """tools, prompts, keywords, screenshots, privacy_policies, icons."""
    tools = manifest.get("tools", [])
    if not (isinstance(tools, list) and all(isinstance(t, dict) and _text(t.get("name")) and _text(t.get("description"))
                                            for t in tools)):  # fmt: skip
        out.append("tools must be a list of {name, description}")
    else:
        for i, tool in enumerate(tools):
            _unknown(out, f"tools[{i}] ({tool['name']})", tool, TOOL_KEYS)
        if len({t["name"] for t in tools}) != len(tools):
            out.append("tools lists a name twice")
    prompts = manifest.get("prompts", [])
    if not isinstance(prompts, list):
        out.append("prompts must be a list")
    else:
        for i, prompt in enumerate(prompts):
            if (prompt := _object(out, f"prompts[{i}]", prompt, PROMPT_KEYS)) is None:
                continue
            if not (isinstance(prompt.get("name"), str) and isinstance(prompt.get("text"), str)):
                out.append(f"prompts[{i}] needs a name and a text")
            if "arguments" in prompt and not _strings(prompt["arguments"]):
                out.append(f"prompts[{i}].arguments must be a list of strings")
    for key in ("keywords", "screenshots"):
        if key in manifest and not _strings(manifest[key]):
            out.append(f"{key} must be a list of strings")
    policies = manifest.get("privacy_policies", [])
    if not (isinstance(policies, list) and all(_url(p) for p in policies)):
        out.append("privacy_policies must be a list of URLs")
    icons = manifest.get("icons", [])
    if not isinstance(icons, list):
        out.append("icons must be a list")
    else:
        for i, icon in enumerate(icons):
            if (icon := _object(out, f"icons[{i}]", icon, ICON_KEYS)) is None:
                continue
            if not (isinstance(icon.get("src"), str) and _ICON_SIZE.fullmatch(str(icon.get("size", "")))):
                out.append(f"icons[{i}] needs a src and a size like 512x512")
            if "theme" in icon and not _text(icon["theme"]):
                out.append(f"icons[{i}].theme must be a non-empty string")


def check_manifest(manifest: dict[str, Any], *, repo: Path = REPO, names: Iterable[str] | None = None) -> list[str]:
    """Every way `manifest` is not what this bundle needs, one line each ([] = good): the MCPB 0.4
    schema, read as strictly as the host reads it, and this project's own rules. `names`: the
    bundle's members, for the entry point check."""
    out: list[str] = []
    _unknown(out, "the manifest", manifest, ROOT_KEYS)
    for key in REQUIRED:
        if key not in manifest or manifest[key] in (None, "", {}, []):
            out.append(f"{key} is missing")
    if manifest.get("manifest_version") != MANIFEST_VERSION:
        out.append(f"manifest_version must be {MANIFEST_VERSION!r} (server type uv), not {manifest.get('manifest_version')!r}")
    if "dxt_version" in manifest and manifest["dxt_version"] != MANIFEST_VERSION:
        out.append(f"dxt_version (deprecated) must be {MANIFEST_VERSION!r} when given")
    for key in ("name", "version", "description"):
        if key in manifest and not _text(manifest[key]):
            out.append(f"{key} must be a non-empty string")
    for key in ("$schema", "display_name", "long_description", "icon", "license"):
        if key in manifest and not isinstance(manifest[key], str):
            out.append(f"{key} must be a string")
    for key in ("homepage", "documentation", "support"):
        if key in manifest and not _url(manifest[key]):
            out.append(f"{key} must be a URL")
    for key in ("tools_generated", "prompts_generated"):
        if key in manifest and not isinstance(manifest[key], bool):
            out.append(f"{key} must be true or false")

    if "author" in manifest and (author := _object(out, "author", manifest["author"], AUTHOR_KEYS)) is not None:
        if not _text(author.get("name")):
            out.append("author must be an object with a name")
        if "email" in author and not (isinstance(author["email"], str) and _EMAIL.fullmatch(author["email"])):
            out.append("author.email must be an email address")
        if "url" in author and not _url(author["url"]):
            out.append("author.url must be a URL")
    if "repository" in manifest:
        repository = _object(out, "repository", manifest["repository"], REPOSITORY_KEYS)
        if repository is not None:
            if not isinstance(repository.get("type"), str):
                out.append("repository.type must be a string")
            if not _url(repository.get("url")):
                out.append("repository.url must be a URL")
    if "localization" in manifest:
        local = _object(out, "localization", manifest["localization"], LOCALIZATION_KEYS)
        if local is not None:
            if not (isinstance(local.get("resources"), str) and "${locale}" in local["resources"].casefold()):
                out.append('localization.resources must hold a "${locale}" placeholder')
            if not (isinstance(local.get("default_locale"), str) and _BCP47.fullmatch(local["default_locale"])):
                out.append("localization.default_locale must be a BCP 47 locale")
    meta = manifest.get("_meta", {})
    if not (isinstance(meta, dict) and all(isinstance(v, dict) for v in meta.values())):
        out.append("_meta must map names to objects")

    config = manifest.get("user_config", {})
    if not isinstance(config, dict):
        out.append("user_config must be an object")
        config = {}
    _check_user_config(out, config)
    if "server" in manifest and manifest["server"] not in (None, {}):
        _check_server(out, manifest["server"], config, names)
    _check_lists(out, manifest)

    if "compatibility" in manifest:
        compat = _object(out, "compatibility", manifest["compatibility"], COMPATIBILITY_KEYS)
        if compat is not None:
            if "claude_desktop" in compat and not isinstance(compat["claude_desktop"], str):
                out.append("compatibility.claude_desktop must be a string")
            platforms = compat.get("platforms", [])
            if not (isinstance(platforms, list) and set(platforms) <= PLATFORMS):
                out.append(f"compatibility.platforms must be a list from {sorted(PLATFORMS)}")
            if "runtimes" in compat and (runtimes := _object(out, "compatibility.runtimes", compat["runtimes"],
                                                             RUNTIME_KEYS)) is not None:  # fmt: skip
                if not all(isinstance(v, str) for v in runtimes.values()):
                    out.append("compatibility.runtimes must map runtimes to version strings")

    if _text(manifest.get("version")):
        project, plugin = versions(repo)
        if not manifest["version"] == project == plugin:
            out.append(f"version {manifest['version']} must equal pyproject.toml ({project}) and plugin.json ({plugin})")
    return out


def _shipped(rel: str) -> bool:
    """False for caches and OS files, which never go in."""
    parts = rel.split("/")
    return not (any(part in SKIP_DIRS for part in parts) or parts[-1] in SKIP_FILES or rel.endswith(SKIP_SUFFIXES))


def _allowed(name: str) -> bool:
    """The bundle's whole allowlist: manifest.json, TOP_FILES, and package files under src/dj/."""
    if name == "manifest.json" or name in TOP_FILES:
        return True
    parts = name.split("/")
    return (name.startswith(f"{PACKAGE}/") and _shipped(name) and "" not in parts and ".." not in parts
            and "\\" not in name and not parts[-1].startswith(".env"))  # fmt: skip


def _git(repo: Path, *args: str) -> list[str]:
    """`git ls-files -z <args>` at the repo root: repo-relative POSIX paths."""
    try:
        done = subprocess.run(["git", "-C", str(repo), "ls-files", "-z", *args], capture_output=True, timeout=120)
    except OSError as exc:
        raise BuildError(f"git is needed to list the engine's files: {exc}") from None
    if done.returncode != 0:
        raise BuildError("the repo is not a git checkout: the bundle is built from the files git tracks. "
                         + done.stderr.decode("utf-8", "replace").strip())  # fmt: skip
    return [name for name in done.stdout.decode("utf-8").split("\0") if name]


def members(repo: Path = REPO, manifest: Path | None = None) -> dict[str, Path]:
    """{name in the bundle: source file}, sorted. The manifest from mcpb/, the TOP_FILES and every
    file git tracks under src/dj/ (as it is on disk), minus caches. Refuses a top file git does not
    track, a file under src/dj/ git neither tracks nor ignores, and any name outside the allowlist."""
    manifest = manifest or repo / "mcpb" / "manifest.json"
    stray = sorted(rel for rel in _git(repo, "--others", "--exclude-standard", "--", PACKAGE) if _shipped(rel))
    if stray:
        raise BuildError(f"{PACKAGE}/ holds files git does not track: " + ", ".join(stray)
                         + ". Track them (git add) or move them: the bundle ships the tracked code only.")  # fmt: skip
    tracked = set(_git(repo, "--cached", "--", *TOP_FILES, PACKAGE))
    names: dict[str, Path] = {"manifest.json": manifest}
    for rel in TOP_FILES:
        if rel not in tracked:
            raise BuildError(f"{rel} is not tracked by git: the bundle needs it.")
        names[rel] = repo / rel
    for rel in sorted(tracked):
        path = repo / rel
        if rel.startswith(f"{PACKAGE}/") and _shipped(rel) and path.is_file() and not path.is_symlink():
            names[rel] = path
    for name, path in names.items():
        if not _allowed(name):
            raise BuildError(f"{name} is not a file the bundle may hold.")
        if not path.is_file():
            raise BuildError(f"{name} is missing on disk ({path}).")
    return dict(sorted(names.items()))


def pack(names: dict[str, Path]) -> bytes:
    """The zip itself: the given files, sorted, fixed time stamps and modes, deflated."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for name in sorted(names):
            info = zipfile.ZipInfo(name, date_time=STAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3  # the same header on every OS
            info.external_attr = 0o100644 << 16
            zf.writestr(info, names[name].read_bytes())
    return buf.getvalue()


def pack_npx(names: dict[str, Path]) -> bytes:
    """The same files packed by the official CLI at its pinned version (`npx MCPB_CLI pack`).
    Refuses when npx is not on PATH, when the CLI fails, or when its zip holds any other file list."""
    npx = shutil.which("npx")
    if npx is None:
        raise BuildError("--npx needs Node's npx on PATH. Leave --npx out: the built-in writer makes the same layout.")
    with tempfile.TemporaryDirectory(prefix="djl-mcpb-") as tmp:
        stage = Path(tmp) / "stage"
        for name, source in names.items():
            (stage / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, stage / name)
        packed = Path(tmp) / "engine.mcpb"
        try:
            done = subprocess.run([npx, "--yes", MCPB_CLI, "pack", str(stage), str(packed)],
                                  capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)  # fmt: skip
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise BuildError(f"npx {MCPB_CLI} pack did not run: {exc}") from None
        if done.returncode != 0 or not packed.is_file():
            raise BuildError(f"npx {MCPB_CLI} pack failed: {(done.stderr or done.stdout).strip()[-800:]}")
        data = packed.read_bytes()
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        got = {n for n in zf.namelist() if not n.endswith("/")}
    if got != set(names):
        raise BuildError(f"npx {MCPB_CLI} pack made a different file list: "
                         f"extra {sorted(got - set(names))}, missing {sorted(set(names) - got)}.")  # fmt: skip
    return data


# -- --smoke: start the bundle the way a host does ---------------------------------------------------


def launch(manifest: dict[str, Any], ext: Path, folders: Path) -> tuple[list[str], dict[str, str]]:
    """The command and the env a host builds from `server.mcp_config` for the bundle unpacked in
    `ext`: `${__dirname}` is `ext`, `${/}` the path separator, a directory setting gets an empty
    folder of its own under `folders`, every other setting its default or empty (a boolean: false)."""
    values = {"__dirname": str(ext), "/": os.sep, "pathSeparator": os.sep, "HOME": str(Path.home())}
    for key, option in manifest.get("user_config", {}).items():
        if option.get("type") == "directory":
            (folders / key).mkdir(parents=True, exist_ok=True)
            value = str(folders / key)
        elif option.get("type") == "boolean":
            value = "true" if option.get("default") is True else "false"
        else:
            value = str(option.get("default", ""))
        values[f"user_config.{key}"] = value

    def fill(text: str) -> str:
        return _VAR.sub(lambda m: values.get(m.group(1), m.group(0)), text)

    mcp = dict(manifest["server"]["mcp_config"])
    mcp.update(mcp.pop("platform_overrides", {}).get(sys.platform, {}))
    command = [fill(mcp["command"]), *(fill(arg) for arg in mcp.get("args", []))]
    return command, {key: fill(value) for key, value in mcp.get("env", {}).items()}


def _pump(stream: IO[bytes], lines: queue.Queue) -> None:
    for line in iter(stream.readline, b""):
        lines.put(line)
    lines.put(None)


def _tail(log: Path) -> str:
    try:
        text = log.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""
    return f" Its stderr ends: {text[-1500:]}" if text else ""


def _answer(lines: queue.Queue, msg_id: int, seconds: float, log: Path) -> dict[str, Any]:
    """The result of JSON-RPC request `msg_id`, from the server's stdout lines (anything that is not
    a JSON object, a notification or another id is skipped)."""
    deadline = time.monotonic() + seconds
    while (left := deadline - time.monotonic()) > 0:
        try:
            line = lines.get(timeout=left)
        except queue.Empty:
            break
        if line is None:
            raise BuildError("the engine stopped before it answered." + _tail(log))
        text = line.decode("utf-8", "replace").strip()
        try:
            message = json.loads(text) if text.startswith("{") else None
        except ValueError:
            message = None
        if not isinstance(message, dict) or message.get("id") != msg_id:
            continue
        if "error" in message:
            raise BuildError(f"the engine answered request {msg_id} with an error: {message['error']}")
        return message.get("result") or {}
    raise BuildError(f"the engine did not answer within {seconds:g} s." + _tail(log))


def _send(proc: subprocess.Popen, message: dict[str, Any]) -> None:
    try:
        proc.stdin.write((json.dumps(message) + "\n").encode("utf-8"))
        proc.stdin.flush()
    except OSError as exc:
        raise BuildError(f"the engine stopped reading: {exc}") from None


def _stop(proc: subprocess.Popen) -> None:
    """Close stdin (an MCP stdio server ends there), then terminate and kill if it lingers."""
    try:
        proc.stdin.close()
    except OSError:
        pass
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=15)


def handshake(data: bytes, *, offline: bool = False, timeout: float = SMOKE_SECONDS) -> dict[str, Any]:
    """Start the bundle `data` as a host would and ask it for its tools: unpack it into a temp
    folder outside the checkout, run its `server.mcp_config` (launch()), send `initialize` and
    `tools/list` over stdio, and compare the tool names with the manifest's `tools`. Returns
    {"tools": count, "server": serverInfo}. Refuses when the command is not on PATH, the server
    does not answer within `timeout` seconds or stops, or its tools differ. `offline`: uv takes
    Python and the dependencies from its cache only (UV_OFFLINE), never the network."""
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        manifest = json.loads(zf.read("manifest.json"))
        with tempfile.TemporaryDirectory(prefix="djl-mcpb-smoke-", ignore_cleanup_errors=True) as tmp:
            ext = Path(tmp) / "extension"
            zf.extractall(ext)
            command, server_env = launch(manifest, ext, Path(tmp) / "settings")
            exe = shutil.which(command[0])
            if exe is None:
                raise BuildError(f"--smoke starts the bundle with {command[0]!r}, which is not on PATH.")
            env = {key: value for key, value in os.environ.items() if key != "VIRTUAL_ENV"}
            env.update(server_env)  # the manifest's env wins over the caller's, as with a host
            if offline:
                env["UV_OFFLINE"] = "1"
            log = Path(tmp) / "stderr.log"
            with log.open("wb") as err:
                proc = subprocess.Popen([exe, *command[1:]], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=err, env=env, cwd=tmp)  # fmt: skip
                lines: queue.Queue = queue.Queue()
                pump = threading.Thread(target=_pump, args=(proc.stdout, lines), daemon=True)
                pump.start()
                try:
                    _send(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                 "params": {"protocolVersion": PROTOCOL, "capabilities": {},
                                            "clientInfo": {"name": "build_mcpb --smoke", "version": "0"}}})  # fmt: skip
                    init = _answer(lines, 1, timeout, log)
                    _send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})
                    _send(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
                    listed = _answer(lines, 2, min(timeout, 120.0), log).get("tools", [])
                finally:
                    _stop(proc)
                    pump.join(timeout=10)  # it ends at EOF once the server is gone
                    if not pump.is_alive():
                        proc.stdout.close()
    got = sorted(str(tool.get("name")) for tool in listed if isinstance(tool, dict))
    want = sorted(tool["name"] for tool in manifest.get("tools", []))
    if got != want:
        raise BuildError("the engine lists other tools than the manifest: not in the manifest "
                         f"{sorted(set(got) - set(want))}, missing {sorted(set(want) - set(got))}.")  # fmt: skip
    return {"tools": len(got), "server": init.get("serverInfo", {})}


# -- the build ---------------------------------------------------------------------------------------


def bundle(repo: Path = REPO, *, npx: bool = False) -> tuple[bytes, dict[str, Any]]:
    """Check the manifest, gather the files and pack them: (the bundle's bytes, its manifest).
    build_plugin_zip.py calls this to put the engine in the plugin zip."""
    manifest_path = repo / "mcpb" / "manifest.json"
    manifest = load_manifest(manifest_path)
    names = members(repo, manifest_path)
    problems = check_manifest(manifest, repo=repo, names=names)
    if problems:
        raise BuildError("mcpb/manifest.json: " + "; ".join(problems) + ".")
    data = pack_npx(names) if npx else pack(names)
    return data, {"manifest": manifest, "files": len(names), "names": list(names)}


def _write(target: Path, data: bytes) -> None:
    """`data` to `target` through a temp file in the same folder, then one rename."""
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, target)
    finally:
        Path(tmp).unlink(missing_ok=True)


def _shown(path: Path, repo: Path) -> str:
    path = path.resolve()
    return path.relative_to(repo.resolve()).as_posix() if path.is_relative_to(repo.resolve()) else path.as_posix()


def build(out_dir: Path, *, repo: Path = REPO, plugin_dir: Path | None = None, npx: bool = False,
          smoke: bool = False) -> dict[str, Any]:  # fmt: skip
    """Write the bundle into `out_dir` (and to `plugin_dir`/engine.mcpb when given) and say what
    it is. `smoke`: start it first (handshake()). Nothing is written when a check fails."""
    data, info = bundle(repo, npx=npx)
    started = handshake(data) if smoke else None
    version = info["manifest"]["version"]
    target = out_dir / NAME.format(version=version)
    _write(target, data)
    result: dict[str, Any] = {"path": _shown(target, repo), "size": len(data), "files": info["files"],
                              "version": version}  # fmt: skip
    if plugin_dir is not None:
        _write(plugin_dir / IN_PLUGIN, data)
        result["plugin"] = _shown(plugin_dir / IN_PLUGIN, repo)
    if started is not None:
        result["smoke"] = started
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build dist/dj-librarian-engine-<version>.mcpb (nothing is uploaded).")
    parser.add_argument("--out", type=Path, default=REPO / "dist", help="folder for the bundle (default: dist/)")
    parser.add_argument("--plugin", action="store_true", help="also write plugin/engine.mcpb (plugin.json points there)")
    parser.add_argument("--npx", action="store_true", help=f"pack with `npx {MCPB_CLI} pack` (needs Node)")
    parser.add_argument("--smoke", action="store_true",
                        help="start the bundle with uv as a host would and compare its tools with the manifest's")  # fmt: skip
    args = parser.parse_args(argv)
    try:
        result = build(args.out.resolve(), plugin_dir=PLUGIN if args.plugin else None, npx=args.npx,
                       smoke=args.smoke)  # fmt: skip
    except BuildError as exc:
        print(json.dumps({"error": str(exc)}))
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
