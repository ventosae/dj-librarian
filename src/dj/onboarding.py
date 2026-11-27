"""Which folder may become the DJ's dj-library (`dj.library_setup` asks at install).

    library_root(text, keep_out=...)   the folder, checked; too wide or too busy -> refused

Stdlib + PyYAML only (through dj.libfolder). Nothing here creates, reads or writes a file.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable

from dj import libfolder
from dj.libfolder import DIRS, FILES, LibraryFolder, LibraryFolderError

CROWDED = 10  # more entries of the DJ's own than this: not a folder to scaffold into
USER_FOLDERS = frozenset(
    {
        "desktop", "documents", "downloads", "music", "movies", "videos", "pictures",
        "onedrive", "dropbox", "icloud drive", "google drive",
    }
)  # fmt: skip

REASONS = ("folder", "usage", "refused")
NOTHING = "Nothing was created."


class OnboardingError(LibraryFolderError):
    """One line for the DJ, what kind of problem it is, and the exit code.

    `reason`: `folder` the folder cannot be set up as it is; `usage` a bad argument (the
    caller's mistake); `refused` (code 2) not a folder to set up a library in.
    """

    def __init__(self, message: str, reason: str, code: int = 1) -> None:
        super().__init__(message)
        if reason not in REASONS:
            raise ValueError(f"unknown reason {reason!r}")
        self.message = " ".join(message.split())
        self.reason = reason
        self.code = code


def _refused(message: str) -> OnboardingError:
    return OnboardingError(f"{message} {NOTHING}", "refused", code=2)


# -- the folder ----------------------------------------------------------------------------


def library_root(text: str | Path, *, keep_out: Iterable[str | Path] = ()) -> Path:
    """The library folder, resolved, or OnboardingError.

    Empty text is a usage error (it would mean the current folder). Refused (code 2): a drive
    root, the home folder or a folder holding it (`libfolder`'s own check); a folder inside or
    holding one of `keep_out` (the plugin); and, while the folder is not set up yet (no
    library.yaml), a well-known user folder (Desktop, Documents, Downloads, ...) or one that
    already holds more than CROWDED files and folders of the DJ's own. A file: `folder` error.
    """
    if not str(text).strip():
        raise OnboardingError("--library is empty: give the library folder.", "usage")
    try:
        resolved = Path(text).expanduser().resolve()
    except (OSError, RuntimeError) as exc:  # RuntimeError: `~` with no home folder known
        raise OnboardingError(f"Cannot use that folder: {exc}", "folder") from exc
    try:
        libfolder._library_root(resolved, "the library folder")  # one copy of the drive/home rule
    except LibraryFolderError:
        raise _refused(
            "That folder is a whole drive or the home folder, not a library folder."
        ) from None
    for other in keep_out:
        other = Path(other).resolve()
        if resolved.is_relative_to(other) or other.is_relative_to(resolved):
            raise _refused("That folder is the plugin's own folder or holds it.")
    if resolved.exists() and not resolved.is_dir():
        raise OnboardingError(f"{resolved.name} is a file, not a folder.", "folder")
    if resolved.is_dir() and not LibraryFolder(resolved).library_yaml.exists():
        if resolved.name.casefold() in USER_FOLDERS:
            raise _refused(f"{resolved.name} is a shared user folder, not a library folder.")
        own = _own_entries(resolved)
        if own > CROWDED:
            raise _refused(f"That folder already holds {own} files and folders of yours.")
    return resolved


def _own_entries(root: Path) -> int:
    """Entries that are not the tool's and not hidden."""
    tool = set(DIRS) | set(FILES)
    try:
        names = [entry.name for entry in os.scandir(root)]
    except OSError:
        return 0
    return sum(1 for name in names if name not in tool and not name.startswith("."))
