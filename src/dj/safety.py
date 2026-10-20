"""Safety core. Every DB access in this project goes through open_db().

See CLAUDE.md for the hard rules this module enforces.
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKUP_DIR = REPO_ROOT / "backups"
PLAYLIST_XML = "masterPlaylists6.xml"
PROCESS_NAME = "rekordbox.exe"  # Windows image name, as tasklist shows it
MAC_PROCESS_NAME = "rekordbox"  # macOS process name, as pgrep -x matches it
PGREP = "/usr/bin/pgrep"  # by absolute path, never from PATH
PGREP_TIMEOUT_S = 30
# Direct master.db writes are Windows power mode (CLAUDE.md rule 4, R-205). The macOS port
# (R-203) makes the process check work there; it must not open the write path with it.
DB_WRITE_PLATFORMS = ("win32",)
# `dj tidy apply/undo --apply` write audio files on Windows only in v0.1 (macOS is R-1303,
# v0.2): a working pgrep must not open tidy's write path on a Mac either.
TIDY_WRITE_PLATFORMS = ("win32",)


class SafetyError(RuntimeError):
    """A safety precondition failed. Nothing was written."""


class RekordboxRunningError(SafetyError):
    pass


class BackupError(SafetyError):
    pass


def find_master_db() -> Path:
    """Locate master.db: DJ_MASTER_DB override, pyrekordbox config, then the OS default
    (Windows: %APPDATA%/Pioneer/rekordbox, macOS: ~/Library/Pioneer/rekordbox; none elsewhere)."""
    override = os.environ.get("DJ_MASTER_DB")
    if override:
        path = Path(override)
    else:
        path = _db_path_from_pyrekordbox() or _db_path_default()
    if path is None or not path.is_file():
        raise FileNotFoundError(f"master.db not found (looked at: {path})")
    return path


def _db_path_from_pyrekordbox() -> Path | None:
    from pyrekordbox.config import get_config

    for section in ("rekordbox7", "rekordbox6"):
        try:
            db_path = get_config(section).get("db_path")
        except Exception:
            db_path = None
        if db_path and Path(db_path).is_file():
            return Path(db_path)
    return None


def _db_path_default() -> Path | None:
    """Where rekordbox keeps master.db by default on this OS; None where it does not run."""
    if sys.platform == "win32":
        return _db_path_from_appdata()
    if sys.platform == "darwin":
        return _db_path_from_mac_home()
    return None


def _db_path_from_appdata() -> Path | None:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return None
    return Path(appdata) / "Pioneer" / "rekordbox" / "master.db"


def _db_path_from_mac_home() -> Path:
    return Path.home() / "Library" / "Pioneer" / "rekordbox" / "master.db"


def process_name() -> str:
    """The rekordbox process name on this OS, for messages."""
    return MAC_PROCESS_NAME if sys.platform == "darwin" else PROCESS_NAME


def rekordbox_running() -> bool:
    """True if rekordbox runs: tasklist on Windows, pgrep on macOS.

    Any other OS, or a check that cannot answer, raises SafetyError: never report
    "not running" when the processes cannot actually be seen."""
    if sys.platform == "win32":
        return _running_windows()
    if sys.platform == "darwin":
        return _running_macos()
    raise SafetyError(
        f"rekordbox_running() needs Windows (tasklist) or macOS (pgrep); this is {sys.platform}."
    )


def _running_windows() -> bool:
    """tasklist as before; a tasklist that cannot run or fails is a SafetyError, like pgrep.

    tasklist writes its localized messages in the console's OEM code page, which is neither
    UTF-8 (the MCP server sets PYTHONUTF8=1) nor the ANSI code page: decode with errors="replace".
    The process name is ASCII, the same in every one of those code pages."""
    tasklist = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "tasklist.exe"
    try:
        result = subprocess.run(
            [str(tasklist), "/FI", f"IMAGENAME eq {PROCESS_NAME}", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            errors="replace",
            check=True,
        )
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise SafetyError(f"Cannot tell whether rekordbox runs: tasklist failed ({exc}).") from exc
    if not isinstance(result.stdout, str):
        raise SafetyError("Cannot tell whether rekordbox runs: tasklist failed (its output did not read).")
    return PROCESS_NAME.lower() in result.stdout.lower()


def _running_macos() -> bool:
    """pgrep exits 0 when a process matched, 1 when none did; anything else is an error."""
    try:
        result = subprocess.run(
            [PGREP, "-x", MAC_PROCESS_NAME],
            capture_output=True,
            text=True,
            errors="replace",
            check=False,
            timeout=PGREP_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise SafetyError(f"Cannot tell whether rekordbox runs: {PGREP} failed ({exc}).") from exc
    if result.returncode == 0:
        return True
    if result.returncode == 1:
        return False
    raise SafetyError(
        f"Cannot tell whether rekordbox runs: {PGREP} exited with {result.returncode}."
    )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass
class Backup:
    timestamp: str
    # source file -> backup copy
    files: dict[Path, Path] = field(default_factory=dict)
    # source file -> sha256 at backup time
    hashes: dict[Path, str] = field(default_factory=dict)

    @property
    def db_copy(self) -> Path:
        return next(copy for src, copy in self.files.items() if src.name == "master.db")

    def changed_sources(self) -> list[Path]:
        """Source files whose content no longer equals the backup."""
        return [
            src
            for src, digest in self.hashes.items()
            if not src.is_file() or sha256(src) != digest
        ]


def backup(db_path: Path, dest: Path | None = None) -> Backup:
    """Copy master.db (+ masterPlaylists6.xml, -wal, -shm) and verify every copy."""
    dest = dest or BACKUP_DIR
    dest.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    sources = {db_path: dest / f"master_{stamp}.db"}
    xml = db_path.parent / PLAYLIST_XML
    if xml.is_file():
        sources[xml] = dest / f"masterPlaylists6_{stamp}.xml"
    for suffix in ("-wal", "-shm"):
        side = db_path.with_name(db_path.name + suffix)
        if side.is_file():
            sources[side] = dest / f"master_{stamp}.db{suffix}"

    result = Backup(timestamp=stamp)
    for src, copy in sources.items():
        if copy.exists():
            raise BackupError(f"Backup target already exists: {copy}")
        shutil.copy2(src, copy)
        src_hash, copy_hash = sha256(src), sha256(copy)
        if src.stat().st_size != copy.stat().st_size or src_hash != copy_hash:
            raise BackupError(f"Backup copy differs from source: {src} -> {copy}")
        result.files[src] = copy
        result.hashes[src] = src_hash

    _verify_opens(result.db_copy)
    return result


def _verify_opens(db_copy: Path) -> None:
    """The copy must open and answer a query, otherwise it is not a backup."""
    try:
        db = _connect(db_copy, quiet=True)
        try:
            db.get_content().count()
        finally:
            db.close()
    except Exception as exc:
        raise BackupError(f"Backup copy does not open: {db_copy} ({exc})") from exc


def _connect(db_path: Path, quiet: bool = False) -> Any:
    from pyrekordbox import Rekordbox6Database

    log = logging.getLogger("pyrekordbox")
    level = log.level
    if quiet:
        log.setLevel(logging.ERROR)
    try:
        return Rekordbox6Database(path=db_path)
    finally:
        log.setLevel(level)


@contextmanager
def open_db(write: bool = False, db_path: Path | None = None) -> Iterator[Any]:
    """Open master.db and yield the pyrekordbox database.

    write=False: never commits; rolls back on exit.
    write=True:  Windows only (DB_WRITE_PLATFORMS) -> refuses if rekordbox runs ->
                 verified backup -> yield -> exactly one commit on clean exit.
                 Any exception -> rollback, no commit.
                 The db object is closed and discarded either way.
    """
    if write and sys.platform not in DB_WRITE_PLATFORMS:
        raise SafetyError(
            f"Direct master.db writes are Windows-only power mode; this is {sys.platform}. "
            "Nothing written."
        )
    path = db_path or find_master_db()
    bk: Backup | None = None
    if write:
        if rekordbox_running():
            raise RekordboxRunningError(f"{process_name()} is running. Close it, then retry.")
        bk = backup(path)

    db = _connect(path)
    try:
        yield db
        if write:
            if rekordbox_running():
                raise RekordboxRunningError(
                    f"{process_name()} was started during the run. Nothing committed."
                )
            db.commit()
        else:
            db.rollback()
    except BaseException as exc:
        try:
            db.rollback()
        except Exception:
            pass
        if bk is not None:
            changed = bk.changed_sources()
            if changed:
                names = ", ".join(p.name for p in changed)
                exc.add_note(
                    f"WARNING: changed on disk despite the failure: {names}. "
                    f"Restore from backups/*_{bk.timestamp}.* (see README)."
                )
            else:
                exc.add_note("Rolled back. master.db and the playlist XML are unchanged.")
        raise
    finally:
        try:
            db.close()
        except Exception:
            pass
