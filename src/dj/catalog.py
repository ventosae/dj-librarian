"""The track catalog (D-37): the DJ's library as plain SQLite and CSV, for questions asked in SQL.

    <dj-library>/catalog/catalog.db   tables tracks, playlists, playlist_tracks, notes, meta
    <dj-library>/catalog/tracks.csv   a header row and one row per track (the tracks table)

    ensure(folder, lib=None)          -> {db, csv, tracks, rebuilt}: build when master.db changed, else keep
    build(folder, lib, *, db_sha256)  -> the same, rebuilt
    query(folder, sql, page=1)        -> {counts: {rows, page, pages}, columns, rows}: one SELECT, read-only
    note(folder, track_id, field, value, source="dj") -> one dated row in `notes`

The catalog is built from a `dj.model.Library` read from the master.db snapshot (`dj.readers.db.read_db`);
this module never opens master.db and never writes to rekordbox, Spotify or audio files. It writes only
inside `<dj-library>/catalog/` (its own `.gitignore` keeps it out of git: it holds file paths) and one
log.md line per rebuild and per note (R-904).

Tables:
- `tracks`: one column per `dj.model.Track` field (my_tags joined with ", ", date_added as YYYY-MM-DD,
  has_artwork 0/1, never NULL), plus `camelot` (the Camelot code of `key`, "" when it is not a key) and
  `local` (1 = a local file, 0 = a row rekordbox streams: Q-34, `readers.common.streaming_service`).
  A streamed row carries its id only: the readers keep the rest out of the Library.
- `playlists` (id, name, path, kind, parent): every folder, playlist and smart playlist in tree order;
  `path` joins the names from the top with "/", `parent` is the parent's id ("" at the top).
- `playlist_tracks` (playlist_id, position, track_id): the playlists' tracks in order, position from 1.
  A smart playlist has none: master.db stores its rules, not its tracks.
- `notes` (track_id, field, value, source, date): the DJ's own notes. A rebuild never touches them.
- `meta` (key, value): db_sha256 and wal_sha256 (master.db and its -wal as `dj.backup` hashes them),
  built_at, engine_version.

A rebuild replaces tracks, playlists and playlist_tracks inside one transaction; tracks.csv is written
first, so a failed rebuild leaves the stored sha256 old and the next call builds again. `ensure` keeps
the catalog while master.db and its -wal hash as stored (and the engine version is the same).
"""

from __future__ import annotations

import csv
import io
import json
import sqlite3
import time
from contextlib import closing
from dataclasses import fields
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

from dj import libfolder
from dj.analysis.common import library_folder
from dj.crate import camelot
from dj.libfolder import LibraryFolder, LibraryFolderError
from dj.model import Library, LibraryError, PlaylistNode, Track, id_sort_key
from dj.readers.common import streaming_service

DIR = "catalog"
DB = f"{DIR}/catalog.db"
CSV = f"{DIR}/tracks.csv"
GITIGNORE = "# dj-librarian: the catalog holds the paths of music files on this computer. Not for git.\n*\n"
PAGE_ROWS = 200  # rows of a query result in one page, at most
PAGE_CHARS = 16_000  # a page ends early here (compact JSON), so a result stays under the tool-result limit
QUERY_SECONDS = 20  # a query that runs longer is stopped
NOTE_FIELD_MAX, NOTE_VALUE_MAX = 60, 2000

TRACK_FIELDS = tuple(f.name for f in fields(Track))
COLUMNS = TRACK_FIELDS + ("camelot", "local")
_SQL_TYPES = {"int": "INTEGER", "bool": "INTEGER", "float": "REAL"}  # every other field is TEXT
_TRACK_COLUMNS = [f"{f.name} {_SQL_TYPES.get(str(f.type), 'TEXT')}" for f in fields(Track)]
REBUILT = ("playlist_tracks", "playlists", "tracks")  # dropped and made again by every build; never notes
SCHEMA = (
    f"CREATE TABLE tracks ({', '.join(_TRACK_COLUMNS)}, camelot TEXT, local INTEGER, PRIMARY KEY (id))",
    "CREATE TABLE playlists (id TEXT, name TEXT, path TEXT, kind TEXT, parent TEXT)",
    "CREATE TABLE playlist_tracks (playlist_id TEXT, position INTEGER, track_id TEXT)",
    "CREATE INDEX playlist_tracks_by_playlist ON playlist_tracks (playlist_id, position)",
    "CREATE INDEX playlist_tracks_by_track ON playlist_tracks (track_id)",
    "CREATE TABLE IF NOT EXISTS notes (track_id TEXT, field TEXT, value TEXT, source TEXT, date TEXT)",
    "CREATE INDEX IF NOT EXISTS notes_by_track ON notes (track_id)",
    "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)",
)
ONLY_SELECT = "Only one SELECT statement is allowed: the catalog is read-only (a note goes through dj_note)."
_ALLOWED = (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION)


class CatalogError(LibraryError):
    """The catalog cannot be built, read or written as asked. The message is one line."""


def _engine_version() -> str:
    from dj import (
        backup,  # the engine's (pyrekordbox behind it): only when a catalog is built or checked
    )

    return backup._engine_version()


def stamp(master_db: str | Path) -> dict[str, str]:
    """What decides "unchanged": master.db's sha256 and its -wal's, as `dj.backup` computes them
    (while rekordbox runs, recent changes sit in the WAL), and the engine version."""
    from dj import backup

    hashes = backup._live_hashes(Path(master_db))
    if backup.DB not in hashes:
        raise CatalogError(f"master.db not found: {master_db}")
    return {"db_sha256": hashes[backup.DB], "wal_sha256": hashes.get(backup.DB + "-wal", ""),
            "engine_version": _engine_version()}  # fmt: skip


# -- rows ---------------------------------------------------------------------------------------


def _cell(value: Any) -> Any:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, tuple):
        return ", ".join(str(v) for v in value)
    if isinstance(value, date):
        return value.isoformat()
    return "" if value is None else value


def _track_row(track: Track, local: int) -> tuple:
    return (*(_cell(getattr(track, name)) for name in TRACK_FIELDS), camelot(track.key) or "", local)


def track_rows(lib: Library) -> list[tuple]:
    """One row per track in COLUMNS order, by id: the local files, then the streamed rows (id only)."""
    local = sorted(lib.tracks.values(), key=lambda t: id_sort_key(t.id))
    rows = [_track_row(t, 0 if streaming_service(t.location) else 1) for t in local]
    return rows + [_track_row(Track(id=tid), 0) for tid in sorted(lib.streaming, key=id_sort_key)]


def playlist_rows(lib: Library) -> tuple[list[tuple], list[tuple]]:
    """(playlists rows, playlist_tracks rows), both in tree order."""
    nodes: list[tuple] = []
    entries: list[tuple] = []

    def visit(children: Iterable[PlaylistNode], parent: str) -> None:
        for node in children:
            nodes.append((node.id, node.name, node.path_str, node.kind, parent))
            entries.extend((node.id, position, tid) for position, tid in enumerate(node.track_ids, 1))
            visit(node.children, node.id)

    visit(lib.roots, "")
    return nodes, entries


# -- build --------------------------------------------------------------------------------------


def _marks(n: int) -> str:
    return ", ".join("?" * n)


def _result(tracks: int, rebuilt: bool, log: str | None = None) -> dict[str, Any]:
    return {"db": DB, "csv": CSV, "tracks": tracks, "rebuilt": rebuilt, "log": log}


def build(folder: LibraryFolder | str | Path, lib: Library, *, db_sha256: str, wal_sha256: str = "",
          engine_version: str | None = None, today: date | None = None) -> dict[str, Any]:  # fmt: skip
    """Write catalog/tracks.csv, then replace tracks, playlists and playlist_tracks in catalog/catalog.db
    in one transaction (notes stay as they are) and store `db_sha256` in meta. One log.md line.
    Returns {db, csv, tracks, rebuilt: True, log}; the paths are relative to the library folder."""
    folder = library_folder(folder)
    (folder.root / DIR).mkdir(exist_ok=True)
    libfolder.write_new_text(folder.root / DIR / ".gitignore", GITIGNORE)
    tracks = track_rows(lib)
    playlists, entries = playlist_rows(lib)
    meta = {"db_sha256": db_sha256, "wal_sha256": wal_sha256,
            "built_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "engine_version": engine_version if engine_version is not None else _engine_version()}  # fmt: skip

    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(COLUMNS)
    writer.writerows(tracks)
    libfolder.write_text(folder.root / CSV, "﻿" + out.getvalue())  # the BOM: Excel reads it as UTF-8

    try:
        with closing(sqlite3.connect(folder.root / DB, isolation_level=None)) as con:
            con.execute("BEGIN IMMEDIATE")
            try:
                for table in REBUILT:
                    con.execute(f"DROP TABLE IF EXISTS {table}")
                for statement in SCHEMA:
                    con.execute(statement)
                con.executemany(f"INSERT INTO tracks VALUES ({_marks(len(COLUMNS))})", tracks)
                con.executemany(f"INSERT INTO playlists VALUES ({_marks(5)})", playlists)
                con.executemany(f"INSERT INTO playlist_tracks VALUES ({_marks(3)})", entries)
                con.executemany("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", meta.items())
                con.execute("COMMIT")
            except BaseException:
                con.execute("ROLLBACK")
                raise
    except sqlite3.Error as exc:
        raise CatalogError(f"{DB} could not be written ({exc}). The catalog is as it was.") from exc
    counts = {"tracks": len(tracks), "playlists": len(playlists)}
    return _result(len(tracks), True, _log(folder, "catalog", counts, today))


def _log(folder: LibraryFolder, action: str, counts: dict[str, int], today: date | None) -> str | None:
    try:
        return libfolder.append_log(folder.root, action, counts, file=DB, today=today)
    except (LibraryFolderError, OSError):
        return None  # the catalog is written; the log line is the extra


def _stored(folder: LibraryFolder) -> tuple[dict[str, str], int]:
    """(the meta rows, the number of tracks) of the catalog that is there; ({}, 0) when there is none."""
    if not (folder.root / DB).is_file() or not (folder.root / CSV).is_file():
        return {}, 0
    try:
        with closing(_read_only(folder.root / DB)) as con:
            meta = dict(con.execute("SELECT key, value FROM meta").fetchall())
            return meta, con.execute("SELECT count(*) FROM tracks").fetchone()[0]
    except sqlite3.Error:
        return {}, 0


def ensure(folder: LibraryFolder | str | Path, lib: Library | None = None, *,
           today: date | None = None) -> dict[str, Any]:  # fmt: skip
    """The catalog, never stale: kept when master.db (and its -wal) hash as stored, else built again.
    `lib`: a Library just read from the master.db snapshot (the analysis passes its own); without one
    a snapshot is read only when a rebuild is due. No master.db on this computer: the catalog as it
    was last built. Returns {db, csv, tracks, rebuilt, log}."""
    from dj import safety  # master.db is found and hashed here, never opened

    folder = library_folder(folder)
    if lib is not None and lib.source != "db":
        raise CatalogError("The catalog is built from master.db, not from an export.")
    meta, tracks = _stored(folder)
    try:
        live = Path(lib.source_path) if lib is not None else safety.find_master_db()
        now = stamp(live)
    except (FileNotFoundError, CatalogError) as exc:
        if meta:
            return _result(tracks, False)
        raise CatalogError(f"No catalog yet and no rekordbox database to build it from ({exc}).") from None
    if meta and all(meta.get(key) == value for key, value in now.items()):
        return _result(tracks, False)
    if lib is None:
        from dj.readers.db import read_db

        lib = read_db(live)
    return build(folder, lib, today=today, **now)


# -- query (read-only) ----------------------------------------------------------------------------


def _read_only(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, isolation_level=None)
    con.execute("PRAGMA query_only = ON")
    return con


def _select_only(action: int, *_args: Any) -> int:
    return sqlite3.SQLITE_OK if action in _ALLOWED else sqlite3.SQLITE_DENY


def one_select(sql: Any) -> str:
    """`sql` as one statement that starts with SELECT (or WITH), else CatalogError. What it does is
    checked again when it runs: an authorizer that allows only SELECT, READ and FUNCTION."""
    text = sql.strip().rstrip(";").strip() if isinstance(sql, str) else ""
    first = text.split(None, 1)[0].upper() if text else "nothing"
    if first not in ("SELECT", "WITH"):
        raise CatalogError(f"{ONLY_SELECT} Got {first[:20]}.")
    return text


def _json_cell(value: Any) -> Any:
    return value.hex() if isinstance(value, bytes) else value


def query(folder: LibraryFolder | str | Path, sql: str, page: int = 1) -> dict[str, Any]:
    """Run one SELECT on catalog.db, opened read-only (URI mode=ro, PRAGMA query_only, the authorizer).
    Counts first: {counts: {rows, page, pages}, columns, rows}; `rows` are lists in `columns` order,
    PAGE_ROWS a page at most (a page ends early at PAGE_CHARS characters). A page past the end is
    empty. Anything that is not exactly one SELECT -> CatalogError, one line why."""
    statement = one_select(sql)
    if isinstance(page, bool) or not isinstance(page, int) or page < 1:
        raise CatalogError(f"page must be a whole number from 1, got {page!r}.")
    path = library_folder(folder).root / DB
    if not path.is_file():
        raise CatalogError(f"{DB} not found: run the analysis first (dj_library_analyze).")
    deadline = time.monotonic() + QUERY_SECONDS
    rows: list[list[Any]] = []
    total, at, in_page, used = 0, 1, 0, 0
    try:
        with closing(_read_only(path)) as con:
            con.set_authorizer(_select_only)
            con.set_progress_handler(lambda: time.monotonic() > deadline, 20_000)
            cursor = con.execute(statement)
            columns = [column[0] for column in cursor.description or ()]
            for record in cursor:
                row = [_json_cell(value) for value in record]
                size = len(json.dumps(row, ensure_ascii=False, separators=(",", ":"))) + 1
                if in_page and (in_page >= PAGE_ROWS or used + size > PAGE_CHARS):
                    at, in_page, used = at + 1, 0, 0
                if at == page:
                    rows.append(row)
                total, in_page, used = total + 1, in_page + 1, used + size
    except (sqlite3.Error, sqlite3.Warning) as exc:
        why = " ".join(str(exc).split())
        if "interrupted" in why:
            raise CatalogError(f"The query ran longer than {QUERY_SECONDS} s and was stopped: add a WHERE or a LIMIT.") from None
        if "not authorized" in why or "one statement" in why:
            raise CatalogError(f"{ONLY_SELECT} sqlite: {why}") from None
        raise CatalogError(f"The query did not run: {why}") from None
    return {"counts": {"rows": total, "page": page, "pages": at}, "columns": columns, "rows": rows}


# -- notes ----------------------------------------------------------------------------------------


def _one_line(value: Any, what: str, limit: int) -> str:
    text = " ".join(value.split()) if isinstance(value, str) else ""
    if not text or len(text) > limit:
        raise CatalogError(f"{what} must be 1 to {limit} characters of text. Nothing was written.")
    return text


def note(folder: LibraryFolder | str | Path, track_id: Any, field: str, value: str, source: str = "dj", *,
         today: date | None = None) -> dict[str, Any]:  # fmt: skip
    """Append one row to `notes` with today's date: (track_id, field, value, source, date). An id the
    catalog's tracks do not hold -> CatalogError, nothing written. One log.md line. Notes are only ever
    added: to change one, add a newer row (the latest date wins for whoever reads them)."""
    folder = library_folder(folder)
    tid = _one_line(str(track_id) if isinstance(track_id, int) else track_id, "track_id", 40)
    row = {"track_id": tid, "field": _one_line(field, "field", NOTE_FIELD_MAX),
           "value": _one_line(value, "value", NOTE_VALUE_MAX), "source": _one_line(source, "source", NOTE_FIELD_MAX),
           "date": (today or date.today()).isoformat()}  # fmt: skip
    if not (folder.root / DB).is_file():
        raise CatalogError(f"{DB} not found: run the analysis first (dj_library_analyze). Nothing was written.")
    try:
        with closing(sqlite3.connect(folder.root / DB)) as con, con:
            found = con.execute("SELECT artist, title FROM tracks WHERE id = ?", (tid,)).fetchone()
            if found is None:
                raise CatalogError(f"No track with id {tid} in the catalog: look the id up with dj_query. "
                                   "Nothing was written.")  # fmt: skip
            con.execute(f"INSERT INTO notes (track_id, field, value, source, date) VALUES ({_marks(5)})",
                        tuple(row.values()))  # fmt: skip
            count = con.execute("SELECT count(*) FROM notes WHERE track_id = ?", (tid,)).fetchone()[0]
    except sqlite3.Error as exc:
        raise CatalogError(f"The note was not written ({exc}).") from exc
    artist, title = found
    return {"counts": {"notes": count}, "note": row, "track": f"{artist} - {title}" if artist else title,
            "db": DB, "log": _log(folder, f"note {tid}", {"notes": count}, today)}  # fmt: skip
