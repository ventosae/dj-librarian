"""dj-structure: how the DJ's playlist tree is built, measured by code (R-321, R-322, R-302).

Door 1 core: stdlib + PyYAML only (contract section 0). Works on a `dj.model.Library`; it
opens no database and writes only text files inside the library folder (R-341).

    facts(lib)   -> dict: depth, width, naming, sizes, overlap, orphans, empty, dumps,
                    smart_vs_plain, notes, reveals. Pure, JSON-serialisable, deterministic.
    graph(lib)   -> dict: nodes, edges, overlaps (for the report's crate wall).
    write(...)   -> structure/analysis.md, graph.json, facts.json, current-tree.yaml.
    run(folder)  -> read the latest export, compute, write, append one log.md line.

What the numbers mean (analysis.md and facts.json use exactly these definitions):

- Paths are "Folder/Playlist" with the names of current-tree.yaml. rekordbox allows two
  siblings with the same name, a tree file does not: a repeat is written "Name (2)"
  (`treeschema.level_names`) and listed in `naming.duplicates_renamed` as
  `{"path": <rekordbox path>, "renamed": <path in the tree file>}`. The same goes for a blank
  name, written "(unnamed)".
- depth: a node's level, top level = 1. `max` over every folder and playlist, `mean` over
  playlists (plain and smart).
- width: children per folder. `top` = folders and playlists at the top level.
- size of a playlist: its entries, as rekordbox counts them. Sizes, overlap, dumps and empty
  use the playlists whose tracks the source lists: every plain playlist, and a smart one only
  when its tracks are listed. master.db stores smart rules, not members
  (`dj.readers.db.DB_NOTES`); an XML export has no smart playlists at all.
- naming: over playlist names (folders get their own dominant pattern). A pattern is the
  shape of a name: its case (lower, Title, UPPER, Sentence, mixed) and its word separator
  (underscore, dash " - ", hyphen, space, none), written as a template such as `word_word`
  or `Word Word`. A leading number ("1.1_", "01 ") or date ("2025-03-14 ") is left out of
  the pattern ("1.2_peak" -> `word`, "01 Intro" -> `Word`) and counted on its own:
  `numbered` = names with a leading number, `dated` = names holding a year, optionally with
  month and day, such as "2025-03". `separators` and `cases` count the same shapes.
  `top_tokens`: words in folder and playlist names, counted once per name.
- overlap: Jaccard = shared tracks / tracks in either, for every pair of playlists with at
  least one track. Pairs with 0.5 or more are listed, highest first, then by path; 0.8 or
  more are near-duplicates. `contained`: playlists whose every track is in a bigger one;
  `count` = such playlists, `pairs` = (inner, outer) pairs (a playlist inside two bigger
  ones is one playlist, two pairs), `top` = the first 5 pairs.
- orphans: tracks in no playlist (`Library.orphans`).
- empty: plain playlists with no tracks; folders with nothing in them; dead playlists, whose
  every entry points at a track the collection does not hold.
- dumps: more than 300 tracks (entries, as rekordbox counts them); or more than half the
  collection; or more than 25% of the collection and more than twice the median size of the
  other playlists that hold tracks (so a small library's normal playlists are not dumps).
  The share of the collection counts each collection track in the playlist once, so it is
  never above 100%; `distinct` is that count.
- reveals: at most 5 short sentences built only from the facts above. Names in them, and in
  every analysis.md line outside a table, are written on one line.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from itertools import combinations
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from dj import treeschema
from dj.libfolder import (
    LibraryFolder,
    LibraryFolderError,
    append_log,
    latest_export,
    load_meta,
    relative,
    validate_meta,
    write_text,
)
from dj.model import Library, LibraryError, PlaylistNode, Track
from dj.readers.xml import read_xml

MODULE = "dj.analysis.structure"
LIST_MAX = 5  # DJ-facing lists (R-1002 rule 9); full data lives in the JSON files
SHAPES_SHOWN = 2  # separators and cases shown in analysis.md: the most used ones
OVERLAP_MIN = 0.5
NEAR_DUPLICATE_MIN = 0.8
DUMP_TRACKS = 300
DUMP_HALF = 0.5
DUMP_SHARE = 0.25
DUMP_MEDIAN_FACTOR = 2
DUMP_RULE = (
    f"more than {DUMP_TRACKS} tracks; or more than half the collection; or more than "
    f"{round(DUMP_SHARE * 100)}% of the collection and more than {DUMP_MEDIAN_FACTOR} times the "
    "median size of the other playlists that hold tracks (each track counted once)"
)
SIZE_BUCKETS = (("0", 0, 0), ("1-25", 1, 25), ("26-100", 26, 100), ("101-300", 101, 300), ("300+", 301, None))
CASES = ("lower", "Title", "UPPER", "Sentence", "mixed", "none")
SEPARATORS = ("underscore", "dash", "hyphen", "space", "none")
_JOIN = {"underscore": "_", "dash": " - ", "hyphen": "-", "space": " "}
_WORDS = {
    "lower": ("word", "word"),
    "Title": ("Word", "Word"),
    "UPPER": ("WORD", "WORD"),
    "Sentence": ("Word", "word"),
    "mixed": ("wOrd", "wOrd"),
    "none": ("123", "123"),
}
_LETTERS = re.compile(r"[^\W\d_]+")
_TOKEN = re.compile(r"[^\W_]+")
_HYPHEN = re.compile(r"(?<=[^\W\d_])-(?=[^\W\d_])")
_NUMBERED = re.compile(r"^\d{1,3}(?:\.\d{1,3})*(?:[_.)\-]|\s)")
_DATED = re.compile(r"(?<!\d)(?:19|20)\d{2}(?:[-./]\d{1,2}){0,2}(?![0-9A-Za-z])")
_LEADING_DATE = re.compile(r"^(?:19|20)\d{2}(?:[-./]\d{1,2}){0,2}(?=[\s_.)\-])")
_LEADING_GAP = " _-.)"
_DRIVE = re.compile(r"^[A-Za-z]:/")
_STOPWORDS = frozenset({"a", "an", "and", "at", "by", "for", "in", "my", "of", "on", "the", "to", "with"})

FILES = ("analysis.md", "graph.json", "facts.json", "current-tree.yaml")
TREE_FILE = "current-tree.yaml"
_FINGERPRINT = re.compile(r"^# fingerprint: ([0-9a-f]{12})\s*$")


# -- walking the tree ------------------------------------------------------------------------


@dataclass(frozen=True)
class _Item:
    node: PlaylistNode
    name: str  # as in current-tree.yaml
    path: str  # unique "Folder/Playlist", names as in current-tree.yaml
    original: str  # the same path with rekordbox's names
    depth: int
    parent: str | None


def _items(lib: Library) -> list[_Item]:
    """Every node in tree order, with its tree-file name and a path no other node has."""
    out: list[_Item] = []
    seen: set[str] = set()

    def visit(nodes: Sequence[PlaylistNode], prefix: tuple[str, ...], orig: tuple[str, ...], parent: str | None) -> None:
        for node, name in zip(nodes, treeschema.level_names([n.name for n in nodes])):
            names, originals = prefix + (name,), orig + (node.name,)
            path, k = "/".join(names), 2
            while path in seen:  # only a "/" inside a name can make two paths alike
                path, k = f"{'/'.join(names)} #{k}", k + 1
            seen.add(path)
            out.append(_Item(node, name, path, "/".join(originals), len(names), parent))
            visit(node.children, names, originals, path)

    visit(lib.roots, (), (), None)
    return out


def _measured(items: Iterable[_Item]) -> list[_Item]:
    """Playlists whose tracks the source lists: plain ones, and smart ones that list tracks."""
    return [i for i in items if i.node.kind == "playlist" or (i.node.kind == "smart" and i.node.track_ids)]


def _share(part: int, whole: int) -> float:
    return round(part / whole, 3) if whole else 0.0


def _pct(share: float) -> int:
    return round(share * 100)


# -- overlap ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Pair:
    a: _Item  # earlier in the tree
    b: _Item
    shared: int
    union: int

    @property
    def jaccard(self) -> float:
        return self.shared / self.union

    def as_dict(self) -> dict[str, Any]:
        return {"a": self.a.path, "b": self.b.path, "jaccard": round(self.jaccard, 3), "shared": self.shared}


def _pairs(measured: Sequence[_Item]) -> tuple[list[_Pair], int]:
    """(every pair sharing at least one track, how many pairs of non-empty playlists there are).
    Counted through the tracks, so pairs with nothing in common cost nothing."""
    sets = [frozenset(i.node.track_ids) for i in measured]
    by_track: dict[str, list[int]] = defaultdict(list)
    for k, tracks in enumerate(sets):
        for track_id in sorted(tracks):
            by_track[track_id].append(k)
    shared: Counter[tuple[int, int]] = Counter()
    for ks in by_track.values():
        shared.update(combinations(ks, 2))
    pairs = [
        _Pair(measured[x], measured[y], n, len(sets[x]) + len(sets[y]) - n)
        for (x, y), n in sorted(shared.items())
    ]
    filled = sum(1 for s in sets if s)
    return pairs, filled * (filled - 1) // 2


def _ranked(pairs: Iterable[_Pair], minimum: float) -> list[_Pair]:
    return sorted((p for p in pairs if p.jaccard >= minimum), key=lambda p: (-p.jaccard, p.a.path, p.b.path))


def _contained(pairs: Iterable[_Pair]) -> dict[str, Any]:
    """Playlists whose every track is in a bigger one. `count` = those playlists (one sitting
    inside two bigger ones counts once), `pairs` = (inner, outer) pairs, `top` = 5 pairs."""
    out = []
    for p in pairs:
        size_a, size_b = len(set(p.a.node.track_ids)), len(set(p.b.node.track_ids))
        if p.shared == size_a < size_b:
            out.append((p.a, p.b, p.shared))
        elif p.shared == size_b < size_a:
            out.append((p.b, p.a, p.shared))
    out.sort(key=lambda row: (-row[2], row[0].path, row[1].path))
    rows = [{"inner": inner.path, "outer": outer.path, "tracks": n} for inner, outer, n in out]
    return {"count": len({row["inner"] for row in rows}), "pairs": len(rows), "top": rows[:LIST_MAX]}


# -- naming -----------------------------------------------------------------------------------


def _case(name: str) -> str:
    words = _LETTERS.findall(name)
    if not words:
        return "none"
    kinds = []
    for word in words:
        if word.islower():
            kinds.append("lower")
        elif word.isupper() and len(word) > 1:
            kinds.append("upper")
        elif word[0].isupper() and (len(word) == 1 or word[1:].islower()):
            kinds.append("title")
        else:
            kinds.append("mixed")
    if all(k == "lower" for k in kinds):
        return "lower"
    if all(k == "upper" for k in kinds):
        return "UPPER"
    if all(k in ("title", "upper") for k in kinds):
        return "Title"
    if len(kinds) > 1 and kinds[0] in ("title", "upper") and all(k == "lower" for k in kinds[1:]):
        return "Sentence"
    return "mixed"


def _separator(name: str) -> str:
    if " - " in name:
        return "dash"
    counts = {
        "underscore": name.count("_"),
        "hyphen": len(_HYPHEN.findall(name)),
        "space": name.count(" "),
    }
    best = max(counts, key=lambda key: counts[key])  # ties: the order above
    return best if counts[best] else "none"


def _core(name: str) -> str:
    """The name without a leading number ("1.1_", "01 ", "3) ") or date ("2025-03-14 "):
    those are counted under `numbered` and `dated`, not in the pattern. A name that is only
    a number keeps it."""
    name = name.strip()
    core = name
    for lead in (_NUMBERED, _LEADING_DATE):
        match = lead.match(core)
        if match:
            core = core[match.end():].lstrip(_LEADING_GAP)
    return core or name.rstrip(_LEADING_GAP) or name


def _form(name: str) -> tuple[str, str]:
    """(case, separator) of a name, its leading number or date left out."""
    core = _core(name)
    return _case(core), _separator(core)


def pattern(name: str) -> str:
    """The shape of one name as a template: "1.1_warm_up" -> "word_word", "1.2_peak" ->
    "word", "01 Intro" -> "Word", "Gig 2025-03 Warehouse" -> "Word Word", "House" -> "Word"."""
    case, sep = _form(name)
    first, rest = _WORDS[case]
    return first if sep == "none" else f"{first}{_JOIN[sep]}{rest}"


def _tokens(name: str) -> list[str]:
    words = _TOKEN.findall(name.casefold())
    return list(dict.fromkeys(w for w in words if len(w) > 1 and not w.isdigit() and w not in _STOPWORDS))


def _dominant(names: Sequence[str]) -> list[dict[str, Any]]:
    """Patterns, most common first; ties by first appearance in the tree."""
    found: dict[str, dict[str, Any]] = {}
    for name in names:
        row = found.setdefault(pattern(name), {"pattern": pattern(name), "count": 0, "example": name})
        row["count"] += 1
    return sorted(found.values(), key=lambda row: -row["count"])  # stable: tree order on ties


def _naming(items: Sequence[_Item]) -> dict[str, Any]:
    playlists = [i.node.name.strip() for i in items if i.node.kind != "folder"]
    folders = [i.node.name.strip() for i in items if i.node.kind == "folder"]
    patterns = _dominant(playlists)
    folder_patterns = _dominant(folders)
    numbered = [n for n in playlists if _NUMBERED.match(n)]
    dated = [n for n in playlists if _DATED.search(n)]
    tokens: Counter[str] = Counter(t for item in items for t in _tokens(item.node.name))
    top = sorted(tokens, key=lambda t: (-tokens[t], t))[:LIST_MAX]
    renamed = [
        {"path": i.original, "renamed": i.path}
        for i in items
        if i.name != i.node.name.strip()
    ]
    top_pattern = patterns[0] if patterns else None
    top_folder = folder_patterns[0] if folder_patterns else None
    forms = [_form(n) for n in playlists]
    return {
        "names": len(playlists),
        "dominant": top_pattern["pattern"] if top_pattern else None,
        "dominant_count": top_pattern["count"] if top_pattern else 0,
        "dominant_share": _share(top_pattern["count"], len(playlists)) if top_pattern else 0.0,
        "patterns": patterns[:LIST_MAX],
        "separators": {sep: sum(s == sep for _, s in forms) for sep in SEPARATORS},
        "cases": {case: sum(c == case for c, _ in forms) for case in CASES},
        "numbered": {"count": len(numbered), "examples": numbered[:LIST_MAX]},
        "dated": {"count": len(dated), "examples": dated[:LIST_MAX]},
        "top_tokens": [{"token": t, "count": tokens[t]} for t in top],
        "folders": {
            "names": len(folders),
            "dominant": top_folder["pattern"] if top_folder else None,
            "dominant_share": _share(top_folder["count"], len(folders)) if top_folder else 0.0,
        },
        "duplicates_renamed": renamed,
    }


# -- the facts --------------------------------------------------------------------------------


def _depth(items: Sequence[_Item]) -> dict[str, Any]:
    playlists = [i for i in items if i.node.kind != "folder"]
    deepest = max((i.depth for i in items), default=0)
    levels = Counter(i.depth for i in playlists)
    return {
        "max": deepest,
        "mean": round(statistics.fmean(i.depth for i in playlists), 2) if playlists else None,
        "playlists_by_level": {str(level): levels[level] for level in sorted(levels)},
        "deepest": [i.path for i in items if i.depth == deepest][:LIST_MAX] if items else [],
    }


def _width(lib: Library, items: Sequence[_Item]) -> dict[str, Any]:
    folders = [i for i in items if i.node.kind == "folder"]
    widest = max(folders, key=lambda i: len(i.node.children), default=None)  # first on ties
    return {
        "top": len(lib.roots),
        "folders": len(folders),
        "max": len(widest.node.children) if widest else 0,
        "max_path": widest.path if widest else None,
        "mean": round(statistics.fmean(len(i.node.children) for i in folders), 2) if folders else None,
    }


def _median(sizes: Sequence[int]) -> float | None:
    return float(statistics.median(sizes)) if sizes else None


def _sizes(measured: Sequence[_Item]) -> dict[str, Any]:
    sizes = sorted(len(i.node.track_ids) for i in measured)
    buckets = {
        label: sum(1 for s in sizes if s >= low and (high is None or s <= high))
        for label, low, high in SIZE_BUCKETS
    }
    largest = sorted(measured, key=lambda i: (-len(i.node.track_ids), i.path))[:LIST_MAX]
    return {
        "playlists": len(sizes),
        "min": sizes[0] if sizes else None,
        "median": _median(sizes),
        "max": sizes[-1] if sizes else None,
        "buckets": buckets,
        "largest": [{"path": i.path, "tracks": len(i.node.track_ids)} for i in largest],
    }


def _overlap(pairs: Sequence[_Pair], checked: int) -> dict[str, Any]:
    listed = _ranked(pairs, OVERLAP_MIN)
    near = [p for p in listed if p.jaccard >= NEAR_DUPLICATE_MIN]
    return {
        "pairs_checked": checked,
        "min_jaccard": OVERLAP_MIN,
        "count": len(listed),
        "top": [p.as_dict() for p in listed[:LIST_MAX]],
        "near_duplicates": {
            "min_jaccard": NEAR_DUPLICATE_MIN,
            "count": len(near),
            "top": [p.as_dict() for p in near[:LIST_MAX]],
        },
        "contained": _contained(pairs),
    }


def _orphans(lib: Library) -> dict[str, Any]:
    orphans = lib.orphans()
    return {
        "count": len(orphans),
        "share": _share(len(orphans), len(lib.tracks)),
        "examples": [{"id": t.id, "track": t.label_line or f"track {t.id}"} for t in orphans[:LIST_MAX]],
        "ids": [t.id for t in orphans],
    }


def _empty(lib: Library, items: Sequence[_Item]) -> dict[str, Any]:
    empty = [i.path for i in items if i.node.kind == "playlist" and not i.node.track_ids]
    empty_folders = [i.path for i in items if i.node.kind == "folder" and not i.node.children]
    dead = [
        i.path
        for i in _measured(items)
        if i.node.track_ids and not any(t in lib.tracks for t in i.node.track_ids)
    ]
    return {
        "count": len(empty),
        "paths": empty[:LIST_MAX],
        "folders": len(empty_folders),
        "folder_paths": empty_folders[:LIST_MAX],
        "dead": len(dead),
        "dead_paths": dead[:LIST_MAX],
    }


def _dumps(measured: Sequence[_Item], collection: Mapping[str, Track]) -> dict[str, Any]:
    """Catch-all playlists (rule: DUMP_RULE). `tracks` = entries, as rekordbox counts them;
    `distinct` = collection tracks in the playlist, each once; `share` = distinct / collection."""
    total = len(collection)
    held = [len(set(i.node.track_ids) & collection.keys()) for i in measured]

    def is_dump(k: int) -> bool:
        if len(measured[k].node.track_ids) > DUMP_TRACKS:
            return True
        share = held[k] / total if total else 0.0
        if share > DUMP_HALF:
            return True
        if share <= DUMP_SHARE:
            return False
        median = _median([h for j, h in enumerate(held) if j != k and h])  # the others that hold tracks
        return median is not None and held[k] > DUMP_MEDIAN_FACTOR * median

    dumps = sorted(
        (k for k in range(len(measured)) if is_dump(k)),
        key=lambda k: (-len(measured[k].node.track_ids), measured[k].path),
    )
    return {
        "rule": DUMP_RULE,
        "count": len(dumps),
        "top": [
            {"path": measured[k].path, "tracks": len(measured[k].node.track_ids), "distinct": held[k],
             "share": _share(held[k], total)}
            for k in dumps[:LIST_MAX]
        ],  # fmt: skip
    }


def _smart_vs_plain(items: Sequence[_Item]) -> dict[str, Any]:
    plain = [i for i in items if i.node.kind == "playlist"]
    smart = [i for i in items if i.node.kind == "smart"]
    return {
        "plain": len(plain),
        "smart": len(smart),
        "smart_share": _share(len(smart), len(plain) + len(smart)),
        "smart_paths": [i.path for i in smart[:LIST_MAX]],
        "smart_tracks_listed": sum(1 for i in smart if i.node.track_ids),
    }


def _notes(lib: Library, items: Sequence[_Item]) -> list[str]:
    notes = []
    if lib.source == "xml":
        notes.append("An XML export carries no smart playlists, so none are counted here.")
    elif any(i.node.kind == "smart" and not i.node.track_ids for i in items):
        notes.append(
            "master.db stores the rules of a smart playlist, not its tracks: smart playlists are "
            "left out of sizes and overlap, and a track only a smart playlist reaches counts as an orphan."
        )
    return notes


def facts(lib: Library, *, today: date | None = None) -> dict[str, Any]:
    """Everything dj-structure measures, as one JSON-serialisable dict (definitions: module
    docstring). Pure: same Library, same dict. `today` is accepted for the common analysis
    signature; no structure fact depends on the date."""
    items = _items(lib)
    measured = _measured(items)
    pairs, checked = _pairs(measured)
    data: dict[str, Any] = {
        "source": lib.source,
        "counts": lib.counts(),
        "depth": _depth(items),
        "width": _width(lib, items),
        "naming": _naming(items),
        "sizes": _sizes(measured),
        "overlap": _overlap(pairs, checked),
        "orphans": _orphans(lib),
        "empty": _empty(lib, items),
        "dumps": _dumps(measured, lib.tracks),
        "smart_vs_plain": _smart_vs_plain(items),
        "notes": _notes(lib, items),
    }
    data["reveals"] = reveals(data)
    return data


def _plural(n: int, word: str, plural: str | None = None) -> str:
    return f"{n} {word if n == 1 else (plural or word + 's')}"


def reveals(f: dict[str, Any]) -> list[str]:
    """At most 5 short plain sentences, built only from the facts (numbers from code)."""
    out: list[str] = []
    counts, depth = f["counts"], f["depth"]
    playlists = counts["playlists"] + counts["smart"]
    if not playlists:
        out.append(f"No playlists yet: all {_plural(counts['tracks'], 'track')} sit in the collection only.")
        return out
    lists = _plural(playlists, "playlist") + (f" ({counts['smart']} smart)" if counts["smart"] else "")
    if counts["folders"]:
        out.append(f"{lists} in {_plural(counts['folders'], 'folder')}, {_plural(depth['max'], 'level')} deep at most.")
    else:
        out.append(f"{lists}, all at the top level: no folders.")

    naming = f["naming"]
    if naming["names"] > 1 and naming["dominant_count"] > 1:
        share = naming["dominant_share"]
        verb = "follow" if share >= 0.5 else "share"
        out.append(
            f"{naming['dominant_count']} of {naming['names']} playlist names {verb} one pattern: "
            f"{naming['dominant']}."
        )

    dumps = f["dumps"]
    if dumps["count"]:
        top = dumps["top"][0]
        where = f"{top['tracks']} tracks, {_pct(top['share'])}% of the collection"
        if dumps["count"] == 1:
            out.append(f"{_one_line(top['path'])} holds {where}: a dump.")
        else:
            out.append(f"{dumps['count']} playlists are dumps; the biggest, {_one_line(top['path'])}, holds {where}.")

    overlap = f["overlap"]
    if overlap["near_duplicates"]["count"]:
        near = overlap["near_duplicates"]
        top = near["top"][0]
        lead = "1 pair of playlists is" if near["count"] == 1 else f"{near['count']} pairs of playlists are"
        out.append(
            f"{lead} nearly the same: {_one_line(top['a'])} and {_one_line(top['b'])} share {top['shared']} tracks."
        )
    elif overlap["count"]:
        top = overlap["top"][0]
        out.append(
            f"{_one_line(top['a'])} and {_one_line(top['b'])} share {top['shared']} tracks "
            f"(overlap {top['jaccard']:.2f})."
        )
    elif overlap["contained"]["count"]:
        top = overlap["contained"]["top"][0]
        out.append(f"{_one_line(top['inner'])} sits entirely inside {_one_line(top['outer'])}.")

    parts = []
    orphans, empty = f["orphans"], f["empty"]
    if orphans["count"]:
        verb = "sits" if orphans["count"] == 1 else "sit"
        parts.append(f"{_plural(orphans['count'], 'track')} ({_pct(orphans['share'])}%) {verb} in no playlist")
    if empty["count"]:
        which = f" ({_one_line(empty['paths'][0])})" if empty["count"] == 1 else ""
        parts.append(f"{_plural(empty['count'], 'playlist')} {'is' if empty['count'] == 1 else 'are'} empty{which}")
    if parts:
        out.append("; ".join(parts) + ".")

    return out[:LIST_MAX]


# -- graph -------------------------------------------------------------------------------------


def _folder_tracks(node: PlaylistNode) -> set[str]:
    if node.kind != "folder":
        return set(node.track_ids)
    out: set[str] = set()
    for child in node.children:
        out |= _folder_tracks(child)
    return out


def _node_tracks(node: PlaylistNode) -> int | None:
    if node.kind == "folder":
        return len(_folder_tracks(node))
    if node.kind == "smart" and not node.track_ids:
        return None  # not listed by the source: unknown, not zero
    return len(node.track_ids)


def graph(lib: Library) -> dict[str, Any]:
    """{"nodes": [{id, path, name, kind, tracks, depth}], "edges": [{source, target}],
    "overlaps": [{a, b, jaccard, shared}]}. Ids are the paths (names as in current-tree.yaml).
    A folder's `tracks` = distinct tracks in the playlists below it; an unlisted smart
    playlist has `tracks: null`. `overlaps` = every pair at 0.5 or more, highest first."""
    items = _items(lib)
    pairs, _checked = _pairs(_measured(items))
    return {
        "nodes": [
            {"id": i.path, "path": i.path, "name": i.name, "kind": i.node.kind,
             "tracks": _node_tracks(i.node), "depth": i.depth}
            for i in items
        ],  # fmt: skip
        "edges": [{"source": i.parent, "target": i.path} for i in items if i.parent is not None],
        "overlaps": [p.as_dict() for p in _ranked(pairs, OVERLAP_MIN)],
    }


# -- analysis.md -------------------------------------------------------------------------------


def _cell(text: Any) -> str:
    return str(text).replace("\r", " ").replace("\n", " ").replace("|", "\\|")


def _table(head: Sequence[str], rows: Sequence[Sequence[Any]]) -> list[str]:
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    lines += ["| " + " | ".join(_cell(c) for c in row) + " |" for row in rows[:LIST_MAX]]
    return lines


def _most_used(mapping: dict[str, int], limit: int = SHAPES_SHOWN) -> str:
    """The `limit` biggest counts, "space 4, underscore 3"; ties keep the mapping's order.
    The full counts are in facts.json."""
    used = sorted((item for item in mapping.items() if item[1]), key=lambda item: -item[1])
    return ", ".join(f"{key} {n}" for key, n in used[:limit]) or "none"


def _shape(f: dict[str, Any]) -> list[str]:
    c, d, w = f["counts"], f["depth"], f["width"]
    mean_depth = f"{d['mean']:g}" if d["mean"] is not None else "n/a"
    rows = [
        ("Playlists", f"{c['playlists']} plain, {c['smart']} smart, in {_plural(c['folders'], 'folder')}"),
        ("Top level", f"{w['top']} folders and playlists"),
        ("Depth", f"{_plural(d['max'], 'level')} at most; playlists sit {mean_depth} deep on average"),
    ]
    if w["folders"]:
        rows.append(("Width", f"up to {w['max']} inside one folder ({w['max_path']}); {w['mean']:g} per folder on average"))
    return _table(("Measure", "Value"), rows)


def _naming_md(f: dict[str, Any]) -> list[str]:
    n = f["naming"]
    if not n["names"]:
        return ["No playlist names yet."]
    rows = [
        ("Most common pattern", f"{n['dominant']}: {n['dominant_count']} of {n['names']} playlist names ({_pct(n['dominant_share'])}%)"),
        ("Most used separators and case", f"{_most_used(n['separators'])}; {_most_used(n['cases'])}"),
        ("Numbered and dated", f"numbered {n['numbered']['count']}, dated {n['dated']['count']}"),
        ("Top words", ", ".join(f"{t['token']} {t['count']}" for t in n["top_tokens"]) or "none"),
    ]
    renamed = n["duplicates_renamed"]
    if renamed:
        rows.append(("Same name twice", f"{len(renamed)}, written as {renamed[0]['renamed']} in {TREE_FILE}"))
    return _table(("Measure", "Value"), rows)


def _sizes_md(f: dict[str, Any]) -> list[str]:
    s = f["sizes"]
    if not s["playlists"]:
        return ["No playlists with listed tracks."]
    biggest = _one_line(s["largest"][0]["path"])
    lines = [
        f"Smallest {s['min']}, median {s['median']:g}, largest {s['max']} tracks ({biggest}).",
        "",
    ]
    return lines + _table(("Tracks", "Playlists"), list(s["buckets"].items()))


def _overlap_md(f: dict[str, Any]) -> list[str]:
    o = f["overlap"]
    near, contained = o["near_duplicates"], o["contained"]
    lines = [
        f"{_plural(o['pairs_checked'], 'pair')} of playlists checked: {o['count']} overlap 0.5 or more, "
        f"{near['count']} of them near-copies (0.8 or more).",
    ]
    if o["top"]:
        rows = [(p["a"], p["b"], p["shared"], f"{p['jaccard']:.2f}") for p in o["top"]]
        lines += [""] + _table(("Playlist", "Playlist", "Shared", "Overlap"), rows)
    if contained["count"]:
        top = contained["top"][0]
        verb = "sits" if contained["count"] == 1 else "sit"
        lines += ["", f"{_plural(contained['count'], 'playlist')} {verb} entirely inside a bigger one, "
                      f"for example {_one_line(top['inner'])} inside {_one_line(top['outer'])}."]  # fmt: skip
    return lines


def _orphans_md(f: dict[str, Any]) -> list[str]:
    o, e = f["orphans"], f["empty"]
    examples = "; ".join(x["track"] for x in o["examples"]) or "none"
    rows = [
        ("Tracks in no playlist", f"{o['count']} ({_pct(o['share'])}%)"),
        ("For example", examples),
        ("Empty playlists", f"{e['count']}" + (f": {', '.join(e['paths'])}" if e["paths"] else "")),
        ("Empty folders", f"{e['folders']}" + (f": {', '.join(e['folder_paths'])}" if e["folder_paths"] else "")),
        ("Dead playlists (every track gone from the collection)",
         f"{e['dead']}" + (f": {', '.join(e['dead_paths'])}" if e["dead_paths"] else "")),
    ]  # fmt: skip
    return _table(("Measure", "Value"), rows)


def _dumps_md(f: dict[str, Any]) -> list[str]:
    d = f["dumps"]
    lines = [f"A dump here: {d['rule']}."]
    if not d["count"]:
        return lines + ["", "None."]
    rows = [(x["path"], x["tracks"], f"{_pct(x['share'])}%") for x in d["top"]]
    return lines + [""] + _table(("Playlist", "Tracks", "Share of collection"), rows)


def render(f: dict[str, Any], *, source: str, today: date) -> str:
    """analysis.md: title, provenance line, then the sections; every list 5 rows at most."""
    sections = [
        ("Shape", _shape(f)),
        ("Naming", _naming_md(f)),
        ("Sizes", _sizes_md(f)),
        ("Overlap", _overlap_md(f)),
        ("Orphans and empty", _orphans_md(f)),
        ("Dumps", _dumps_md(f)),
        ("What it reveals", [f"- {_one_line(line)}" for line in f["reveals"][:LIST_MAX]] or ["Nothing stands out."]),
    ]
    lines = [
        "# Structure",
        "",
        f"> Measured by code: {MODULE} from {_one_line(source)}, {today.isoformat()}.",
        "",
    ]
    for note in f.get("notes", []):
        lines += [f"Note: {_one_line(note)}", ""]
    for title, body in sections:
        lines += [f"## {title}", "", *body, ""]
    return "\n".join(lines).rstrip("\n") + "\n"


# -- current-tree.yaml -------------------------------------------------------------------------


def _one_line(text: str) -> str:
    return " ".join(str(text).split())


def fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def tree_text(doc: treeschema.TreeDoc, *, source: str, today: date) -> str:
    """current-tree.yaml: 3 comment lines, the fingerprint line, then `treeschema.dumps(doc)`.
    The fingerprint covers the whole file but its own line (the 3 header lines and the body),
    so the next run can tell whether the DJ changed anything (then a copy is kept first)."""
    body = treeschema.dumps(doc)
    head = (
        f"# Your rekordbox tree as code, generated from {_one_line(source)} on {today.isoformat()}.\n"
        f"{_HEADER_FIXED[0]}\n"
        f"{_HEADER_FIXED[1]}\n"
    )
    return f"{head}# fingerprint: {fingerprint(head + body)}\n{body}"


_HEADER_FIRST = re.compile(r"^# Your rekordbox tree as code, generated from .+ on \d{4}-\d{2}-\d{2}\.$")
_HEADER_FIXED = (
    "# Edit freely: dj never writes this file back to rekordbox.",
    "# dj-structure rewrites it on its next run; a copy you edited is kept next to it first.",
)


def _edited(text: str) -> bool:
    """True unless the file is exactly what the tool wrote: the header shape, and every line
    but the fingerprint line (header lines and body alike) matching the fingerprint. A comment
    the DJ added or changed, even in the first line, counts as an edit."""
    lines = text.split("\n")
    if len(lines) < 5 or not _HEADER_FIRST.match(lines[0]) or tuple(lines[1:3]) != _HEADER_FIXED:
        return True
    stamp = _FINGERPRINT.match(lines[3])
    return stamp is None or fingerprint("\n".join(lines[:3] + lines[4:])) != stamp.group(1)


def _keep_copy(folder: LibraryFolder, data: bytes, today: date) -> Path:
    """Save the DJ's edited tree, byte for byte, under a new name. Create only: the name is
    taken with O_EXCL, so another file is never overwritten. The original is replaced only
    after this returns."""
    stem = f"current-tree.edited-{today.isoformat()}"
    n = 1
    while True:
        path = folder.structure / (f"{stem}.yaml" if n == 1 else f"{stem}-{n}.yaml")
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0))
        except FileExistsError:
            n += 1
            continue
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        return path


def _write_tree(folder: LibraryFolder, doc: treeschema.TreeDoc, *, source: str, today: date) -> tuple[Path, Path | None]:
    path = folder.structure / TREE_FILE
    text = tree_text(doc, source=source, today=today)
    kept = None
    if path.is_file():
        data = path.read_bytes()
        old = data.decode("utf-8", "replace")
        if old != text and _edited(old):
            kept = _keep_copy(folder, data, today)
    write_text(path, text)
    return path, kept


# -- writing and running -----------------------------------------------------------------------


def _folder(folder: LibraryFolder | str | Path) -> LibraryFolder:
    return folder if isinstance(folder, LibraryFolder) else LibraryFolder(Path(folder))


def _library_folder(folder: LibraryFolder | str | Path) -> LibraryFolder:
    """The folder, if it is a dj-library folder that dj-start set up: it exists and holds a
    valid library.yaml. Anything else -> LibraryFolderError before a single file is written, so
    a wrong --library never puts structure/ or a log.md line into some other folder."""
    folder = _folder(folder)
    name = folder.root.name or "The folder"
    if not folder.root.is_dir():
        raise LibraryFolderError(f"{name}: library folder not found. Run dj-start first.")
    if not folder.library_yaml.is_file():
        raise LibraryFolderError(
            f"{name} is not a dj-library folder (no library.yaml). "
            "Set it up with dj-start first. Nothing was written."
        )
    try:
        errors = validate_meta(load_meta(folder.root))
    except LibraryFolderError as exc:
        errors = [str(exc)]
    if errors:
        raise LibraryFolderError(
            f"{name}: library.yaml is not valid ({'; '.join(errors)}). "
            "Run dj-start on the folder first. Nothing was written."
        )
    return folder


def _json(data: Any) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def source_label(root: str | Path, source: str | Path) -> str:
    """The source as written into the folder's files: relative to the folder when it is inside,
    else its file name only. Never an absolute path (R-905)."""
    text = str(source).replace("\\", "/")
    absolute = Path(text).is_absolute() or text.startswith("/") or bool(_DRIVE.match(text))
    if not absolute:
        return text
    if Path(text).is_absolute():
        try:
            return relative(root, text)
        except LibraryError:
            pass
    return text.rstrip("/").rsplit("/", 1)[-1]


def write(
    folder: LibraryFolder | str | Path,
    facts: dict[str, Any],
    graph: dict[str, Any],
    doc: treeschema.TreeDoc,
    *,
    source: str,
    today: date | None = None,
) -> list[Path]:
    """Write structure/analysis.md, graph.json, facts.json and current-tree.yaml (tool-owned,
    rewritten each run, temp file + os.replace). facts.json also names the export it was
    measured from (`export`, relative), so dj-identity can tell facts of another export. If the DJ edited current-tree.yaml since the
    last run, their file is first copied to structure/current-tree.edited-<date>.yaml (create
    only); that copy is the fifth path returned. A folder that is not a dj-library folder ->
    LibraryFolderError, nothing written. Never touches rekordbox (R-341)."""
    folder = _library_folder(folder)
    today = today or date.today()
    source = source_label(folder.root, source)
    folder.structure.mkdir(parents=True, exist_ok=True)
    paths = [
        write_text(folder.structure / "analysis.md", render(facts, source=source, today=today)),
        write_text(folder.structure / "graph.json", _json(graph)),
        write_text(folder.structure / "facts.json", _json({**facts, "export": source})),
    ]
    tree_path, kept = _write_tree(folder, doc, source=source, today=today)
    paths.append(tree_path)
    if kept is not None:
        paths.append(kept)
    return paths


def run(
    folder: LibraryFolder | str | Path, *, xml: str | Path | None = None, today: date | None = None
) -> dict[str, Any]:
    """Read the latest export (or `xml`), measure, write structure/, append one log.md line.

    Returns {"written": [relative paths], "kept": [...], "source", "counts", "reveals", ...}.
    The folder must be a dj-library folder (library.yaml, see `_library_folder`); otherwise
    LibraryFolderError and nothing is written. Reads only the XML; never opens master.db,
    never writes to rekordbox (R-341).
    """
    folder = _library_folder(folder)
    today = today or date.today()
    path = Path(xml) if xml else latest_export(folder.root)
    lib = read_xml(path)
    source = source_label(folder.root, path.resolve())
    data = facts(lib, today=today)
    paths = write(folder, data, graph(lib), treeschema.from_library(lib, today=today), source=source, today=today)
    written = [relative(folder.root, p) for p in paths[: len(FILES)]]
    kept = [relative(folder.root, p) for p in paths[len(FILES):]]
    counts = data["counts"]
    log_counts = {
        "playlists": counts["playlists"] + counts["smart"],
        "folders": counts["folders"],
        "files": len(paths),
    }
    line = append_log(folder.root, "structure", log_counts, file="structure/analysis.md")
    return {
        "written": written,
        "kept": kept,
        "source": source,
        "counts": counts,
        "depth": data["depth"]["max"],
        "overlaps": data["overlap"]["count"],
        "dumps": data["dumps"]["count"],
        "orphans": data["orphans"]["count"],
        "empty": data["empty"]["count"],
        "reveals": data["reveals"],
        "log": line,
    }
