"""One library model, fed by two readers (R-204): the rekordbox XML export and master.db.

Door 1: stdlib only. No pyrekordbox, rapidfuzz, httpx, typer or mcp in here, because skill
scripts import this in Cowork's sandbox. Readers live in `dj.readers.*`.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Any, Iterable, Iterator

TRACK_KINDS = ("mp3", "m4a", "flac", "wav", "aiff", "unknown")
NODE_KINDS = ("folder", "playlist", "smart")
SOURCES = ("xml", "db")
COUNT_KEYS = ("tracks", "folders", "playlists", "smart", "orphans", "entries")


class LibraryError(ValueError):
    """The library source is unreadable or a lookup in it failed."""


def id_sort_key(track_id: str) -> tuple[int, int, str]:
    """Numeric ids in numeric order ("2" before "10"), any other id after them, by text."""
    text = str(track_id)
    return (0, int(text), text) if text.isdigit() else (1, 0, text)


@dataclass(frozen=True)
class Track:
    """One track. Every field has a safe default; a reader fills what its source carries."""

    id: str = ""
    artist: str = ""
    title: str = ""
    album: str = ""
    duration_s: int = 0
    isrc: str = ""
    bitrate: int = 0  # kbps
    location: str = ""  # POSIX path, decoded ("D:/Music/a b.mp3", "/Users/x/a.mp3")
    kind: str = "unknown"  # one of TRACK_KINDS
    bit_depth: int = 0
    sample_rate: int = 0  # Hz
    file_size: int = 0  # bytes
    bpm: float = 0.0  # real BPM (master.db stores x100; readers convert)
    key: str = ""
    genre: str = ""
    label: str = ""
    remixer: str = ""
    year: int = 0
    rating: int = 0  # 0-5 stars
    colour: str = ""  # rekordbox colour name ("Pink" ... "Purple"), or the raw value if unknown
    comment: str = ""
    date_added: date | None = None
    play_count: int = 0
    my_tags: tuple[str, ...] = ()
    cue_count: int = 0
    has_artwork: bool = False

    def __post_init__(self) -> None:
        if self.kind not in TRACK_KINDS:
            raise LibraryError(f"track {self.id!r}: kind {self.kind!r} is not one of {TRACK_KINDS}")

    @property
    def label_line(self) -> str:
        """'Artist - Title', or the title alone when the artist is empty."""
        return f"{self.artist} - {self.title}" if self.artist else self.title


@dataclass(frozen=True)
class PlaylistNode:
    """A folder, playlist or smart playlist. `path` is filled by `Library` (names from the top)."""

    id: str
    kind: str  # one of NODE_KINDS
    name: str
    children: tuple["PlaylistNode", ...] = ()
    track_ids: tuple[str, ...] = ()  # playlist order kept; may name ids the collection lacks;
    # empty for a smart playlist read from master.db (members are not stored there)
    rules: tuple[dict, ...] = ()  # smart only, raw form (e.g. {"raw": "<NODE ...>"})
    path: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.kind not in NODE_KINDS:
            raise LibraryError(f"node {self.name!r}: kind {self.kind!r} is not one of {NODE_KINDS}")
        if self.kind != "folder" and self.children:
            raise LibraryError(f"node {self.name!r}: only a folder can hold children")
        if self.kind == "folder" and self.track_ids:
            raise LibraryError(f"node {self.name!r}: a folder holds no tracks")

    @property
    def path_str(self) -> str:
        return "/".join(self.path)


def fill_paths(nodes: Iterable[PlaylistNode], prefix: tuple[str, ...] = ()) -> tuple[PlaylistNode, ...]:
    """Copies of `nodes` with `path` set from the top of the tree down."""
    out = []
    for node in nodes:
        path = prefix + (node.name,)
        out.append(replace(node, path=path, children=fill_paths(node.children, path)))
    return tuple(out)


def _split(path: str | tuple[str, ...] | list[str]) -> tuple[str, ...]:
    if isinstance(path, str):
        parts = tuple(p.strip() for p in path.split("/"))
    else:
        parts = tuple(str(p).strip() for p in path)
    parts = tuple(p for p in parts if p)
    if not parts:
        raise LibraryError("Empty playlist path.")
    return parts


@dataclass(frozen=True)
class Library:
    """Tracks by id plus the playlist tree. The rekordbox ROOT node is not a root here."""

    source: str  # "xml" | "db"
    source_path: str = ""
    rekordbox_version: str | None = None
    read_at: str = ""  # ISO timestamp
    tracks: dict[str, Track] = field(default_factory=dict)  # local files only (Q-34)
    roots: tuple[PlaylistNode, ...] = ()
    # Rows rekordbox streams (Spotify, Beatport Streaming, ...): id -> service. The readers keep them
    # out of `tracks` and out of every playlist's `track_ids`; they are counted, never analysed.
    streaming: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.source not in SOURCES:
            raise LibraryError(f"source {self.source!r} is not one of {SOURCES}")
        object.__setattr__(self, "roots", fill_paths(self.roots))

    # -- the tree -----------------------------------------------------------------------

    def walk(self) -> list[PlaylistNode]:
        """Every node, depth-first, in tree order (a folder before its children)."""

        def visit(nodes: tuple[PlaylistNode, ...]) -> Iterator[PlaylistNode]:
            for node in nodes:
                yield node
                yield from visit(node.children)

        return list(visit(self.roots))

    def playlists(self) -> list[PlaylistNode]:
        """Playlists and smart playlists, flat, in tree order."""
        return [n for n in self.walk() if n.kind in ("playlist", "smart")]

    def folders(self) -> list[PlaylistNode]:
        return [n for n in self.walk() if n.kind == "folder"]

    def node_at(self, path: str | tuple[str, ...]) -> PlaylistNode:
        """'Folder/Playlist' or ('Folder', 'Playlist'). Exact name first, then case-insensitive.
        A name that itself holds '/' needs the tuple form. rekordbox allows siblings with the
        same name: when more than one sibling matches at the tier used (exact, or
        case-insensitive when nothing matches exactly), the path is ambiguous -> LibraryError."""
        parts = _split(path)
        level, node = self.roots, None
        for depth, part in enumerate(parts):
            hits = [n for n in level if n.name == part] or [
                n for n in level if n.name.strip().casefold() == part.casefold()
            ]
            where = repr("/".join(parts[:depth])) if depth else "the top level"
            if not hits:
                raise LibraryError(f"No playlist or folder {part!r} in {'/'.join(parts)!r}.")
            if len(hits) > 1:
                names = ", ".join(repr(n.name) for n in hits)
                raise LibraryError(f"Ambiguous: {len(hits)} nodes in {where} match {part!r} ({names}).")
            node = hits[0]
            level = node.children
        assert node is not None
        return node

    def tracks_in(self, path: str | tuple[str, ...]) -> list[Track]:
        """The tracks of one playlist, in playlist order. Ids the collection lacks are skipped."""
        node = self.node_at(path)
        if node.kind == "folder":
            raise LibraryError(f"{node.path_str!r} is a folder; give a playlist.")
        return [self.tracks[i] for i in node.track_ids if i in self.tracks]

    def orphans(self) -> list[Track]:
        """Tracks no playlist and no smart playlist lists in its `track_ids`, sorted by id
        (numeric ids numerically). Smart membership counts only where the source lists it:
        master.db stores smart rules, not members (`dj.readers.db.DB_NOTES`), so on a db
        Library a track that only a smart playlist reaches is an orphan."""
        used = {i for node in self.playlists() for i in node.track_ids}
        return sorted((t for i, t in self.tracks.items() if i not in used), key=lambda t: id_sort_key(t.id))

    def counts(self) -> dict[str, int]:
        """tracks; folders; playlists (plain only); smart; orphans; entries (playlist rows,
        summed over plain and smart playlists, repeats counted; smart rows only where the
        source lists them, see `orphans`)."""
        nodes = self.walk()
        return {
            "tracks": len(self.tracks),
            "folders": sum(n.kind == "folder" for n in nodes),
            "playlists": sum(n.kind == "playlist" for n in nodes),
            "smart": sum(n.kind == "smart" for n in nodes),
            "orphans": len(self.orphans()),
            "entries": sum(len(n.track_ids) for n in nodes if n.kind != "folder"),
        }

    def track_split(self) -> dict[str, Any]:
        """What rekordbox's collection shows, split (Q-34): tracks = local + streaming; services =
        streamed rows per service, biggest first (ties by name)."""
        services = Counter(self.streaming.values())
        return {
            "tracks": len(self.tracks) + len(self.streaming),
            "local": len(self.tracks),
            "streaming": len(self.streaming),
            "services": dict(sorted(services.items(), key=lambda kv: (-kv[1], kv[0]))),
        }
