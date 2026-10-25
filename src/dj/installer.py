"""The engine's entry in Claude Desktop's config, for `/dj-librarian:install` (W-35, D-29).

Standard library only: `scripts/merge_desktop_config.py` runs it from the engine copy the install
command made (`~/dj-librarian`), before or after `uv sync`.

    merge_desktop_config(path, uv, folder, library)  -> add or replace mcpServers["dj-librarian"]
    remove_desktop_config(path)                     -> take that one entry out
    default_config_path()                           -> the config file on this Mac or Windows PC

The entry is `{"command": <absolute uv>, "args": ["run", "--directory", <absolute folder>,
"--no-sync", "dj-mcp"], "env": {"UV_PROJECT_ENVIRONMENT": <folder>/.venv, "DJ_POWER_MODE": true on Windows,
false on a Mac (W-38, Q-35), "DJ_LIBRARY": <the dj-library folder>}}`; the engine reads DJ_LIBRARY first (dj.hostenv), and the venv is pinned so an inherited
UV_PROJECT_ENVIRONMENT (a contributor's setting) never redirects it. Only `mcpServers["dj-librarian"]` ever changes: every other key keeps
its value and its order, written back in the two-space layout Claude Desktop itself writes. Before
any change the file is copied to `claude_desktop_config.json.bak-<date>` (create-only: `-2`, `-3`
on a second run that day). The same entry again writes nothing (idempotent). A file that is not a
JSON object, or whose `mcpServers` is not an object, is refused and left as it is.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

SERVER = "dj-librarian"
CONFIG_NAME = "claude_desktop_config.json"


class InstallerError(RuntimeError):
    """The config cannot be changed safely. The message is one line; nothing was written."""


def default_config_path(platform: str = sys.platform, env: dict[str, str] | None = None) -> Path:
    """Claude Desktop's config file: macOS and Windows only (D-01)."""
    env = os.environ if env is None else env
    if platform == "darwin":
        return Path(env.get("HOME") or Path.home()) / "Library" / "Application Support" / "Claude" / CONFIG_NAME
    if platform == "win32":
        appdata = env.get("APPDATA")
        if not appdata:
            raise InstallerError("APPDATA is not set, so the Claude Desktop config cannot be found.")
        return Path(appdata) / "Claude" / CONFIG_NAME
    raise InstallerError(f"Claude Desktop runs on macOS and Windows only, not {platform}.")


def entry(uv: str | Path, folder: str | Path, library: str | Path | None = None,
          *, platform: str = sys.platform) -> dict[str, Any]:  # fmt: skip
    """The engine's server entry. `uv` and `folder` must be absolute: the config never relies on
    PATH. On Windows `uv` gets its `.exe` when the file beside it has one: Claude Desktop starts the
    command as written. `library`, when given, must be a dj-library folder (it holds library.yaml)."""
    uv, folder = Path(uv), Path(folder)
    for what, path in (("uv", uv), ("the engine folder", folder)):
        if not path.is_absolute():
            raise InstallerError(f"{what} must be an absolute path, got {path}.")
    if platform == "win32" and not uv.suffix and uv.with_suffix(".exe").is_file():
        uv = uv.with_suffix(".exe")
    if not (folder / "pyproject.toml").is_file():
        raise InstallerError(f"{folder} holds no pyproject.toml: copy the engine there first.")
    # W-38 (D-32): writes into rekordbox on Windows; off on a Mac until its live write test (Q-35)
    power = "true" if platform == "win32" else "false"
    out: dict[str, Any] = {"command": str(uv), "args": ["run", "--directory", str(folder), "--no-sync", "dj-mcp"],
                           "env": {"UV_PROJECT_ENVIRONMENT": str(folder / ".venv"), "DJ_POWER_MODE": power}}  # fmt: skip
    if library is not None:
        library = Path(library).expanduser()
        if not (library / "library.yaml").is_file():
            raise InstallerError(f"{library} is not a dj-library folder (no library.yaml). Pick the folder "
                                 "dj-start set up.")  # fmt: skip
        out["env"]["DJ_LIBRARY"] = str(library.resolve())
    return out


def _read(path: Path) -> dict[str, Any]:
    """The config as an object: {} for a missing or empty file; refused when it is not an object."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except (OSError, UnicodeDecodeError) as exc:
        raise InstallerError(f"{path} cannot be read: {exc}") from None
    if not text.strip():
        return {}
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise InstallerError(f"{path} is not valid JSON ({exc}); fix or move it, then run the install again. "
                             "Nothing was written.") from None  # fmt: skip
    if not isinstance(data, dict):
        raise InstallerError(f"{path} does not hold a JSON object. Nothing was written.")
    if not isinstance(data.get("mcpServers", {}), dict):
        raise InstallerError(f'{path}: "mcpServers" is not an object. Nothing was written.')
    return data


def backup(path: Path, today: date | None = None) -> Path | None:
    """Copy the config to `<name>.bak-<date>` (then -2, -3 ...), never over an older backup."""
    if not path.is_file():
        return None
    stem = f"{path.name}.bak-{(today or date.today()).isoformat()}"
    for n in range(1, 1000):
        target = path.with_name(stem if n == 1 else f"{stem}-{n}")
        try:
            with open(target, "xb") as out, open(path, "rb") as src:
                shutil.copyfileobj(src, out)
            return target
        except FileExistsError:
            continue
    raise InstallerError(f"too many backups of {path.name} today.")


def _write(path: Path, data: dict[str, Any]) -> None:
    """Write through a temp file in the same folder, then replace: never a half-written config."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as out:
            out.write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        os.replace(tmp, path)
    finally:
        Path(tmp).unlink(missing_ok=True)


def merge_desktop_config(path: str | Path, uv: str | Path, folder: str | Path, library: str | Path | None = None,
                         *, today: date | None = None, platform: str = sys.platform) -> dict[str, Any]:  # fmt: skip
    """Add or replace mcpServers["dj-librarian"]; every other key stays as it was."""
    path = Path(path)
    new = entry(uv, folder, library, platform=platform)
    data = _read(path)
    servers = data.get("mcpServers", {})
    if servers.get(SERVER) == new:
        return {"status": "unchanged", "config": str(path), "backup": None, "entry": new}
    status = "replaced" if SERVER in servers else "added"
    saved = backup(path, today)
    data["mcpServers"] = {**servers, SERVER: new}  # an existing key keeps its place
    _write(path, data)
    return {"status": status, "config": str(path), "backup": str(saved) if saved else None, "entry": new}


def remove_desktop_config(path: str | Path, *, today: date | None = None) -> dict[str, Any]:
    """Take mcpServers["dj-librarian"] out (backup first); every other key stays as it was."""
    path = Path(path)
    data = _read(path)
    servers = data.get("mcpServers", {})
    if SERVER not in servers:
        return {"status": "absent", "config": str(path), "backup": None}
    saved = backup(path, today)
    data["mcpServers"] = {key: value for key, value in servers.items() if key != SERVER}
    _write(path, data)
    return {"status": "removed", "config": str(path), "backup": str(saved) if saved else None}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Add or remove the dj-librarian engine in Claude Desktop's config.")
    sub = parser.add_subparsers(dest="action", required=True)
    add = sub.add_parser("merge", help="add or replace the dj-librarian entry")
    add.add_argument("--uv", required=True, help="absolute path of uv")
    add.add_argument("--folder", required=True, help="absolute path of the engine folder (~/dj-librarian)")
    add.add_argument("--library", required=True, help="the DJ's dj-library folder (holds library.yaml)")
    rem = sub.add_parser("remove", help="take the dj-librarian entry out")
    for p in (add, rem):
        p.add_argument("--config", type=Path, help="the config file (default: Claude Desktop's on this computer)")
    args = parser.parse_args(argv)
    try:
        config = args.config or default_config_path()
        if args.action == "merge":
            result = merge_desktop_config(config, args.uv, args.folder, args.library)
        else:
            result = remove_desktop_config(config)
    except (InstallerError, OSError) as exc:  # a locked or read-only config: one line, never a traceback
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
