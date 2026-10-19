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
PROCESS_NAME = "rekordbox.exe"


class SafetyError(RuntimeError):
    """A safety precondition failed. Nothing was written."""


class RekordboxRunningError(SafetyError):
    pass


class BackupError(SafetyError):
    pass


def find_master_db() -> Path:
    """Locate master.db: DJ_MASTER_DB override, pyrekordbox config, then %APPDATA%."""
    override = os.environ.get("DJ_MASTER_DB")
    if override:
        path = Path(override)
    else:
        path = _db_path_from_pyrekordbox() or _db_path_from_appdata()
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


def _db_path_from_appdata() -> Path | None:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return None
    return Path(appdata) / "Pioneer" / "rekordbox" / "master.db"


def rekordbox_running() -> bool:
    """True if rekordbox.exe is running, per tasklist. Windows only."""
    if sys.platform != "win32":
        # Never report "not running" when we cannot actually see Windows processes.
        raise SafetyError("rekordbox_running() needs native Windows (tasklist).")
    tasklist = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "tasklist.exe"
    result = subprocess.run(
        [str(tasklist), "/FI", f"IMAGENAME eq {PROCESS_NAME}", "/FO", "CSV", "/NH"],
        capture_output=True,
        text=True,
        check=True,
    )
    return PROCESS_NAME.lower() in result.stdout.lower()


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
    write=True:  refuses if rekordbox runs -> verified backup -> yield ->
                 exactly one commit on clean exit. Any exception -> rollback, no commit.
                 The db object is closed and discarded either way.
    """
    path = db_path or find_master_db()
    bk: Backup | None = None
    if write:
        if rekordbox_running():
            raise RekordboxRunningError("rekordbox.exe is running. Close it, then retry.")
        bk = backup(path)

    db = _connect(path)
    try:
        yield db
        if write:
            if rekordbox_running():
                raise RekordboxRunningError(
                    "rekordbox.exe was started during the run. Nothing committed."
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
