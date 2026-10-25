"""Read-only views of the rekordbox library."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from dj.match import Local
from dj.readers.common import streaming_service
from dj.rules import BPM_SCALE
from dj.tree import KIND_BY_ATTRIBUTE, ROOT_ID, alive, children_of, norm


class LibraryError(RuntimeError):
    pass


def to_local(content: Any) -> Local:
    return Local(
        content_id=str(content.ID),
        artist=content.ArtistName or "",
        title=content.Title or "",
        album=content.AlbumName or "",
        duration_s=int(content.Length or 0),
        isrc=(content.ISRC or "").strip(),
        bitrate=int(getattr(content, "BitRate", 0) or 0),
        path=getattr(content, "FolderPath", "") or "",
    )


def all_tracks(db: Any) -> list[Local]:
    return [to_local(c) for c in db.get_content().all() if alive(c)]


def row_service(content: Any) -> str:
    """The streaming service of a DjmdContent row (its FolderPath and ServiceID), "" for a local file."""
    return streaming_service(getattr(content, "FolderPath", None), getattr(content, "ServiceID", None))


def track_split(db: Any) -> dict[str, Any]:
    """The rows rekordbox's collection shows (not soft-deleted), split as `Library.track_split`
    does (Q-34): tracks = local + streaming, services = streamed rows per service."""
    services = Counter(row_service(c) for c in db.get_content().all() if alive(c))
    local = services.pop("", 0)
    streamed = sum(services.values())
    return {"tracks": local + streamed, "local": local, "streaming": streamed,
            "services": dict(sorted(services.items(), key=lambda kv: (-kv[1], kv[0])))}  # fmt: skip


def find_playlist(db: Any, path: str) -> Any:
    """'funk_base/funk_crate' -> the playlist row. Names match like `dj tree` does."""
    parent_id, row = ROOT_ID, None
    parts = [p.strip() for p in path.split("/") if p.strip()]
    if not parts:
        raise LibraryError("Empty playlist path.")
    for part in parts:
        rows = [r for r in children_of(db, parent_id) if norm(r.Name or "") == norm(part)]
        if not rows:
            raise LibraryError(f"No rekordbox playlist or folder {part!r} in {path!r}.")
        row = rows[0]
        parent_id = row.ID
    kind = KIND_BY_ATTRIBUTE.get(row.Attribute)
    if kind != "playlist":
        raise LibraryError(f"{path!r} is a {kind}, a crate must be a normal playlist.")
    return row


def crate_content_ids(playlist: Any) -> set[str]:
    return {str(s.ContentID) for s in playlist.Songs if alive(s)}


# -- the file-level view `dj tidy` needs (read-only, more columns than Local) --------------


def posix_key(path: str) -> str:
    """rekordbox stores FolderPath POSIX-style (`C:/Music/x.mp3`); compare paths this way."""
    return Path(path).as_posix().casefold() if path else ""


@dataclass(frozen=True)
class TrackInfo:
    """One DjmdContent row, as `dj tidy` reads it. Every field has a default-safe value."""

    content_id: str
    path: str  # FolderPath as stored
    file_name: str  # FileNameL
    artist: str
    title: str
    album: str
    duration_s: int
    isrc: str
    bitrate: int  # kbps as rekordbox stores it
    file_type: int  # pyrekordbox tables.FileType: MP3=1, M4A=4, FLAC=5, WAV=11, AIFF=12; 0 unknown
    bit_depth: int
    sample_rate: int
    file_size: int
    image_path: str  # "" when rekordbox has no artwork for the row
    analysed: int
    bpm_raw: int  # DjmdContent.BPM as stored (x100, see rules.BPM_SCALE)
    key: str
    genre: str
    label: str
    remixer: str
    release_year: int
    rating: int
    comment: str
    subtitle: str
    cue_count: int

    @property
    def posix_key(self) -> str:
        return posix_key(self.path)

    @property
    def bpm(self) -> float:
        return self.bpm_raw / BPM_SCALE if self.bpm_raw else 0.0

    @property
    def label_line(self) -> str:
        return f"{self.artist} - {self.title}" if self.artist else self.title


def _s(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _i(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def to_track_info(content: Any) -> TrackInfo:
    """Reads only; `getattr` defaults keep SimpleNamespace fakes and older schemas working.
    `Cues` is a lazy relationship: one extra query per row, the slow part of `--all`."""
    cues = getattr(content, "Cues", None) or []
    return TrackInfo(
        content_id=str(content.ID),
        path=_s(getattr(content, "FolderPath", "")),
        file_name=_s(getattr(content, "FileNameL", "")),
        artist=_s(getattr(content, "ArtistName", "")),
        title=_s(getattr(content, "Title", "")),
        album=_s(getattr(content, "AlbumName", "")),
        duration_s=_i(getattr(content, "Length", 0)),
        isrc=_s(getattr(content, "ISRC", "")),
        bitrate=_i(getattr(content, "BitRate", 0)),
        file_type=_i(getattr(content, "FileType", 0)),
        bit_depth=_i(getattr(content, "BitDepth", 0)),
        sample_rate=_i(getattr(content, "SampleRate", 0)),
        file_size=_i(getattr(content, "FileSize", 0)),
        image_path=_s(getattr(content, "ImagePath", "")),
        analysed=_i(getattr(content, "Analysed", 0)),
        bpm_raw=_i(getattr(content, "BPM", 0)),
        key=_s(getattr(content, "KeyName", "")),
        genre=_s(getattr(content, "GenreName", "")),
        label=_s(getattr(content, "LabelName", "")),
        remixer=_s(getattr(content, "RemixerName", "")),
        release_year=_i(getattr(content, "ReleaseYear", 0)),
        rating=_i(getattr(content, "Rating", 0)),
        comment=_s(getattr(content, "Commnt", "")),
        subtitle=_s(getattr(content, "Subtitle", "")),
        cue_count=sum(1 for c in cues if alive(c)),
    )


def track_infos(db: Any) -> list[TrackInfo]:
    return [to_track_info(c) for c in db.get_content().all() if alive(c)]


def crate_track_infos(db: Any, crate: str, infos: Iterable[TrackInfo] | None = None) -> tuple[Any, list[TrackInfo]]:
    """-> (playlist row, its alive tracks in playlist order). `infos` = an earlier track_infos(db)."""
    playlist = find_playlist(db, crate)
    wanted = crate_content_ids(playlist)
    source = track_infos(db) if infos is None else infos
    by_id = {t.content_id: t for t in source if t.content_id in wanted}
    order = sorted((s for s in playlist.Songs if alive(s)), key=lambda s: getattr(s, "TrackNo", 0) or 0)
    seen: set[str] = set()
    out = []
    for s in order:
        cid = str(s.ContentID)
        if cid in by_id and cid not in seen:
            seen.add(cid)
            out.append(by_id[cid])
    return playlist, out


def by_posix_path(infos: Iterable[TrackInfo]) -> dict[str, TrackInfo]:
    return {t.posix_key: t for t in infos if t.path}
