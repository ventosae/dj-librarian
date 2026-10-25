"""Automatic, verified copies of the rekordbox database in the dj-library folder (W-37, D-31, R-206).

    take_backup(library_dir)   -> BackupResult   (`dj backup`, MCP `dj_backup`)
    list_backups(library_dir)  -> dict           (`dj backup --list`)

A backup is `master.db`, `master.db-wal` and `master.db-shm` when present, and `masterPlaylists6.xml`,
copied in one pass by `dj.readers.db.snapshot` (the database and its WAL are copied again if rekordbox
wrote meanwhile) into a scratch folder, then byte for byte into
`<dj-library>/backups/rekordbox-<YYYY-MM-DD-HHMM>/`, so a retry never removes a file there. Analysis
files and artwork stay out: rekordbox's own File > Library > Backup Library covers them.

- Dedupe: when master.db and its -wal hash the same as the newest verified backup's, nothing is
  copied and the result says `unchanged since <date>`. (The WAL counts too: while rekordbox runs,
  recent changes live there, not in master.db.)
- Verify: the copy is opened through the read path (`dj.readers.db.open_snapshot`, a scratch copy of
  the backup, so the backup's own bytes stay exactly as hashed): `PRAGMA quick_check` must say ok
  and djmdContent must answer a count. `manifest.json` records the date, the rekordbox version, every
  file with its size and sha256, the track counts (Q-34 split), `rekordbox_running` and `verified`.
- `RESTORE.md`: the steps for this OS with the real paths. No automatic restore in v0.1.
- Nothing is deleted, ever (hard rule 1): every backup is kept and dedupe bounds the growth. An
  unverified copy is kept too, flagged in its manifest and by `NOT-VERIFIED.md`, and the result asks
  the DJ to close rekordbox and run it again.
- Writes only under `<dj-library>/backups/` (its own `.gitignore` keeps the copies out of git), never
  into the Pioneer folder. Refuses a folder that is not a dj-library, or one inside a cloud-synced
  folder (`library_setup.synced`, install step 3's rule): a database copy has no place in the cloud.

The one write tool without a preview id (D-31): it never touches rekordbox, and it only adds files.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from dj import libfolder, library, safety
from dj.library_setup import synced
from dj.readers import db as db_reader

BACKUPS = "backups"
PREFIX = "rekordbox-"
MANIFEST = "manifest.json"
RESTORE = "RESTORE.md"
NOT_VERIFIED = "NOT-VERIFIED.md"
DB = "master.db"
DEDUPE_FILES = (DB, DB + "-wal")  # what decides "unchanged": the database and its WAL
FILE_ORDER = (DB, DB + "-wal", DB + "-shm", safety.PLAYLIST_XML)
GITIGNORE = "# Copies of your rekordbox database (dj backup). They hold paths from this computer.\n*\n"
ALSO = "Analysis files and artwork are not in here: rekordbox's File > Library > Backup Library covers them."


class BackupError(RuntimeError):
    """No backup was taken. `reason`: synced, not_library, pioneer, no_db, failed."""

    def __init__(self, message: str, reason: str) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass
class BackupResult:
    status: str  # created | unchanged | unverified
    folder: Path  # the backup this run made, or the unchanged one it matched
    size: int  # bytes of that backup's files
    verified: bool
    manifest: dict[str, Any] = field(default_factory=dict)
    since: str | None = None  # unchanged: the matched backup's date
    reason: str | None = None  # unverified: why
    shown: str = ""  # the folder as the DJ sees it: relative to the dj-library (backups/rekordbox-...)

    @property
    def line(self) -> str:
        """The one line the DJ sees."""
        where = self.shown or str(self.folder)
        if self.status == "unchanged":
            return f"Backup: unchanged since {self.since} · {where}"
        if self.verified:
            return f"Backup: {where} · {size_text(self.size)} · verified"
        return (f"Backup: {where} · {size_text(self.size)} · NOT verified ({self.reason}). "
                "Close rekordbox, then run the backup again.")  # fmt: skip

    def as_json(self) -> dict[str, Any]:
        return {"status": self.status, "line": self.line, "folder": str(self.folder), "size": self.size,
                "verified": self.verified, "since": self.since, "reason": self.reason,
                "tracks": self.manifest.get("tracks"), "rekordbox": self.manifest.get("rekordbox")}  # fmt: skip


def size_text(n: int) -> str:
    for unit, scale in (("GB", 1e9), ("MB", 1e6), ("KB", 1e3)):
        if n >= scale:
            return f"{n / scale:.1f} {unit}"
    return f"{n} B"


def _when(stamp: str) -> str:
    """'2026-10-25T14:32:05+11:00' -> '2026-10-25 14:32'."""
    return stamp[:16].replace("T", " ")


# -- the library folder -------------------------------------------------------------------------


def backups_root(library_dir: str | Path, pioneer: Path | None = None) -> Path:
    """`<dj-library>/backups`, after the refusals in the module docstring."""
    root = Path(library_dir).expanduser()
    if not root.is_absolute():
        raise BackupError(f"give the whole path of the dj-library folder, got {library_dir}.", "not_library")
    cloud = synced(root.resolve())
    if cloud:
        raise BackupError(f"{root} is inside {cloud}, which syncs to the cloud: a copy of your rekordbox "
                          "database does not belong there. Move the dj-library out of it first.", "synced")  # fmt: skip
    try:
        libfolder.load_meta(root)
    except (libfolder.LibraryFolderError, OSError) as exc:
        raise BackupError(f"{root} is not a dj-library folder (library.yaml): {exc}", "not_library") from None
    if pioneer is not None and root.resolve().is_relative_to(pioneer.resolve()):
        raise BackupError(f"{root} is inside rekordbox's own folder {pioneer}: nothing is written there.", "pioneer")
    return root / BACKUPS


def _new_folder(backups: Path, now: datetime) -> Path:
    """backups/rekordbox-<YYYY-MM-DD-HHMM>, -2, -3 ... when that minute is taken. Create-only."""
    backups.mkdir(parents=True, exist_ok=True)
    libfolder.write_new_text(backups / ".gitignore", GITIGNORE)
    base = f"{PREFIX}{now:%Y-%m-%d-%H%M}"
    for n in range(1, 1000):
        folder = backups / (base if n == 1 else f"{base}-{n}")
        try:
            folder.mkdir()
        except FileExistsError:
            continue
        return folder
    raise BackupError(f"{backups} has no free name for {base}.", "failed")


# -- manifests ------------------------------------------------------------------------------------


def _read_manifest(folder: Path) -> dict[str, Any] | None:
    try:
        data = json.loads((folder / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _backups(backups: Path) -> list[tuple[Path, dict[str, Any] | None]]:
    """Every backup folder with its manifest (None when it has none), oldest first."""
    if not backups.is_dir():
        return []
    found = [(p, _read_manifest(p)) for p in backups.iterdir() if p.is_dir() and p.name.startswith(PREFIX)]
    return sorted(found, key=lambda item: (str((item[1] or {}).get("date", "")), item[0].name))


def _hashes(manifest: dict[str, Any]) -> dict[str, str]:
    files = manifest.get("files") if isinstance(manifest.get("files"), list) else []
    return {f["name"]: f.get("sha256", "") for f in files if isinstance(f, dict) and f.get("name") in DEDUPE_FILES}


def _live_hashes(db_path: Path) -> dict[str, str]:
    out = {}
    for name in DEDUPE_FILES:
        path = db_path.with_name(name)
        if path.is_file():
            out[name] = safety.sha256(path)
    return out


def _file_entries(folder: Path) -> list[dict[str, Any]]:
    return [{"name": name, "size": (folder / name).stat().st_size, "sha256": safety.sha256(folder / name)}
            for name in FILE_ORDER if (folder / name).is_file()]  # fmt: skip


def _engine_version() -> str:
    from importlib import metadata

    try:
        return metadata.version("dj-librarian")
    except metadata.PackageNotFoundError:
        return "unknown"


def _running() -> bool | None:
    try:
        return safety.rekordbox_running()
    except safety.SafetyError:
        return None  # this OS cannot tell; a read never depends on it (R-201)


# -- verify ---------------------------------------------------------------------------------------


def quick_check(db: Any) -> str:
    """SQLite's `PRAGMA quick_check` on the open database: "ok", or its first findings."""
    from sqlalchemy import text

    rows = [str(r) for r in db.session.execute(text("PRAGMA quick_check")).scalars().all()]
    return "ok" if rows == ["ok"] else "; ".join(rows[:3]) or "no answer"


def _verify(folder: Path) -> tuple[str | None, dict[str, Any]]:
    """(None when the copy is sound, else why it is not; the track counts it read)."""
    try:
        with db_reader.open_snapshot(folder / DB) as db:
            check = quick_check(db)
            rows = db.get_content().count()
            tracks = {"rows": rows} | library.track_split(db)
    except Exception as exc:  # a torn copy, a wrong key, a missing sqlcipher3: not a backup
        return f"it does not open: {db_reader._short_reason(exc)}", {}
    if check != "ok":
        return f"quick_check: {check}", tracks
    return None, tracks


# -- RESTORE.md -----------------------------------------------------------------------------------


def restore_text(manifest: dict[str, Any], platform: str = sys.platform) -> str:
    """The restore steps for this OS, with the folder the backup was taken from."""
    mac = platform == "darwin"
    pioneer = manifest.get("taken_from", "")
    names = [f["name"] for f in manifest.get("files", [])]
    t = manifest.get("tracks") or {}
    counted = (f"{t.get('tracks')} tracks ({t.get('local')} local, {t.get('streaming')} streaming)"
               if t.get("tracks") is not None else "the track count it had")  # fmt: skip
    close = "rekordbox > Quit rekordbox (Cmd+Q)" if mac else "File > Exit"
    find = ("In Finder: Go > Go to Folder..., paste ~/Library/Pioneer/rekordbox" if mac
            else "In File Explorer: paste %APPDATA%\\Pioneer\\rekordbox into the address bar")  # fmt: skip
    lines = [
        "# Restore rekordbox from this backup",
        "",
        f"Taken {_when(manifest.get('date', ''))} from rekordbox {manifest.get('rekordbox') or '(version unknown)'}, "
        f"verified: {counted}.",
        "Restoring puts your collection and playlists back to that moment. What you did in rekordbox since is lost.",
        "",
        f"1. Close rekordbox ({close}).",
        f"2. Open rekordbox's database folder: `{pioneer}`. {find}.",
        f"3. Move {', '.join(f'`{n}`' for n in FILE_ORDER)} out of that folder into a new folder of their own. "
        "Keep them: they are your library as it is now.",
        "4. Copy these files from this folder into rekordbox's database folder:",
        *[f"   - `{name}`" for name in names],
        f"5. Open rekordbox. Check it shows {counted}.",
        "",
        ALSO,
        "",
    ]
    return "\n".join(lines)


def _not_verified_text(reason: str) -> str:
    return (f"# This copy did NOT verify\n\n{reason}\n\nDo not restore from it. Close rekordbox, then run the "
            "backup again (`dj backup`, or say \"back up my library\").\n")  # fmt: skip


# -- take / list ----------------------------------------------------------------------------------


def _copy(live: Path, folder: Path) -> str | None:
    """The settled snapshot (scratch folder) into the new backup `folder`; why it failed, or None."""
    try:
        with tempfile.TemporaryDirectory(prefix="dj-backup-") as scratch:
            db_reader.snapshot(live, Path(scratch))
            for name in FILE_ORDER:
                if (Path(scratch) / name).is_file():
                    shutil.copyfile(Path(scratch) / name, folder / name)
    except (OSError, db_reader.LibraryError) as exc:
        return f"the copy failed: {exc}"
    return None


def take_backup(library_dir: str | Path, *, db_path: Path | None = None, now: datetime | None = None,
                platform: str = sys.platform) -> BackupResult:  # fmt: skip
    """Copy, verify and describe the rekordbox database (see the module docstring)."""
    try:
        live = Path(db_path) if db_path else safety.find_master_db()
    except FileNotFoundError as exc:
        raise BackupError(str(exc), "no_db") from None
    if not live.is_file():
        raise BackupError(f"master.db not found: {live}", "no_db")
    backups = backups_root(library_dir, live.parent)
    now = now or datetime.now().astimezone()

    hashes = _live_hashes(live)
    verified = [(p, m) for p, m in _backups(backups) if m and m.get("verified") is True]
    if verified and _hashes(verified[-1][1]) == hashes:
        folder, manifest = verified[-1]
        size = sum(int(f.get("size", 0)) for f in manifest.get("files", []))
        return BackupResult("unchanged", folder, size, True, manifest, since=_when(str(manifest.get("date", ""))),
                            shown=libfolder.relative(backups.parent, folder))  # fmt: skip

    folder = _new_folder(backups, now)
    reason = _copy(live, folder)
    tracks: dict[str, Any] = {}
    if reason is None:
        reason, tracks = _verify(folder)
    manifest = {
        "tool": "dj-librarian", "version": _engine_version(), "date": now.isoformat(timespec="seconds"),
        "taken_from": str(live.parent), "rekordbox": db_reader.rekordbox_version(folder),
        "rekordbox_running": _running(), "files": _file_entries(folder), "tracks": tracks,
        "verified": reason is None, "reason": reason,
    }  # fmt: skip
    libfolder.write_new_text(folder / MANIFEST, json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    if reason is None:
        libfolder.write_new_text(folder / RESTORE, restore_text(manifest, platform))
    else:
        libfolder.write_new_text(folder / NOT_VERIFIED, _not_verified_text(reason))
    size = sum(f["size"] for f in manifest["files"])
    return BackupResult("created" if reason is None else "unverified", folder, size, reason is None, manifest,
                        reason=reason, shown=libfolder.relative(backups.parent, folder))  # fmt: skip


def list_backups(library_dir: str | Path) -> dict[str, Any]:
    """Every backup, newest first: date, verified, size, tracks; and the totals."""
    rows = []
    for folder, manifest in reversed(_backups(backups_root(library_dir))):
        m = manifest or {}
        files = m.get("files") if isinstance(m.get("files"), list) else []
        size = sum(int(f.get("size", 0)) for f in files if isinstance(f, dict))
        if not files:  # no manifest: measure what is there
            size = sum(p.stat().st_size for p in folder.iterdir() if p.is_file())
        rows.append({"folder": str(folder), "date": _when(str(m.get("date", ""))) or folder.name[len(PREFIX):],
                     "verified": m.get("verified") is True, "size": size,
                     "tracks": (m.get("tracks") or {}).get("tracks")})  # fmt: skip
    total = sum(r["size"] for r in rows)
    verified = sum(r["verified"] for r in rows)
    line = f"{len(rows)} backups · {verified} verified · {size_text(total)} in all" if rows else "No backups yet."
    return {"count": len(rows), "verified": verified, "total_size": total, "line": line, "backups": rows}


def list_lines(listing: dict[str, Any]) -> list[str]:
    out = [listing["line"]]
    for r in listing["backups"]:
        mark = "verified" if r["verified"] else "NOT verified"
        out.append(f"  {r['date']}  {mark:<12}  {size_text(r['size']):>9}  {r['folder']}")
    return out


def default_library() -> Path:
    """The configured dj-library (DJ_LIBRARY, else the remembered folder)."""
    return libfolder.configured_root()
