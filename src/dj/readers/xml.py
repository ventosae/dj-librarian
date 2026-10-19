"""rekordbox XML export (File > Export Collection in xml format) -> `dj.model.Library`.

Door 1: stdlib `xml.etree.ElementTree` only, so skill scripts can run it without the engine.
Attribute names are those of `pyrekordbox.rbxml` (Track.ATTRIBS; NODE Type 0 = folder,
1 = playlist; KeyType 0 = TrackID, 1 = Location); a test cross-checks a fixture against
`pyrekordbox.rbxml.RekordboxXml`.

What the export carries, field by field, is `FIELD_ATTRIBUTES` (+ `cue_count` from the
POSITION_MARK children). What it does not carry is `XML_FIELDS_MISSING` and `XML_NOTES`.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from dj.model import Library, LibraryError, PlaylistNode, Track
from dj.readers.common import (
    MAX_TREE_DEPTH,
    colour_name,
    kind_from,
    parse_date,
    posix_location,
    stars_from_rating,
    text,
    to_float,
    to_int,
)

# model field -> COLLECTION/TRACK attribute
FIELD_ATTRIBUTES = {
    "id": "TrackID",
    "artist": "Artist",
    "title": "Name",
    "album": "Album",
    "duration_s": "TotalTime",
    "bitrate": "BitRate",
    "location": "Location",
    "kind": "Kind",
    "sample_rate": "SampleRate",
    "file_size": "Size",
    "bpm": "AverageBpm",
    "key": "Tonality",
    "genre": "Genre",
    "label": "Label",
    "remixer": "Remixer",
    "year": "Year",
    "rating": "Rating",
    "colour": "Colour",
    "comment": "Comments",
    "date_added": "DateAdded",
    "play_count": "PlayCount",
}
XML_FIELDS_CARRIED = tuple(FIELD_ATTRIBUTES) + ("cue_count",)  # cue_count = POSITION_MARK count
# Model fields the export has no attribute for. They stay at their defaults in an XML Library.
XML_FIELDS_MISSING = ("isrc", "bit_depth", "my_tags", "has_artwork")
# Not model fields, but asked for by R-204 and missing from the export as well.
XML_NOTES = (
    "play history: no history lists in the export (only PlayCount and a LastPlayed date per track)",
    "smart playlists: no rules in the export (NODE Type is only 0 folder or 1 playlist)",
)

FOLDER, PLAYLIST = "0", "1"
KEY_TRACK_ID, KEY_LOCATION = "0", "1"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _track(el: ET.Element) -> Track:
    a = el.attrib.get
    track_id = text(a("TrackID"))
    if not track_id:
        raise LibraryError(f"A COLLECTION/TRACK has no TrackID (Name={a('Name')!r}).")
    location = posix_location(a("Location"))
    return Track(
        id=track_id,
        artist=text(a("Artist")),
        title=text(a("Name")),
        album=text(a("Album")),
        duration_s=to_int(a("TotalTime")),
        bitrate=to_int(a("BitRate")),
        location=location,
        kind=kind_from(a("Kind"), location),
        sample_rate=to_int(a("SampleRate")),
        file_size=to_int(a("Size")),
        bpm=to_float(a("AverageBpm")),
        key=text(a("Tonality")),
        genre=text(a("Genre")),
        label=text(a("Label")),
        remixer=text(a("Remixer")),
        year=to_int(a("Year")),
        rating=stars_from_rating(a("Rating")),
        colour=colour_name(a("Colour")),
        comment=text(a("Comments")),
        date_added=parse_date(a("DateAdded")),
        play_count=to_int(a("PlayCount")),
        cue_count=len(el.findall(".//POSITION_MARK")),
    )


def _location_resolver(tracks: dict[str, Track]) -> Callable[[str], str | None]:
    """KeyType=1 playlists name tracks by file: map a key to its TrackID (exact path first,
    then a case-insensitive match when exactly one track fits)."""
    exact: dict[str, str] = {}
    folded: dict[str, list[str]] = {}
    for track in tracks.values():
        if track.location:
            exact.setdefault(track.location, track.id)
            folded.setdefault(track.location.casefold(), []).append(track.id)

    def resolve(key: str) -> str | None:
        path = posix_location(key)
        if path in exact:
            return exact[path]
        hits = folded.get(path.casefold(), [])
        return hits[0] if len(hits) == 1 else None

    return resolve


def _node(el: ET.Element, node_id: str, resolve: Callable[[str], str | None], depth: int = 1) -> PlaylistNode:
    name = el.attrib.get("Name", "")
    if depth > MAX_TREE_DEPTH:
        raise LibraryError(f"The playlist tree is nested deeper than {MAX_TREE_DEPTH} levels (at {name!r}).")
    kind_attr = text(el.attrib.get("Type"))
    children = el.findall("NODE")
    if kind_attr == FOLDER or (kind_attr != PLAYLIST and children):
        kids = tuple(_node(child, f"{node_id}.{i}", resolve, depth + 1) for i, child in enumerate(children, 1))
        return PlaylistNode(id=node_id, kind="folder", name=name, children=kids)
    keys = [text(t.attrib.get("Key")) for t in el.findall("TRACK")]
    if text(el.attrib.get("KeyType")) == KEY_LOCATION:
        ids = tuple(i for i in (resolve(k) for k in keys) if i)
    else:
        ids = tuple(k for k in keys if k)
    return PlaylistNode(id=node_id, kind="playlist", name=name, track_ids=ids)


def read_xml(path: str | Path, *, read_at: str | None = None) -> Library:
    """Parse a rekordbox collection XML. Raises LibraryError for anything that is not one.
    Node ids are positions in the tree ("1", "1.2", "1.2.1"): stable for the same file."""
    source = Path(path)
    try:
        root = ET.parse(source).getroot()
    except (ET.ParseError, LookupError, ValueError) as exc:  # LookupError: unknown encoding
        raise LibraryError(f"{source.name}: not readable XML ({exc}).") from exc
    except OSError as exc:
        raise LibraryError(f"{source}: cannot read the file ({exc.strerror or exc}).") from exc
    if root.tag != "DJ_PLAYLISTS":
        raise LibraryError(f"{source.name}: not a rekordbox XML (root element is <{root.tag}>).")
    collection = root.find("COLLECTION")
    if collection is None:
        raise LibraryError(f"{source.name}: no COLLECTION element; export the whole collection.")

    tracks: dict[str, Track] = {}
    for el in collection.findall("TRACK"):
        track = _track(el)
        if track.id in tracks:
            raise LibraryError(f"{source.name}: TrackID {track.id!r} appears twice in COLLECTION.")
        tracks[track.id] = track

    roots: tuple[PlaylistNode, ...] = ()
    playlists = root.find("PLAYLISTS")
    top = playlists.find("NODE") if playlists is not None else None  # the ROOT node
    if top is not None:
        resolve = _location_resolver(tracks)
        roots = tuple(_node(child, str(i), resolve) for i, child in enumerate(top.findall("NODE"), 1))

    product = root.find("PRODUCT")
    version = None
    if product is not None and text(product.attrib.get("Name")).lower().startswith("rekordbox"):
        version = text(product.attrib.get("Version")) or None
    return Library(
        source="xml",
        source_path=source.as_posix(),
        rekordbox_version=version,
        read_at=read_at or _now(),
        tracks=tracks,
        roots=roots,
    )
