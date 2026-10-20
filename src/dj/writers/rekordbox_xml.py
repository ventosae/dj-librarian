"""A tree (`dj.treeschema.TreeDoc`) + the library -> a rekordbox XML the DJ imports (R-502, R-503).

Door 1 core: stdlib `xml.etree.ElementTree` (+ PyYAML through `dj.treeschema`). No pyrekordbox:
a test reads the output back with `pyrekordbox.rbxml.RekordboxXml`.

The file, as rekordbox's own export writes it (pyrekordbox 0.4.4 schema):

    <DJ_PLAYLISTS Version="1.0.0">
      <PRODUCT Name="dj-librarian" Version="<product_version>" Company="dj-librarian"/>
      <COLLECTION Entries="<n>">            only the tracks a playlist below references
        <TRACK TrackID=".." Name=".." ... Location="file://localhost/..."/>
      </COLLECTION>
      <PLAYLISTS>
        <NODE Type="0" Name="ROOT" Count="<children>">
          <NODE Type="0" Name="<folder>" Count="<children>"> ...
          <NODE Name="<playlist>" Type="1" KeyType="0" Entries="<n>"><TRACK Key="<TrackID>"/>...

Rules:
- A playlist holds the tracks of its `from` playlists (existing playlists of the library), in
  order, each track once (the first time it appears wins). An unknown `from` path -> BuildError.
- Track attributes are written only when the library has a value (0 / empty = left out).
  Rating: stars -> 0/51/102/153/204/255. AverageBpm: two decimals. Colour: the rekordbox code.
- TrackID: the library id when it is a positive whole number written without leading zeros
  (rekordbox's own TrackIDs, master.db content ids). Any other id gets a number above the
  largest such id in the whole library, in library id order (`track_id_map`): the same library
  always maps the same way, whatever the proposal.
- Smart playlists cannot be expressed in an XML import: left out (`XmlPlan.manual`).
- A track without a file location cannot be imported: left out (`XmlPlan.unplaced`).
- `only` (a set of node paths) limits the tree to those nodes; callers pass the CREATE nodes and
  their ancestor folders.
- `vetoed` (library ids, from `taste/vetoes.md` "never propose") are left out of every playlist
  a `from` fills (R-702); `XmlPlan.vetoed` lists the ones that were left out.
- `plan_lists` / `build_lists_xml` take explicit track lists instead of a tree (Crate me): each
  playlist path with its ids in order; the folders on the paths are made once, in order. The
  COLLECTION / TRACK encoding is the same.
- `write_xml` never replaces a file: a taken name becomes `<name>-2.xml`, `-3` ...
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Sequence

from dj.libfolder import write_new_text
from dj.model import Library, LibraryError, Track, id_sort_key
from dj.readers.common import COLOUR_CODES, RATING_STEP, location_url
from dj.treeschema import TreeDoc, TreeNode

PRODUCT_NAME = "dj-librarian"
FORMAT_VERSION = "1.0.0"
KIND_TEXT = {"mp3": "MP3 File", "m4a": "M4A File", "flac": "FLAC File", "wav": "WAV File", "aiff": "AIFF File"}
MAX_NUMBERED = 10_000  # `<name>-N.xml` tries before giving up

_POSITIVE_ID = re.compile(r"^[1-9][0-9]*$")
_HEX_COLOUR = re.compile(r"^0x[0-9A-Fa-f]{6}$")
# Characters XML 1.0 cannot carry (control characters other than tab, LF, CR).
_NOT_XML = re.compile("[^\x09\x0a\x0d\x20-\ud7ff\ue000-\ufffd\U00010000-\U0010ffff]")

NodePath = tuple[str, ...]


class BuildError(ValueError):
    """The proposal cannot be built as asked. Nothing was written."""


@dataclass(frozen=True)
class PlannedNode:
    kind: str  # folder | playlist
    name: str
    path: NodePath
    children: tuple["PlannedNode", ...] = ()
    track_ids: tuple[str, ...] = ()  # library ids, playlist order, each once


@dataclass(frozen=True)
class XmlPlan:
    """What the XML will hold, before it is rendered."""

    nodes: tuple[PlannedNode, ...]
    tracks: tuple[Track, ...]  # COLLECTION, in order of first reference
    track_ids: dict[str, int]  # library id -> TrackID written
    manual: tuple[NodePath, ...] = ()  # smart playlists left out
    unplaced: tuple[str, ...] = ()  # library ids left out: no file location
    vetoed: tuple[str, ...] = ()  # library ids left out: "never propose" in taste/vetoes.md

    def walk(self) -> Iterator[PlannedNode]:
        def visit(nodes: Sequence[PlannedNode]) -> Iterator[PlannedNode]:
            for node in nodes:
                yield node
                yield from visit(node.children)

        yield from visit(self.nodes)

    def playlist_tracks(self) -> dict[str, list[str]]:
        """'A/B' -> library ids, for every playlist in the plan (used for digests and counts)."""
        return {"/".join(n.path): list(n.track_ids) for n in self.walk() if n.kind == "playlist"}


# -- planning ------------------------------------------------------------------------------


def track_id_map(lib: Library) -> dict[str, int]:
    """Library id -> XML TrackID (see the module docstring)."""
    plain = {tid: int(tid) for tid in lib.tracks if _POSITIVE_ID.match(tid)}
    base = max(plain.values(), default=0)
    others = sorted((tid for tid in lib.tracks if tid not in plain), key=id_sort_key)
    mapping = dict(plain)
    mapping.update({tid: base + n for n, tid in enumerate(others, 1)})
    return mapping


def tracks_from(lib: Library, sources: Iterable[str], where: str = "") -> list[str]:
    """Library ids of the playlists `sources` ("A/B"), in order, each id once.

    Ids the collection lacks are skipped (as `Library.tracks_in` does). An unknown, ambiguous
    or folder path -> BuildError naming it and the node that asked for it.
    """
    seen: set[str] = set()
    out: list[str] = []
    for source in sources:
        try:
            tracks = lib.tracks_in(source)
        except LibraryError as exc:
            target = f" (for {where})" if where else ""
            raise BuildError(f"`from: {source}`{target}: {exc}") from exc
        for track in tracks:
            if track.id not in seen:
                seen.add(track.id)
                out.append(track.id)
    return out


def _paths(only: Iterable[NodePath | str] | None) -> set[NodePath] | None:
    if only is None:
        return None
    out = set()
    for item in only:
        out.add(tuple(p for p in item.split("/")) if isinstance(item, str) else tuple(item))
    return out


def plan_xml(
    doc: TreeDoc | Sequence[TreeNode],
    lib: Library,
    *,
    only: Iterable[NodePath | str] | None = None,
    vetoed: Iterable[str] = (),
) -> XmlPlan:
    """The nodes and tracks the XML will hold. `only`: node paths (tuples, or "A/B" text).
    `vetoed`: library ids no playlist may hold (R-702), left out and listed in `XmlPlan.vetoed`."""
    wanted = _paths(only)
    banned = {str(tid) for tid in vetoed}
    nodes = doc.nodes if isinstance(doc, TreeDoc) else tuple(doc)
    manual: list[NodePath] = []
    unplaced: list[str] = []
    left_out: list[str] = []

    def plan(level: Sequence[TreeNode], prefix: NodePath) -> tuple[PlannedNode, ...]:
        out = []
        for node in level:
            path = prefix + (node.name,)
            if wanted is not None and path not in wanted:
                continue
            if node.kind == "smart":
                manual.append(path)
                continue
            if node.kind == "folder":
                out.append(PlannedNode("folder", node.name, path, children=plan(node.children, path)))
                continue
            ids = []
            for tid in tracks_from(lib, node.fill_from, "/".join(path)):
                if tid in banned:
                    if tid not in left_out:
                        left_out.append(tid)
                elif lib.tracks[tid].location:
                    ids.append(tid)
                elif tid not in unplaced:
                    unplaced.append(tid)
            out.append(PlannedNode("playlist", node.name, path, track_ids=tuple(ids)))
        return tuple(out)

    planned = plan(nodes, ())
    return _finish(planned, lib, manual=manual, unplaced=unplaced, vetoed=left_out)


def _finish(
    planned: tuple[PlannedNode, ...],
    lib: Library,
    *,
    manual: Sequence[NodePath] = (),
    unplaced: Sequence[str] = (),
    vetoed: Sequence[str] = (),
) -> XmlPlan:
    """The plan for planned nodes: COLLECTION in order of first reference, TrackIDs mapped."""
    mapping = track_id_map(lib)
    order: dict[str, None] = {}
    for node in XmlPlan(planned, (), {}).walk():
        for tid in node.track_ids:
            order.setdefault(tid, None)
    tracks = tuple(lib.tracks[tid] for tid in order)
    return XmlPlan(
        nodes=planned,
        tracks=tracks,
        track_ids={tid: mapping[tid] for tid in order},
        manual=tuple(manual),
        unplaced=tuple(unplaced),
        vetoed=tuple(vetoed),
    )


def plan_lists(playlists: Iterable[tuple[Sequence[str], Sequence[str]]], lib: Library) -> XmlPlan:
    """Explicit track lists -> the plan. Each item: (playlist path, library ids in order).

    The folders on the paths are made once each, in order of first appearance; a playlist keeps
    its ids in the order given, each once (the first wins). An id the library lacks, an empty
    name, a path given twice, or a name used as a folder and as a playlist -> BuildError. A
    track without a file location is left out (`XmlPlan.unplaced`)."""
    top: list[dict] = []
    unplaced: list[str] = []
    for path, ids in playlists:
        parts = tuple(str(p) for p in path)
        where = "/".join(parts)
        if not parts or any(not p.strip() for p in parts):
            raise BuildError(f"playlist path {where!r}: every name must be non-empty")
        level, prefix = top, ()
        for name in parts[:-1]:
            prefix += (name,)
            node = next((n for n in level if n["name"] == name), None)
            if node is None:
                node = {"kind": "folder", "name": name, "path": prefix, "children": []}
                level.append(node)
            elif node["kind"] != "folder":
                raise BuildError(f"{'/'.join(prefix)} is a playlist and a folder in {where!r}")
            level = node["children"]
        if any(n["name"] == parts[-1] for n in level):
            raise BuildError(f"{where} is given twice")
        kept: list[str] = []
        for tid in (str(t) for t in ids):
            if tid not in lib.tracks:
                raise BuildError(f"{where}: track {tid} is not in the library")
            if tid in kept:
                continue
            if lib.tracks[tid].location:
                kept.append(tid)
            elif tid not in unplaced:
                unplaced.append(tid)
        level.append({"kind": "playlist", "name": parts[-1], "path": parts, "ids": tuple(kept)})

    def freeze(level: list[dict]) -> tuple[PlannedNode, ...]:
        out = []
        for n in level:
            if n["kind"] == "folder":
                out.append(PlannedNode("folder", n["name"], n["path"], children=freeze(n["children"])))
            else:
                out.append(PlannedNode("playlist", n["name"], n["path"], track_ids=n["ids"]))
        return tuple(out)

    return _finish(freeze(top), lib, unplaced=unplaced)


# -- rendering -----------------------------------------------------------------------------


def _clean(value: str) -> str:
    return _NOT_XML.sub("", value)


def _colour_code(colour: str) -> str:
    if colour in COLOUR_CODES:
        return COLOUR_CODES[colour]
    if _HEX_COLOUR.match(colour):
        return "0x" + colour[2:].upper()
    return ""  # a colour name rekordbox does not know: left out


def track_attributes(track: Track, track_id: int) -> dict[str, str]:
    """COLLECTION/TRACK attributes for one track, in the order rekordbox exports them."""
    stars = max(0, min(5, track.rating))
    values = (
        ("TrackID", str(track_id)),
        ("Name", track.title),
        ("Artist", track.artist),
        ("Album", track.album),
        ("Genre", track.genre),
        ("Kind", KIND_TEXT.get(track.kind, "")),
        ("Size", str(track.file_size) if track.file_size > 0 else ""),
        ("TotalTime", str(track.duration_s) if track.duration_s > 0 else ""),
        ("Year", str(track.year) if track.year > 0 else ""),
        ("AverageBpm", f"{track.bpm:.2f}" if track.bpm > 0 else ""),
        ("DateAdded", track.date_added.isoformat() if track.date_added else ""),
        ("BitRate", str(track.bitrate) if track.bitrate > 0 else ""),
        ("SampleRate", str(track.sample_rate) if track.sample_rate > 0 else ""),
        ("Comments", track.comment),
        ("PlayCount", str(track.play_count) if track.play_count > 0 else ""),
        ("Rating", str(stars * RATING_STEP) if stars else ""),
        ("Location", location_url(track.location)),
        ("Remixer", track.remixer),
        ("Tonality", track.key),
        ("Label", track.label),
        ("Colour", _colour_code(track.colour) if track.colour else ""),
    )
    return {key: _clean(value) for key, value in values if value}


def render(plan: XmlPlan, *, product_version: str) -> str:
    """The XML text for a plan: UTF-8 declaration, two-space indent, LF line ends."""
    if not isinstance(product_version, str) or not product_version.strip():
        raise BuildError(f"product_version must be a non-empty text, got {product_version!r}")
    root = ET.Element("DJ_PLAYLISTS", Version=FORMAT_VERSION)
    ET.SubElement(root, "PRODUCT", Name=PRODUCT_NAME, Version=product_version.strip(), Company=PRODUCT_NAME)
    collection = ET.SubElement(root, "COLLECTION", Entries=str(len(plan.tracks)))
    for track in plan.tracks:
        ET.SubElement(collection, "TRACK", track_attributes(track, plan.track_ids[track.id]))
    playlists = ET.SubElement(root, "PLAYLISTS")
    top = ET.SubElement(playlists, "NODE", Type="0", Name="ROOT", Count=str(len(plan.nodes)))
    _render_nodes(top, plan.nodes, plan.track_ids)
    ET.indent(root, space="  ")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n"


def _render_nodes(parent: ET.Element, nodes: Sequence[PlannedNode], ids: dict[str, int]) -> None:
    for node in nodes:
        name = _clean(node.name)
        if node.kind == "folder":
            el = ET.SubElement(parent, "NODE", Type="0", Name=name, Count=str(len(node.children)))
            _render_nodes(el, node.children, ids)
            continue
        el = ET.SubElement(
            parent, "NODE", Name=name, Type="1", KeyType="0", Entries=str(len(node.track_ids))
        )
        for tid in node.track_ids:
            ET.SubElement(el, "TRACK", Key=str(ids[tid]))


def build_xml(
    doc: TreeDoc | Sequence[TreeNode],
    lib: Library,
    *,
    only: Iterable[NodePath | str] | None = None,
    product_version: str,
) -> str:
    """The rekordbox XML text for `doc` (see the module docstring). Writes nothing."""
    return render(plan_xml(doc, lib, only=only), product_version=product_version)


def build_lists_xml(
    playlists: Iterable[tuple[Sequence[str], Sequence[str]]], lib: Library, *, product_version: str
) -> str:
    """The rekordbox XML text for explicit track lists (`plan_lists`). Writes nothing."""
    return render(plan_lists(playlists, lib), product_version=product_version)


# -- writing -------------------------------------------------------------------------------


def numbered(path: Path) -> Iterator[Path]:
    """`path`, then `<stem>-2<suffix>`, `-3` ..."""
    yield path
    for n in range(2, MAX_NUMBERED + 1):
        yield path.with_name(f"{path.stem}-{n}{path.suffix}")


def write_xml(text: str, path: str | Path) -> Path:
    """Write `text` to `path`, or to the first free `<stem>-N.xml` next to it. Returns the path.

    Create-only (hard rule 1): an existing file is never replaced. Each try writes a temp file
    and links it into place, which fails when the name is taken (`libfolder.write_new_text`).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    for candidate in numbered(path):
        if write_new_text(candidate, text):
            return candidate
    raise BuildError(f"{path.name}: {MAX_NUMBERED} numbered names are taken. Nothing was written.")
