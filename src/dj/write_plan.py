"""What a write into rekordbox will hold: folders, playlists and their tracks, before it is written.

Stdlib only (+ PyYAML through `dj.treeschema`). Nothing here opens master.db: `dj.db_write` writes
a `WritePlan` inside `safety.open_db(write=True)`.

    plan_tree(doc, lib, only=..., vetoed=...)   a proposal tree (`dj.treeschema.TreeDoc`) -> WritePlan
    plan_lists([(path, ids), ...], lib)         explicit track lists (Crate me) -> WritePlan

Rules:
- A playlist holds the tracks of its `from` playlists (existing playlists of the library), in
  order, each track once (the first time it appears wins). An unknown `from` path -> BuildError.
- Smart playlists are not written by a build: left out (`WritePlan.manual`), made by hand.
- A track without a file location is left out (`WritePlan.unplaced`).
- `only` (a set of node paths) limits the tree to those nodes; callers pass the CREATE nodes and
  their ancestor folders.
- `vetoed` (library ids, from `taste/vetoes.md` "never propose") are left out of every playlist
  a `from` fills (R-702); `WritePlan.vetoed` lists the ones that were left out.
- `plan_lists` takes explicit track lists instead of a tree: each playlist path with its ids in
  order; the folders on the paths are made once, in order.
- `track_id_map`: library id -> a positive whole number, the same for the same library: the id
  itself when it is one written without leading zeros (master.db content ids), else a number above
  the largest such id, in library id order.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Iterator, Sequence

from dj.model import Library, LibraryError, Track, id_sort_key
from dj.treeschema import TreeDoc, TreeNode

_POSITIVE_ID = re.compile(r"^[1-9][0-9]*$")

NodePath = tuple[str, ...]

__all__ = ["BuildError", "NodePath", "PlannedNode", "WritePlan", "plan_lists", "plan_tree", "track_id_map",
           "tracks_from"]  # fmt: skip


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
class WritePlan:
    """What the write will hold."""

    nodes: tuple[PlannedNode, ...]
    tracks: tuple[Track, ...]  # every track a playlist references, in order of first reference
    track_ids: dict[str, int]  # library id -> its number (`track_id_map`)
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


def track_id_map(lib: Library) -> dict[str, int]:
    """Library id -> its number (see the module docstring)."""
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


def plan_tree(
    doc: TreeDoc | Sequence[TreeNode],
    lib: Library,
    *,
    only: Iterable[NodePath | str] | None = None,
    vetoed: Iterable[str] = (),
) -> WritePlan:
    """The nodes and tracks the write will hold. `only`: node paths (tuples, or "A/B" text).
    `vetoed`: library ids no playlist may hold (R-702), left out and listed in `WritePlan.vetoed`."""
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
) -> WritePlan:
    """The plan for planned nodes: the tracks in order of first reference, their numbers mapped."""
    mapping = track_id_map(lib)
    order: dict[str, None] = {}
    for node in WritePlan(planned, (), {}).walk():
        for tid in node.track_ids:
            order.setdefault(tid, None)
    tracks = tuple(lib.tracks[tid] for tid in order)
    return WritePlan(
        nodes=planned,
        tracks=tracks,
        track_ids={tid: mapping[tid] for tid in order},
        manual=tuple(manual),
        unplaced=tuple(unplaced),
        vetoed=tuple(vetoed),
    )


def plan_lists(playlists: Iterable[tuple[Sequence[str], Sequence[str]]], lib: Library) -> WritePlan:
    """Explicit track lists -> the plan. Each item: (playlist path, library ids in order).

    The folders on the paths are made once each, in order of first appearance; a playlist keeps
    its ids in the order given, each once (the first wins). An id the library lacks, an empty
    name, a path given twice, or a name used as a folder and as a playlist -> BuildError. A
    track without a file location is left out (`WritePlan.unplaced`)."""
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
