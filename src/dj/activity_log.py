"""The tool's own `log.md` lines for the dj CLI's writing commands (R-904).

The tool appends the line, never Claude: one line per command run that wrote something, none for
a dry-run or a refusal. The line is `dj.libfolder.append_log`'s:
`YYYY-MM-DD HH:MM <action> -> <n> <key>, <n> <key>; <file>`.

Where it goes:
- the configured dj-library folder (`dj.libfolder.configured_root`) when that folder is set up:
  a `library.yaml` that `validate_meta` accepts. The DJ reads one log there.
- else `log.md` at the top of the repo (gitignored), the maintainer's workflow before a library
  folder exists. In the desktop extension (W-34) the repo is the install folder: there it is the
  dj-library folder the settings name, set up or not, or `~/.dj-librarian` without a usable one.

The file in the line is relative to the folder of that log.md; a file in the repo (plans/,
reports/, state/) logged into the library folder's log.md is written relative to the repo; any
other file is named by its file name only. No absolute path is ever written (R-905).

Writing the line can fail (a sync client holds log.md open). The write it records is done by
then, so `log_write` returns the reason instead of raising; the caller shows it as a warning.

Stdlib + PyYAML only (`dj.libfolder`), like the other Door-1 modules.

Adopting it in a new writing command (W-23, W-25): after the write succeeded,

    logged = activity_log.log_write("wishlist shop <crate>", {"links": n}, path)
    payload["log"] = logged.line            # None when it could not be written
    if logged.warning: echo it on stderr

"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Mapping

from dj import hostenv, libfolder

# Where log.md goes while no dj-library is set up: the repo in a clone; in the desktop extension
# the dj-library folder the settings name even before it is set up (the DJ reads log.md there; a
# later scaffold keeps it), or ~/.dj-librarian without a usable one (dj.hostenv.home_root), never
# the install folder. Read at call time: tests point it at a temporary folder (tests/conftest.py).
REPO_DIR = hostenv.home_root()


@dataclass(frozen=True)
class Logged:
    """What log_write did: the line appended (None when it could not be written), the log.md it
    went to, and the reason it failed."""

    line: str | None
    log: Path
    warning: str | None = None


# What reading the library settings can raise: a refused folder, an unreadable file, text that is
# not UTF-8 (UnicodeDecodeError is a ValueError).
SETTINGS_ERRORS = (libfolder.LibraryFolderError, OSError, ValueError)


def library_root() -> Path | None:
    """The configured dj-library folder, or None when none can be used (a refused DJ_LIBRARY, an
    unreadable state/library-path.txt)."""
    try:
        return libfolder.configured_root()
    except SETTINGS_ERRORS:
        return None


def is_library(root: Path | None) -> bool:
    """A set-up dj-library: the folder holds a library.yaml that validates."""
    try:
        if root is None or not (root / "library.yaml").is_file():
            return False
        return not libfolder.validate_meta(libfolder.load_meta(root))
    except SETTINGS_ERRORS:
        return False


def log_root() -> Path:
    """The folder whose log.md gets the line: the library folder when set up, else the repo."""
    root = library_root()
    return root if is_library(root) else Path(REPO_DIR)


def _inside(path: Path, root: Path) -> bool:
    try:
        return path.is_relative_to(root.resolve())
    except (OSError, ValueError):
        return False


def file_text(root: Path, file: str | Path | None) -> str | None:
    """The file as the line names it: relative to `root`, else to the repo, else its name."""
    if file is None or not str(file).strip():
        return None
    path = Path(file)
    try:
        path = path.resolve()  # a relative path is the CLI's, from its working folder
    except OSError:
        return path.name or None
    for base in (Path(root), Path(REPO_DIR)):
        if _inside(path, base):
            return path.relative_to(base.resolve()).as_posix() or None
    return path.name or None


def one_line(text: str) -> str:
    """A playlist or crate name inside an action: its own line breaks become spaces."""
    return " ".join(str(text).split())


def log_write(
    action: str,
    counts: Mapping[str, int] | None = None,
    file: str | Path | None = None,
    *,
    now: datetime | None = None,
    today: date | None = None,
) -> Logged:
    """Append one log.md line for a write that is done (R-904). Never raises: the write it records
    is done by then, so whatever goes wrong here (finding the folder, an unreadable library.yaml,
    a held log.md) comes back as `warning`, with `line` None."""
    log = Path(REPO_DIR) / "log.md"
    try:
        root = log_root()
        log = root / "log.md"
        line = libfolder.append_log(
            root, one_line(action), dict(counts or {}) or None, file_text(root, file), now=now, today=today
        )
    except Exception as exc:  # noqa: BLE001 - the log must never undo the report of a finished write
        return Logged(None, log, f"log.md line not written ({type(exc).__name__}: {exc}); the write itself is done.")
    return Logged(line, log)
