"""master.db -> `dj.model.Library`, read from a snapshot copy only (R-202, R-201 read path).

Door 2 (pyrekordbox, through `dj.safety.open_db`). The live master.db is copied byte for byte
(with `-wal`, `-shm` and masterPlaylists6.xml when present) into a temporary folder; only the
copy is opened, read-only, and the folder is removed afterwards, also on error. Works while
rekordbox runs: nothing is written and the live file is never opened by SQLite. If rekordbox
writes while the files are copied, the copy is taken again (`snapshot`).

What master.db does not give this reader is `DB_NOTES`:
- Smart playlists: master.db stores their rules (`SmartList`), not their tracks; rekordbox works
  the tracks out each time it shows the list. Smart nodes come back with the raw rules and no
  `track_ids`, so `Library.orphans()` and `counts()["entries"]` on a db Library leave smart
  membership out: a track that only a smart playlist reaches counts as an orphan.
- Play history (DjmdHistory) is not read yet; the model has no history field (R-204 open part).
"""

from __future__ import annotations

import logging
import re
import shutil
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

from dj import safety
from dj.library import to_track_info
from dj.model import Library, LibraryError, PlaylistNode, Track
from dj.readers.common import (
    BPM_SCALE,
    MAX_TREE_DEPTH,
    colour_name,
    kind_from,
    parse_date,
    posix_location,
    stars_from_rating,
    text,
    to_int,
)
from dj.tree import KIND_BY_ATTRIBUTE, ROOT_ID, alive, children_of

log = logging.getLogger(__name__)

# pyrekordbox tables.FileType (pinned by tests/test_contract.py)
FILE_TYPES = {1: "mp3", 4: "m4a", 5: "flac", 11: "wav", 12: "aiff"}
# model field -> DjmdContent column it comes from. Every model field has a column; what
# master.db holds beyond the model (history) or not per track (smart members) is DB_NOTES.
FIELD_COLUMNS = {
    "id": "ID", "artist": "ArtistName", "title": "Title", "album": "AlbumName", "duration_s": "Length",
    "isrc": "ISRC", "bitrate": "BitRate", "location": "FolderPath", "kind": "FileType",
    "bit_depth": "BitDepth", "sample_rate": "SampleRate", "file_size": "FileSize", "bpm": "BPM",
    "key": "KeyName", "genre": "GenreName", "label": "LabelName", "remixer": "RemixerName",
    "year": "ReleaseYear", "rating": "Rating", "colour": "ColorName", "comment": "Commnt",
    "date_added": "StockDate", "play_count": "DJPlayCount", "my_tags": "MyTags", "cue_count": "Cues",
    "has_artwork": "ImagePath",
}  # fmt: skip
DB_NOTES = (
    "smart playlists: master.db stores their rules, not their tracks (rekordbox works the tracks "
    "out when it shows the list); here they hold no tracks, so a track only a smart playlist "
    "reaches counts as an orphan and smart playlists add nothing to entries",
    "play history: master.db has history lists (DjmdHistory); this reader does not read them yet",
)
SIDE_SUFFIXES = ("-wal", "-shm")
SNAPSHOT_TRIES = 3
SNAPSHOT_PAUSE_S = 0.5
_PRODUCT_VERSION = re.compile(r'<PRODUCT[^>]*\bVersion="([^"]+)"')
_HEX_RUN = re.compile(r"[0-9A-Fa-f]{32,}")


def _stamp(path: Path) -> tuple[int, int] | None:
    try:
        st = path.stat()
    except FileNotFoundError:
        return None
    return (st.st_size, st.st_mtime_ns)


def snapshot(master_db: Path, dest: Path, *, tries: int = SNAPSHOT_TRIES, pause_s: float = SNAPSHOT_PAUSE_S) -> Path:
    """Copy master.db and its side files into `dest`; return the copy of master.db.

    master.db and `-wal` must not change while they are copied (size and mtime before and
    after): a checkpoint between the two copies would pair an old database with a newer WAL.
    If they changed, everything is copied again, up to `tries` times. `-shm` (the WAL index)
    is not checked: SQLite rebuilds it from the WAL when the first connection opens the copy.
    """
    checked = [master_db, master_db.with_name(master_db.name + "-wal")]
    sides = [master_db.with_name(master_db.name + s) for s in SIDE_SUFFIXES]
    copy = dest / master_db.name
    for attempt in range(1, tries + 1):
        before = [_stamp(p) for p in checked]
        shutil.copy2(master_db, copy)
        for side in sides + [master_db.parent / safety.PLAYLIST_XML]:
            try:
                shutil.copy2(side, dest / side.name)
            except FileNotFoundError:
                # absent, or rekordbox checkpointed it away; drop a copy from an earlier attempt
                (dest / side.name).unlink(missing_ok=True)
        if [_stamp(p) for p in checked] == before:
            return copy
        log.info("master.db changed while it was copied (attempt %d of %d); copying again", attempt, tries)
        if attempt < tries:
            time.sleep(pause_s)
    raise LibraryError(
        f"master.db kept changing while it was copied ({tries} tries): rekordbox is writing. "
        "Try again in a moment."
    )


def rekordbox_version(folder: Path) -> str | None:
    """rekordbox stamps its version into masterPlaylists6.xml (same rule as `dj status`)."""
    xml = folder / safety.PLAYLIST_XML
    if not xml.is_file():
        return None
    match = _PRODUCT_VERSION.search(xml.read_text(encoding="utf-8", errors="replace"))
    return match.group(1) if match else None


def _my_tags(content: Any) -> tuple[str, ...]:
    """My Tag names. Prefer the DjmdSongMyTag rows, dropping soft-deleted links and links to a
    soft-deleted DjmdMyTag; else MyTagNames (fakes only: real rows always have MyTags)."""
    rows = getattr(content, "MyTags", None)  # a lazy relationship on real rows: one query each
    if rows is not None:
        names = [
            getattr(r, "MyTagName", None)
            for r in rows
            if alive(r) and not getattr(getattr(r, "MyTag", None), "rb_local_deleted", 0)
        ]
    else:
        names = list(getattr(content, "MyTagNames", None) or [])
    return tuple(dict.fromkeys(text(n) for n in names if text(n)))


def to_track(content: Any) -> Track:
    """One DjmdContent row -> Track: `library.to_track_info` plus the columns it does not read."""
    info = to_track_info(content)
    location = posix_location(info.path)
    return Track(
        id=info.content_id,
        artist=info.artist,
        title=info.title,
        album=info.album,
        duration_s=info.duration_s,
        isrc=info.isrc,
        bitrate=info.bitrate,
        location=location,
        kind=kind_from(FILE_TYPES.get(info.file_type, ""), location),
        bit_depth=info.bit_depth,
        sample_rate=info.sample_rate,
        file_size=info.file_size,
        bpm=info.bpm_raw / BPM_SCALE if info.bpm_raw else 0.0,
        key=info.key,
        genre=info.genre,
        label=info.label,
        remixer=info.remixer,
        year=info.release_year,
        rating=stars_from_rating(info.rating),
        colour=colour_name(getattr(content, "ColorName", None)),
        comment=info.comment,
        date_added=parse_date(getattr(content, "StockDate", None)),
        play_count=to_int(getattr(content, "DJPlayCount", None)),
        my_tags=_my_tags(content),
        cue_count=info.cue_count,
        has_artwork=bool(info.image_path),
    )


def _song_ids(row: Any) -> tuple[str, ...]:
    songs = [s for s in (getattr(row, "Songs", None) or []) if alive(s)]
    songs.sort(key=lambda s: getattr(s, "TrackNo", 0) or 0)
    return tuple(str(s.ContentID) for s in songs)


def _nodes(db: Any, parent_id: str = ROOT_ID, depth: int = 1) -> tuple[PlaylistNode, ...]:
    if depth > MAX_TREE_DEPTH:
        raise LibraryError(f"The playlist tree is nested deeper than {MAX_TREE_DEPTH} levels (under {parent_id!r}).")
    out = []
    for row in children_of(db, parent_id):
        kind = KIND_BY_ATTRIBUTE.get(row.Attribute)
        node_id, name = str(row.ID), row.Name or ""
        if kind == "folder":
            out.append(PlaylistNode(node_id, "folder", name, children=_nodes(db, row.ID, depth + 1)))
        elif kind == "playlist":
            out.append(PlaylistNode(node_id, "playlist", name, track_ids=_song_ids(row)))
        elif kind == "smart":
            # members are not stored (DB_NOTES): rules only, no track_ids
            rules = ({"raw": getattr(row, "SmartList", None) or ""},)
            out.append(PlaylistNode(node_id, "smart", name, rules=rules))
        else:
            log.warning("skipped playlist row %s (%r): unknown Attribute %r", node_id, name, row.Attribute)
    return tuple(out)


def _engine_of(db: Any) -> Any:
    """pyrekordbox keeps its SQLAlchemy engine on the instance. Read it without attribute
    magic, so test fakes that refuse unknown attributes stay quiet."""
    return vars(db).get("engine") if hasattr(db, "__dict__") else None


def _short_reason(exc: BaseException) -> str:
    """'TypeName: first line of the message', at most 200 characters, long hex runs (a key)
    blanked. SQLAlchemy messages carry the whole SELECT after the first line."""
    message = str(exc.args[0]) if exc.args else str(exc)
    first = (message.strip().splitlines() or [""])[0]
    first = _HEX_RUN.sub("<hex>", first)[:200]
    return f"{type(exc).__name__}: {first}" if first else type(exc).__name__


def read_db(master_db: str | Path | None = None, *, read_at: str | None = None) -> Library:
    """Read master.db (found via `safety.find_master_db()` when None) from a snapshot copy.
    Anything that goes wrong comes back as one short LibraryError."""
    try:
        live = Path(master_db) if master_db else safety.find_master_db()
    except FileNotFoundError as exc:
        raise LibraryError(str(exc)) from exc
    if not live.is_file():
        raise LibraryError(f"master.db not found: {live}")

    with tempfile.TemporaryDirectory(prefix="dj-snapshot-") as tmp:
        try:
            copy = snapshot(live, Path(tmp))
        except OSError as exc:
            raise LibraryError(f"Could not copy master.db for a snapshot ({exc}).") from exc
        log.info("reading master.db snapshot %s (the live file is not opened)", copy,
                 extra={"snapshot": copy.as_posix()})  # fmt: skip
        engine = None
        try:
            with safety.open_db(write=False, db_path=copy) as db:
                engine = _engine_of(db)
                tracks: dict[str, Track] = {}
                for content in db.get_content().all():
                    if alive(content):
                        track = to_track(content)
                        tracks[track.id] = track
                roots = _nodes(db)
        except LibraryError:
            raise
        except Exception as exc:  # torn copy, wrong key, sqlcipher3 missing, ...
            raise LibraryError(f"The master.db snapshot could not be read ({_short_reason(exc)}).") from exc
        finally:
            if engine is not None:
                try:
                    engine.dispose()  # pooled SQLite handles would block removing the folder on Windows
                except Exception as exc:
                    log.warning("could not close the snapshot connection (%s)", _short_reason(exc))
        version = rekordbox_version(Path(tmp))

    return Library(
        source="db",
        source_path=live.as_posix(),
        rekordbox_version=version,
        read_at=read_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        tracks=tracks,
        roots=roots,
    )


def tracks_by_id(db: Any, ids: Iterable[str]) -> dict[str, Track]:
    """The rows of `ids` that rekordbox has not soft-deleted, as Tracks (`to_track`: location,
    BPM, key ...), for an XML the DJ imports (`dj apply --xml`, `dj copy --xml`). Reads the
    content rows as `read_db` does; an id the library lacks is left out."""
    wanted = {str(i) for i in ids}
    out: dict[str, Track] = {}
    if not wanted:
        return out
    for content in db.get_content().all():
        if alive(content) and str(content.ID) in wanted:
            out[str(content.ID)] = to_track(content)
    return out


@contextmanager
def open_snapshot(master_db: Path | None = None) -> Iterator[Any]:
    """The pyrekordbox database of a snapshot copy of `master_db` (found via
    `safety.find_master_db()` when None), read-only (R-202), for a caller that needs the rows
    themselves: `dj status` and every read-only pass of the CLI (dry-runs, match, plan, push,
    tidy audit / plan / dupes, the tree print after a write). Same copy, log line and clean-up as
    `read_db`; the live file is never opened. No master.db, or a copy that fails -> LibraryError."""
    if master_db is None:
        try:
            master_db = safety.find_master_db()
        except FileNotFoundError as exc:
            raise LibraryError(str(exc)) from exc
    with tempfile.TemporaryDirectory(prefix="dj-snapshot-") as tmp:
        try:
            copy = snapshot(master_db, Path(tmp))
        except OSError as exc:
            raise LibraryError(f"Could not copy master.db for a snapshot ({exc}).") from exc
        log.info("reading master.db snapshot %s (the live file is not opened)", copy,
                 extra={"snapshot": copy.as_posix()})  # fmt: skip
        engine = None
        try:
            with safety.open_db(write=False, db_path=copy) as db:
                engine = _engine_of(db)
                yield db
        finally:
            if engine is not None:
                try:
                    engine.dispose()  # pooled SQLite handles would block removing the folder on Windows
                except Exception as exc:
                    log.warning("could not close the snapshot connection (%s)", _short_reason(exc))
