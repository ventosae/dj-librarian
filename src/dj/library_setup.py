"""The dj-library folder before session 1, and which session dj-start runs (W-36, D-30).

Install comes first. `/dj-librarian:install` step 6 asks once which folder should be the DJ's
dj-library and makes it (`scripts/library_init.py` runs `main`):

    prepare(folder, device=..., today=...)  -> {status, library, created, log}

- a folder that does not exist yet: created (its parents too) and scaffolded;
- an empty folder: scaffolded;
- a folder that already holds this tool's library.yaml: used as it is (status "existing");
- a folder with other files in it: refused, pick another;
- a path inside a cloud-synced folder (OneDrive, Dropbox, iCloud, Google Drive): refused, the same
  rule as the engine folder (install step 3);
- a drive root, the home folder or a shared user folder: refused (onboarding.library_root).

The scaffold is the one session 1 makes (libfolder.scaffold: the device, today's date, no export
yet) plus one log.md line. `default_folder()` is what the install offers: ~/Music/dj-library.

`session_path(tools)`: "engine" when the dj-librarian engine's `dj_status` tool is among the tools
the session can call, else "xml"; dj-start picks its path by this rule (SKILL.md, "With the
engine"). `set_handle(folder, name)` writes the DJ's handle into library.yaml (dj-start step 1 on
the engine path, where no export runs init). Standard library and PyYAML only (Door 1).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any, Iterable

from dj import libfolder, onboarding
from dj.libfolder import DEVICES, LibraryFolder, LibraryFolderError

SYNCED = ("onedrive", "dropbox", "icloud", "mobile documents", "cloudstorage", "google drive")
OS_FILES = {".ds_store", "desktop.ini", "thumbs.db", ".localized"}
_ENGINE_STATUS = re.compile(r"(?:mcp__(?:plugin_dj-librarian_)?dj-librarian__)?dj_status")


class SetupError(RuntimeError):
    """The folder cannot be the dj-library. `reason`: synced, not_empty, refused, folder, usage."""

    def __init__(self, message: str, reason: str) -> None:
        super().__init__(message)
        self.reason = reason


def default_folder(home: Path | None = None) -> Path:
    return (home or Path.home()) / "Music" / "dj-library"


def synced(path: Path) -> str | None:
    """The cloud-synced folder `path` sits in (its name as written), or None."""
    for part in path.parts:
        if any(name in part.casefold() for name in SYNCED):
            return part
    return None


def _entries(root: Path) -> list[str]:
    try:
        return [e.name for e in os.scandir(root) if e.name.casefold() not in OS_FILES]
    except OSError as exc:
        raise SetupError(f"{root} cannot be read: {exc.strerror or exc}.", "folder") from None


def prepare(folder: str | Path, *, device: str, today: date | None = None) -> dict[str, Any]:
    """Make `folder` the DJ's dj-library (see the module docstring); nothing is touched on a refusal."""
    if device not in DEVICES:
        raise SetupError(f"device must be one of {', '.join(DEVICES)}, got {device!r}", "usage")
    path = Path(folder).expanduser()
    if not path.is_absolute():
        raise SetupError(f"give the whole path of the folder, got {folder}.", "usage")
    cloud = synced(path)
    if cloud:
        raise SetupError(f"{path} is inside {cloud}, which syncs to the cloud: pick a folder outside it, "
                         f"for example {default_folder()}.", "synced")  # fmt: skip
    try:
        root = onboarding.library_root(path)
    except onboarding.OnboardingError as exc:
        raise SetupError(str(exc), "refused" if exc.reason == "refused" else "folder") from None
    if root.is_dir() and LibraryFolder(root).library_yaml.exists():
        try:
            meta = libfolder.load_meta(root)  # this tool's, and valid: used as it is
        except LibraryFolderError as exc:
            raise SetupError(f"{root} holds a library.yaml that is not this tool's: {exc}", "folder") from None
        return {"status": "existing", "library": str(root), "device": meta.get("device"), "created": [], "log": None}
    if root.is_dir() and _entries(root):
        raise SetupError(f"{root} already holds files: pick another folder (an empty one, or a new name).",
                         "not_empty")  # fmt: skip
    try:
        root.mkdir(parents=True, exist_ok=True)
        made = libfolder.scaffold(root, device=device, today=today)
        log = libfolder.append_log(root, "install", {"created": len(made.created)}, today=today)
    except (LibraryFolderError, OSError) as exc:
        raise SetupError(f"setting up {root} failed: {exc}", "folder") from None
    return {"status": "created", "library": str(root), "device": device, "created": list(made.created), "log": log}


def session_path(tools: Iterable[str]) -> str:
    """"engine" when the dj-librarian engine's dj_status tool is callable, else "xml"."""
    return "engine" if any(_ENGINE_STATUS.fullmatch(name) for name in tools) else "xml"


def set_handle(folder: str | Path, name: str | None, *, today: date | None = None) -> str:
    """The DJ's handle into library.yaml; empty or "skip" keeps "You" (they were asked)."""
    handle = libfolder.clean_dj_name(name) if name and name.strip().casefold() != "skip" else None
    meta = libfolder.update_meta(folder, today=today, dj_name=handle or "You")
    return str(meta["dj_name"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Make the DJ's dj-library folder (install step 6).")
    parser.add_argument("--folder", required=True, help="the folder to use or create (a whole path)")
    parser.add_argument("--device", required=True, choices=DEVICES, help="mac or windows (install step 1)")
    parser.add_argument("--today", type=date.fromisoformat, help="the date for library.yaml (YYYY-MM-DD)")
    args = parser.parse_args(argv)
    try:
        result = prepare(args.folder, device=args.device, today=args.today)
    except SetupError as exc:
        print(json.dumps({"error": str(exc), "reason": exc.reason}, ensure_ascii=False))
        return 2 if exc.reason in ("synced", "not_empty", "refused") else 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
