"""dj-report, part 1: two or three named restructure proposals from the DJ's own patterns
(R-404, R-405). Numbers and candidates come from code; Claude may rename them later (R-302).

Door 1 core: stdlib + PyYAML only (contract section 0). Works on a `dj.model.Library`; opens
no database and writes one text file inside the library folder (plus a kept copy, see below).

    candidates(lib, profile, structure, taste) -> list[Proposal]  2 or 3, pure, deterministic
    family_scores(lib, profile, structure)     -> the picking scores (below), with their parts
    write_proposals(folder, proposals, today)  -> structure/proposals.yaml (+ the DJ's kept copy)
    load(path)                                 -> the file as the report reads it, checked (2 or 3)
    run(folder)                                -> latest export -> candidates -> write -> log line

`profile`, `structure` and `taste` are the facts dicts of dj.analysis.profile / structure /
taste for the same Library. Any of them may be None: what is needed is then measured here from
`lib` with the same code, so the result is the same either way.

Families (R-405)
- bases: one base folder per main genre, each holding `0_INBOX` (new tracks; a dump lands here
  to be split by hand), `1_CRATES` (the DJ's crates, one playlist each) and `2_SETS` (gig and set
  playlists). A main genre holds at least 10% of the tracks that carry a genre; at most 5, the
  biggest first (when no genre reaches 10%, the 5 biggest).
- facets: `0_INBOX` for dumps, one shallow folder of genre shelves (genres with at least 2
  tracks, biggest first, 5 to 8), and a gigs folder with one crate per gig or set playlist (left
  out when there is none). The My Tag axes Role / Body / Vibe / Status are named in the principle
  for later: the XML export carries no My Tags and an XML import cannot set them. A library with
  fewer than 5 such genres scores 0 for facets (below), so facets comes only as the second of
  two proposals, with one shelf per genre it has.
- gig-first: `0_INBOX` for dumps, a gigs folder with one crate per residency or event, and an
  archive folder with every other playlist. Gig playlists are grouped by their name without
  dates, numbers and gig words: "Fabric 2024-05" and "Fabric 2024-09" share the crate "Fabric".
  No gig playlist yet: the gigs folder holds one empty playlist, "next gig".
A library with no genre at all builds bases and shelves from its BPM lanes (dj-taste), and with
no lane either from one group, the whole collection.

Picking rules (R-405). Every family gets a score from 0 to 100 from what the DJ already does:
- bases  = (G + N) // 2. G = % of tracks with a genre (the genre field is used); N = % of folder
  and playlist names that hold a genre word (a word of a genre tag in the collection, such as
  "house" in a folder "House" or "deep" in "deep_rollers"). 0 when no track has a genre.
- facets = spread + overlap + dumps, and 0 when fewer than 5 genres hold at least 2 tracks
  (R-405: 5 to 8 shelves). spread = 5 per genre with at least 2 tracks, at most 40 (8 genres);
  overlap = 10 per playlist pair sharing half its tracks or more and per playlist sitting
  entirely inside a bigger one (dj-structure), at most 30; dumps = 15 per dump (the
  dj-structure rule), at most 30.
- gig-first = min(100, 2 * D). D = % of folder and playlist names that are dated or venue-like:
  they hold a year (2025, 2025-03, 2025-03-14), an "@", or the word gig(s), set(s), night(s).
The families are ranked by score, ties in the order bases, facets, gig-first. Every family that
scores above 0 is proposed (3 at most); when fewer than 2 do, the top 2 are proposed anyway. The
first one is the report's recommendation.

Where existing playlists land (`lands`, one `{from, to}` per non-empty playlist, tree order)
- A playlist's genre is the genre (of the family's genres) most of its tracks carry; ties go to
  the bigger genre, then the earlier one. A playlist none of whose tracks carries one of those
  genres stays where it is.
- A dump (dj-structure rule) goes to 0_INBOX; a dated or venue-like playlist to the sets/gigs
  place of its family; any other playlist to a crate, shelf or the archive.
- `to` is "stays where it is" for a smart playlist (its rules stay in rekordbox), and for a
  playlist whose path cannot name it alone: a sibling with the same name, a "/" in a name, a
  blank name. Empty playlists are not listed.
- Every playlist that takes existing music carries `from`: the REAL rekordbox path
  "Folder/Playlist" (names trimmed), checked with `Library.node_at`, never the "Name (2)" that
  current-tree.yaml writes for a repeated name. Nothing existing is moved: the build makes copies.

Names, in the DJ's own words (Claude may rename them in the file later)
- "<Word> <Family>": `Bases`, `Facets`, `Gigs`. The words are the DJ's naming vocabulary (the
  dj-taste words: letters only, 3 or more, from folder and playlist names, top 20 by use), spelled
  as the DJ first spells them in the tree.
- bases: the first word of the biggest main genre that the DJ also uses in a name ("House
  Bases"); else that genre as tagged. facets: the DJ's most used word that is a genre word ("Deep
  Facets"); else the biggest shelf. gig-first: the most used word of the gig names once dates and
  gig words are gone ("Warehouse Gigs"). Fallbacks: "Genre Bases", "Genre Facets", "Gig-First".
- `slug`: the name folded to ASCII, lower case, runs of other characters as one "-"
  (^[a-z0-9]+(-[a-z0-9]+)*$), unique; the family's name when nothing is left.
- `trigger` = "Build me the <name> structure" (dj-build answers it).

New folder names follow the DJ's most common playlist-name pattern (dj-structure naming): its
separator and its case, so "word_word" gives "house_base" and "Word Word" gives "House Base".
`0_INBOX`, `1_CRATES` and `2_SETS` are written as they are. Names repeated in one folder get
" (2)", " (3)" (treeschema.level_names).

Every node of a proposal is new, so the build creates all of it and skips nothing: a top-level
name the DJ's tree already has at the top (case and outer spaces ignored, as treeschema.diff
compares; the real names and the " (2)" names of current-tree.yaml both count) becomes
"<name> (new)", then "<name> (new 2)" ... Everything below a new top-level node is new too.
`treeschema.diff(proposal.tree, treeschema.from_library(lib))` therefore holds CREATE rows only.

Cost: `cost_minutes = F + ceil(P / 2) + 2 * D`, counted on the CREATE rows of that diff: a
minute per folder to create (F), a minute per two playlists to import and check (P), two minutes
per dump to split by hand (D dumps that land in an inbox). At least 1.

structure/proposals.yaml is a list of mappings: slug, name, family, principle, cost_minutes,
trigger, lands, tree (the node list of the one tree schema, R-903). Four comment lines come
first; the last is a fingerprint of everything else, so the next run can tell whether the DJ or
Claude edited the file. An edited file is first kept, byte for byte, as
structure/proposals.edited-<date>.yaml (create only: -2, -3 ...), then the file is written anew.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
from collections import Counter
from dataclasses import dataclass, replace
from datetime import date, datetime, time
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import yaml

from dj import treeschema
from dj.analysis import structure as structure_analysis
from dj.analysis import taste as taste_analysis
from dj.analysis.common import fold, library_folder, pct, resolve_xml
from dj.libfolder import (
    LibraryFolder,
    LibraryFolderError,
    append_log,
    latest_export,
    relative,
    write_text,
)
from dj.model import Library, LibraryError, PlaylistNode, Track
from dj.readers.xml import read_xml
from dj.treeschema import TreeDoc, TreeNode, TreeSchemaError

MODULE = "dj.analysis.proposals"
PROPOSALS_YAML = "structure/proposals.yaml"
FAMILIES = ("bases", "facets", "gig-first")
NOUNS = {"bases": "Bases", "facets": "Facets", "gig-first": "Gigs"}
FALLBACK_NAMES = {"bases": "Genre Bases", "facets": "Genre Facets", "gig-first": "Gig-First"}
KEYS = ("slug", "name", "family", "principle", "cost_minutes", "trigger", "lands", "tree")
SLUG = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
STAYS = "stays where it is"
INBOX, CRATES, SETS = "0_INBOX", "1_CRATES", "2_SETS"
MIN_PROPOSALS, MAX_PROPOSALS = 2, 3
MAX_BASES = 5
BASE_PERCENT = 10  # a main genre holds at least this % of the genre-tagged tracks
MIN_SHELF_TRACKS = 2
MIN_SHELVES, MAX_SHELVES = 5, 8  # R-405: facets = 5 to 8 shallow genre buckets
SPREAD_POINTS, SPREAD_MAX = 5, 40
OVERLAP_POINTS, OVERLAP_MAX = 10, 30
DUMP_POINTS, DUMP_MAX = 15, 30
GIG_FACTOR = 2
MY_TAG_AXES = ("Role", "Body", "Vibe", "Status")
GIG_WORDS = frozenset({"gig", "gigs", "set", "sets", "night", "nights"})
NAMES_IN_LINE = 3  # names spelled out in a principle, then "and N more"

# The same year shape dj-structure counts as `dated`: 2025, 2025-03, 2025.03.14 (not "78-92").
_DATED = re.compile(r"(?<!\d)(?:19|20)\d{2}(?:[-./]\d{1,2}){0,2}(?![0-9A-Za-z])")
_TOKEN = re.compile(r"[^\W_]+")
_NOT_SLUG = re.compile(r"[^a-z0-9]+")
_WORD_SPLIT = re.compile(r"[\s/_]+")


class ProposalsError(LibraryError):
    """structure/proposals.yaml is not usable (broken YAML, a missing part, a bad tree)."""


@dataclass(frozen=True)
class Proposal:
    slug: str
    name: str
    family: str
    principle: str
    tree: TreeDoc
    lands: tuple[dict[str, str], ...]
    cost_minutes: int
    trigger: str
    score: int = 0  # the picking score (module docstring); not written to the file

    def data(self) -> dict[str, Any]:
        """The mapping written to structure/proposals.yaml, keys in file order."""
        tree = yaml.safe_load(treeschema.dumps(TreeDoc(self.tree.nodes)))
        return {
            "slug": self.slug,
            "name": self.name,
            "family": self.family,
            "principle": self.principle,
            "cost_minutes": self.cost_minutes,
            "trigger": self.trigger,
            "lands": [dict(row) for row in self.lands],
            "tree": tree,
        }

    def summary(self) -> dict[str, Any]:
        """Counts first, for a command's JSON output."""
        moved = sum(1 for row in self.lands if row["to"] != STAYS)
        return {
            "slug": self.slug,
            "name": self.name,
            "family": self.family,
            "score": self.score,
            "cost_minutes": self.cost_minutes,
            "lands": moved,
            "stays": len(self.lands) - moved,
            "trigger": self.trigger,
        }


def trigger_for(name: str) -> str:
    return f"Build me the {name} structure"


# -- reading the library ---------------------------------------------------------------------


def _norm(text: str) -> str:
    return " ".join(str(text or "").split())


@dataclass(frozen=True)
class _Group:
    """A genre (as tagged), a BPM lane, or the whole collection."""

    key: str
    label: str
    size: int
    kind: str  # "genre" | "lane" | "all"
    lo: int = 0
    hi: int = 0

    def holds(self, track: Track) -> bool:
        if self.kind == "genre":
            return _norm(track.genre).casefold() == self.key
        if self.kind == "lane":
            return track.bpm > 0 and self.lo <= math.floor(track.bpm + 0.5) <= self.hi
        return True


@dataclass(frozen=True)
class _Playlist:
    node: PlaylistNode
    shown: str  # the rekordbox path as the DJ sees it
    path: str | None  # the real path for `from`; None when it cannot name this playlist alone
    tracks: tuple[Track, ...]  # collection tracks, each once, playlist order
    dump: bool
    gig: bool

    @property
    def movable(self) -> bool:
        return self.path is not None and self.node.kind == "playlist"

    @property
    def name(self) -> str:
        return self.node.name.strip() or treeschema.UNNAMED


def _spelling(spellings: Counter) -> str:
    return sorted(spellings.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]


def _genres(lib: Library) -> list[_Group]:
    """Every genre in the collection, biggest first (ties by name), grouped case-insensitively."""
    counts: Counter = Counter()
    spellings: dict[str, Counter] = {}
    for track in lib.tracks.values():
        name = _norm(track.genre)
        if name:
            counts[name.casefold()] += 1
            spellings.setdefault(name.casefold(), Counter())[name] += 1
    rows = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [_Group(key, _spelling(spellings[key]), n, "genre") for key, n in rows]


def _real_path(lib: Library, node: PlaylistNode) -> str | None:
    """The path that `Library.node_at` resolves to exactly this node, or None."""
    parts = [part.strip() for part in node.path]
    if not parts or any(not part or "/" in part for part in parts):
        return None
    path = "/".join(parts)
    try:
        found = lib.node_at(path)
    except LibraryError:
        return None
    return path if found is node else None


def gig_like(name: str) -> bool:
    """Dated or venue-like: a year (2025, 2025-03), an "@", or gig(s), set(s), night(s)."""
    if "@" in name or _DATED.search(name):
        return True
    return any(word.casefold() in GIG_WORDS for word in _TOKEN.findall(name))


def dump_ids(lib: Library) -> set[str]:
    """Ids of the dumps, by the dj-structure rule (structure.DUMP_*), over the playlists whose
    tracks the source lists."""
    measured = [n for n in lib.playlists() if n.kind == "playlist" or (n.kind == "smart" and n.track_ids)]
    total = len(lib.tracks)
    held = [len(set(n.track_ids) & lib.tracks.keys()) for n in measured]
    out = set()
    for k, node in enumerate(measured):
        share = held[k] / total if total else 0.0
        if len(node.track_ids) > structure_analysis.DUMP_TRACKS or share > structure_analysis.DUMP_HALF:
            out.add(node.id)
            continue
        if share <= structure_analysis.DUMP_SHARE:
            continue
        others = sorted(h for j, h in enumerate(held) if j != k and h)
        if others:
            mid = len(others) // 2
            median = others[mid] if len(others) % 2 else (others[mid - 1] + others[mid]) / 2
            if held[k] > structure_analysis.DUMP_MEDIAN_FACTOR * median:
                out.add(node.id)
    return out


def _playlists(lib: Library) -> list[_Playlist]:
    """Non-empty playlists in tree order, plus every smart playlist (they stay where they are)."""
    dumps = dump_ids(lib)
    out = []
    for node in lib.playlists():
        tracks = tuple(lib.tracks[i] for i in dict.fromkeys(node.track_ids) if i in lib.tracks)
        if node.kind == "playlist" and not tracks:
            continue
        out.append(_Playlist(node, node.path_str, _real_path(lib, node), tracks, node.id in dumps,
                             gig_like(node.name)))  # fmt: skip
    return out


def _names(lib: Library) -> list[str]:
    return [n.name.strip() for n in lib.walk() if n.name.strip()]


def _vocabulary(lib: Library, taste: Mapping[str, Any] | None) -> list[str]:
    """The DJ's naming words, most used first (ties by word): dj-taste's vocabulary top."""
    top = ((taste or {}).get("vocabulary") or {}).get("top")
    if isinstance(top, list):
        return [str(row["word"]) for row in top if isinstance(row, Mapping) and row.get("word")]
    counts: Counter = Counter()
    for node in lib.walk():
        counts.update(taste_analysis.words_of(node.name))
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[: taste_analysis.TOP_WORDS]
    return [word for word, _n in ranked]


def _spell(word: str, names: Iterable[str]) -> str:
    """`word` as the DJ first writes it in a name (tree order); a lower-case one capitalised."""
    for name in names:
        for token in _TOKEN.findall(name):
            if token.casefold() == word:
                return token[:1].upper() + token[1:] if token.islower() else token
    return word[:1].upper() + word[1:]


def _capitalised(text: str) -> str:
    return text[:1].upper() + text[1:] if text[:1].islower() else text


# -- naming style ----------------------------------------------------------------------------


def _style(naming: Mapping[str, Any] | None) -> tuple[str, str]:
    """(case, separator) of the DJ's most common playlist-name pattern (dj-structure)."""
    naming = naming or {}
    pattern = str(naming.get("dominant") or "")
    if " - " in pattern:
        sep = " "
    elif "_" in pattern:
        sep = "_"
    elif "-" in pattern:
        sep = "-"
    elif " " in pattern:
        sep = " "
    else:  # a one-word pattern: the separator the names use most
        counts = naming.get("separators") or {}
        options = [("underscore", "_"), ("hyphen", "-"), ("space", " ")]
        best = max(options, key=lambda kv: int(counts.get(kv[0]) or 0))  # ties: the order above
        sep = best[1] if int(counts.get(best[0]) or 0) else "_"
    words = [w for w in re.split(r" - |[_\- ]", pattern) if w]
    first = words[0] if words else ""
    if first == "word":
        case = "lower"
    elif first == "WORD":
        case = "upper"
    elif first == "Word":
        case = "sentence" if len(words) > 1 and words[1] == "word" else "title"
    else:
        case = "lower" if not pattern else "keep"
    return case, sep


def _styled(words: Sequence[str], style: tuple[str, str]) -> str:
    case, sep = style
    words = [w for w in words if w]
    if case == "lower":
        out = [w.lower() for w in words]
    elif case == "upper":
        out = [w.upper() for w in words]
    elif case == "title":
        out = [w[:1].upper() + w[1:] for w in words]
    elif case == "sentence":
        out = [w.lower() for w in words]
        out[:1] = [out[0][:1].upper() + out[0][1:]] if out else []
    else:
        out = list(words)
    return sep.join(out) or treeschema.UNNAMED


def _label_words(label: str) -> list[str]:
    return [w for w in _WORD_SPLIT.split(label) if any(c.isalnum() for c in w)]


def _node_name(text: str) -> str:
    """A name a tree file can hold as one node: one line, no "/", trimmed, never blank."""
    return _norm(text).replace("/", "-").strip() or treeschema.UNNAMED


# -- the context every family is built from --------------------------------------------------


@dataclass(frozen=True)
class _Context:
    lib: Library
    playlists: tuple[_Playlist, ...]
    genres: tuple[_Group, ...]
    groups_bases: tuple[_Group, ...]
    groups_shelves: tuple[_Group, ...]
    style: tuple[str, str]
    vocabulary: tuple[str, ...]
    names: tuple[str, ...]
    current: tuple[TreeNode, ...]  # the DJ's tree as current-tree.yaml holds it
    top_inbox: str  # the name of a top-level 0_INBOX: "0_INBOX", or "0_INBOX (new)" when taken


def _fallback_groups(lib: Library, taste: Mapping[str, Any] | None) -> list[_Group]:
    """No genre at all: the BPM lanes of dj-taste, else the whole collection as one group."""
    lanes = taste["lanes"] if taste and "lanes" in taste else taste_analysis.facts(lib)["lanes"]
    groups = [
        _Group(f"lane:{lane['label']}", str(lane["label"]), int(lane.get("tracks") or 0), "lane",
               int(lane["lo"]), int(lane["hi"]))
        for lane in lanes or ()
        if isinstance(lane, Mapping) and {"label", "lo", "hi"} <= set(lane)
    ]  # fmt: skip
    groups.sort(key=lambda g: (-g.size, g.lo, g.hi))
    return groups or [_Group("all", "collection", len(lib.tracks), "all")]


def _context(lib: Library, structure: Mapping[str, Any] | None, taste: Mapping[str, Any] | None) -> _Context:
    genres = _genres(lib)
    if genres:
        tagged = sum(g.size for g in genres)
        main = [g for g in genres if g.size * 100 >= BASE_PERCENT * tagged] or genres
        bases = main[:MAX_BASES]
        shelves = ([g for g in genres if g.size >= MIN_SHELF_TRACKS] or genres)[:MAX_SHELVES]
    else:
        bases = shelves = _fallback_groups(lib, taste)[:MAX_SHELVES]
        bases = bases[:MAX_BASES]
    naming = (structure if structure else structure_analysis.facts(lib)).get("naming")
    current = treeschema.from_library(lib).nodes
    return _Context(
        lib=lib,
        playlists=tuple(_playlists(lib)),
        genres=tuple(genres),
        groups_bases=tuple(bases),
        groups_shelves=tuple(shelves),
        style=_style(naming),
        vocabulary=tuple(_vocabulary(lib, taste)),
        names=tuple(_names(lib)),
        current=current,
        top_inbox=free_name(INBOX, taken_at_top(current, lib)),
    )


def _dominant(groups: Sequence[_Group], tracks: Sequence[Track]) -> _Group | None:
    """The group most of `tracks` belong to; ties: the bigger group, then the earlier one."""
    best, best_n = None, 0
    for group in groups:  # groups come biggest first, so `>` keeps the earlier on a tie
        n = sum(1 for t in tracks if group.holds(t))
        if n > best_n:
            best, best_n = group, n
    return best


# -- picking (R-405) -------------------------------------------------------------------------


def _genre_words(genres: Iterable[_Group]) -> set[str]:
    return {w for g in genres if g.kind == "genre" for w in taste_analysis.words_of(g.label)}


def family_scores(
    lib: Library, profile: Mapping[str, Any] | None = None, structure: Mapping[str, Any] | None = None
) -> dict[str, dict[str, int]]:
    """{family: {"score": 0-100, <its parts>}} by the picking rules in the module docstring."""
    tracks = list(lib.tracks.values())
    genres = _genres(lib)
    names = _names(lib)
    share = ((profile or {}).get("fields") or {}).get("genre") if profile is not None else None
    if isinstance(share, Mapping) and isinstance(share.get("pct"), int):
        genre_field = share["pct"]
    else:
        genre_field = pct(sum(1 for t in tracks if _norm(t.genre)), len(tracks))
    words = _genre_words(genres)
    genre_names = pct(sum(1 for n in names if words & set(taste_analysis.words_of(n))), len(names))
    bases = (genre_field + genre_names) // 2 if genres else 0

    if not structure:
        structure = structure_analysis.facts(lib)
    overlap = structure.get("overlap") or {}
    pairs = int(overlap.get("count") or 0) + int((overlap.get("contained") or {}).get("count") or 0)
    dumps = len(dump_ids(lib))
    shelves = sum(1 for g in genres if g.size >= MIN_SHELF_TRACKS)
    spread = min(SPREAD_MAX, SPREAD_POINTS * shelves)
    overlap_points = min(OVERLAP_MAX, OVERLAP_POINTS * pairs)
    dump_points = min(DUMP_MAX, DUMP_POINTS * dumps)
    facets = spread + overlap_points + dump_points if shelves >= MIN_SHELVES else 0

    gig_names = pct(sum(1 for n in names if gig_like(n)), len(names))
    return {
        "bases": {"score": bases, "genre_field": genre_field, "genre_names": genre_names},
        "facets": {"score": facets, "shelves": shelves, "spread": spread,
                   "overlap": overlap_points, "dumps": dump_points},  # fmt: skip
        "gig-first": {"score": min(100, GIG_FACTOR * gig_names), "gig_names": gig_names},
    }


def pick(scores: Mapping[str, Mapping[str, int]]) -> list[str]:
    """The families to propose, best first (module docstring: 2 or 3)."""
    ranked = sorted(FAMILIES, key=lambda f: (-scores[f]["score"], FAMILIES.index(f)))
    chosen = [f for f in ranked if scores[f]["score"] > 0][:MAX_PROPOSALS]
    return chosen if len(chosen) >= MIN_PROPOSALS else ranked[:MIN_PROPOSALS]


# -- building the trees ----------------------------------------------------------------------


class _Lands:
    """Where each existing playlist ends up: node id -> new path."""

    def __init__(self) -> None:
        self.to: dict[str, str] = {}

    def playlists(self, entries: Sequence[tuple[str, Sequence[_Playlist]]], prefix: str) -> tuple[TreeNode, ...]:
        """New playlists (wanted name, sources) under `prefix`, names made unique at the level."""
        names = treeschema.level_names([_node_name(name) for name, _sources in entries])
        out = []
        for name, (_wanted, sources) in zip(names, entries):
            for source in sources:
                self.to[source.node.id] = f"{prefix}/{name}" if prefix else name
            out.append(TreeNode("playlist", name, fill_from=tuple(s.path for s in sources if s.path)))
        return tuple(out)

    def rows(self, playlists: Sequence[_Playlist]) -> tuple[dict[str, str], ...]:
        return tuple({"from": p.path or p.shown, "to": self.to.get(p.node.id, STAYS)} for p in playlists)


def _inbox(lands: _Lands, dumps: Sequence[_Playlist], prefix: str = "", name: str = INBOX) -> TreeNode:
    for p in dumps:
        lands.to[p.node.id] = f"{prefix}/{name}" if prefix else name
    return TreeNode("playlist", name, fill_from=tuple(p.path for p in dumps if p.path))


def _list_names(names: Sequence[str]) -> str:
    shown = ", ".join(names[:NAMES_IN_LINE])
    return shown + (f" and {len(names) - NAMES_IN_LINE} more" if len(names) > NAMES_IN_LINE else "")


def _group_words(groups: Sequence[_Group]) -> tuple[str, str]:
    """('main genre', 'genres') or the lane / collection wording, for a principle line."""
    kind = groups[0].kind if groups else "all"
    return {"genre": ("main genre", "genre"), "lane": ("BPM lane", "BPM lane")}.get(kind, ("group", "group"))


def _build_bases(ctx: _Context) -> tuple[list[TreeNode], _Lands, str]:
    groups = ctx.groups_bases
    lands = _Lands()
    slots: dict[str, dict[str, list[_Playlist]]] = {g.key: {"inbox": [], "crates": [], "sets": []} for g in groups}
    for p in ctx.playlists:
        group = _dominant(groups, p.tracks) if p.movable else None
        if group is None:
            continue
        slots[group.key]["inbox" if p.dump else "sets" if p.gig else "crates"].append(p)
    bases = treeschema.level_names([_styled(_label_words(g.label) + ["base"], ctx.style) for g in groups])
    nodes = []
    for group, base in zip(groups, bases):
        slot = slots[group.key]
        crates = lands.playlists([(p.name, [p]) for p in slot["crates"]], f"{base}/{CRATES}")
        sets = lands.playlists([(p.name, [p]) for p in slot["sets"]], f"{base}/{SETS}")
        nodes.append(TreeNode("folder", base, children=(
            _inbox(lands, slot["inbox"], base),
            TreeNode("folder", CRATES, children=crates),
            TreeNode("folder", SETS, children=sets),
        )))  # fmt: skip
    one, _many = _group_words(groups)
    principle = (
        f"One base per {one} ({_list_names([g.label for g in groups])}): new tracks land in {INBOX}, "
        f"your crates sit in {CRATES}, gigs and sets in {SETS}."
    )
    return nodes, lands, principle


def _build_facets(ctx: _Context) -> tuple[list[TreeNode], _Lands, str]:
    groups = ctx.groups_shelves
    lands = _Lands()
    dumps, gigs = [], []
    shelves: dict[str, list[_Playlist]] = {g.key: [] for g in groups}
    for p in ctx.playlists:
        if not p.movable:
            continue
        if p.dump:
            dumps.append(p)
        elif p.gig:
            gigs.append(p)
        else:
            group = _dominant(groups, p.tracks)
            if group is not None:
                shelves[group.key].append(p)
    shelf_folder = _styled(["genres"] if groups and groups[0].kind == "genre" else ["shelves"], ctx.style)
    gig_folder = _styled(["gigs"], ctx.style)
    nodes = [
        _inbox(lands, dumps, name=ctx.top_inbox),
        TreeNode("folder", shelf_folder,
                 children=lands.playlists([(g.label, shelves[g.key]) for g in groups], shelf_folder)),
    ]  # fmt: skip
    if gigs:
        nodes.append(TreeNode("folder", gig_folder, children=lands.playlists([(p.name, [p]) for p in gigs], gig_folder)))
    _one, many = _group_words(groups)
    shelves = f"{len(groups)} shallow {many} {'shelf' if len(groups) == 1 else 'shelves'}"
    inside = "it" if len(groups) == 1 else "them"
    beside = f" and your gig crates beside {inside}" if gigs else ""
    principle = (
        f"{shelves} ({_list_names([g.label for g in groups])}){beside}; "
        f"My Tags ({', '.join(MY_TAG_AXES)}) sort inside {inside} later."
    )
    return nodes, lands, principle


def event_of(name: str) -> tuple[str, str]:
    """(key, crate name) of a gig playlist: its words without dates, numbers and gig words.
    "Gig 2025-03 Warehouse" -> ("warehouse", "Warehouse"). Nothing left -> the whole name."""
    tokens = [
        t for t in _TOKEN.findall(_DATED.sub(" ", name))
        if not t.isdigit() and t.casefold() not in GIG_WORDS and t.casefold() not in taste_analysis.STOP_WORDS
    ]  # fmt: skip
    if not tokens:
        return _norm(name).casefold(), _norm(name)
    return " ".join(t.casefold() for t in tokens), " ".join(tokens)


def _build_gig_first(ctx: _Context) -> tuple[list[TreeNode], _Lands, str]:
    lands = _Lands()
    dumps, archive = [], []
    events: dict[str, tuple[str, list[_Playlist]]] = {}
    for p in ctx.playlists:
        if not p.movable:
            continue
        if p.dump:
            dumps.append(p)
        elif p.gig:
            key, crate = event_of(p.name)
            events.setdefault(key, (crate, []))[1].append(p)
        else:
            archive.append(p)
    gig_folder = _styled(["gigs"], ctx.style)
    archive_folder = _styled(["archive"], ctx.style)
    entries = list(events.values()) or [(_styled(["next", "gig"], ctx.style), [])]
    nodes = [_inbox(lands, dumps, name=ctx.top_inbox),
             TreeNode("folder", gig_folder, children=lands.playlists(entries, gig_folder))]  # fmt: skip
    if archive:
        nodes.append(TreeNode("folder", archive_folder,
                              children=lands.playlists([(p.name, [p]) for p in archive], archive_folder)))  # fmt: skip
    crates = len(events)
    what = f"{crates} {'crate' if crates == 1 else 'crates'}" if crates else "none yet"
    rest = ", everything else in an archive" if archive else ""
    principle = f"A crate per residency or event ({what}){rest}; new tracks wait in {ctx.top_inbox}."
    return nodes, lands, principle


_BUILDERS = {"bases": _build_bases, "facets": _build_facets, "gig-first": _build_gig_first}


# -- names, slugs, cost ----------------------------------------------------------------------


def _word_bases(ctx: _Context) -> str | None:
    vocabulary = set(ctx.vocabulary)
    for group in ctx.groups_bases:
        if group.kind != "genre":
            continue
        for word in taste_analysis.words_of(group.label):
            if word in vocabulary:
                return _spell(word, ctx.names)
    first = ctx.groups_bases[0] if ctx.groups_bases else None
    return _capitalised(first.label) if first is not None and first.kind != "all" else None


def _word_facets(ctx: _Context) -> str | None:
    genre_words = _genre_words(ctx.genres)
    for word in ctx.vocabulary:
        if word in genre_words:
            return _spell(word, ctx.names)
    first = ctx.groups_shelves[0] if ctx.groups_shelves else None
    return _capitalised(first.label) if first is not None and first.kind != "all" else None


def _word_gig_first(ctx: _Context) -> str | None:
    counts: Counter = Counter()
    order: dict[str, int] = {}
    spelled: list[str] = []
    for name in ctx.names:
        if not gig_like(name):
            continue
        rest = " ".join(t for t in _TOKEN.findall(_DATED.sub(" ", name)) if t.casefold() not in GIG_WORDS)
        for word in taste_analysis.words_of(rest):
            counts[word] += 1
            order.setdefault(word, len(order))
        spelled.append(rest)
    if not counts:
        return None
    word = min(counts, key=lambda w: (-counts[w], order[w]))
    return _spell(word, spelled)


_WORDS = {"bases": _word_bases, "facets": _word_facets, "gig-first": _word_gig_first}


def slug_of(name: str, fallback: str) -> str:
    slug = _NOT_SLUG.sub("-", fold(name)).strip("-")
    return slug if SLUG.match(slug) else fallback


def free_name(name: str, taken: Iterable[str]) -> str:
    """`name`, else "<name> (new)", "<name> (new 2)" ...: the first whose treeschema.norm is not in
    `taken` (a set of normed names)."""
    taken = set(taken)
    candidate, n = name, 1
    while treeschema.norm(candidate) in taken:
        candidate = f"{name} (new)" if n == 1 else f"{name} (new {n})"
        n += 1
    return candidate


def taken_at_top(current: Sequence[TreeNode], lib: Library) -> set[str]:
    """The normed names at the top of the DJ's tree: as rekordbox holds them and as
    current-tree.yaml writes them (a repeated name there is "Name (2)")."""
    return {treeschema.norm(n.name) for n in current} | {treeschema.norm(n.name) for n in lib.roots}


def _clear_of(nodes: Sequence[TreeNode], lands: _Lands, taken: set[str]) -> list[TreeNode]:
    """The top-level nodes, each renamed by `free_name` when the DJ's tree already has its name at
    the top, so the build creates every node; `lands` follows the new names."""
    used = set(taken)
    out: list[TreeNode] = []
    renames: dict[str, str] = {}
    for node in nodes:
        name = free_name(node.name, used)
        used.add(treeschema.norm(name))
        if name != node.name:
            renames[node.name] = name
            node = replace(node, name=name)
        out.append(node)
    for key, path in list(lands.to.items()):
        head, sep, rest = path.partition("/")
        if head in renames:
            lands.to[key] = renames[head] + sep + rest
    return out


def cost_of(nodes: Sequence[TreeNode], dumps: int, current: Sequence[TreeNode] | None = None) -> int:
    """F + ceil(P / 2) + 2 * D over the CREATE rows of `treeschema.diff(nodes, current)`, at least
    1 (module docstring)."""
    rows = treeschema.diff(nodes, current)
    kinds = Counter(row.kind for row in rows if row.op == treeschema.CREATE)
    return max(1, kinds["folder"] + math.ceil(kinds["playlist"] / 2) + 2 * dumps)


def candidates(
    lib: Library,
    profile: Mapping[str, Any] | None = None,
    structure: Mapping[str, Any] | None = None,
    taste: Mapping[str, Any] | None = None,
) -> list[Proposal]:
    """2 or 3 proposals, the recommended one first (rules: module docstring). Pure."""
    if not structure:
        structure = structure_analysis.facts(lib)
    scores = family_scores(lib, profile, structure)
    ctx = _context(lib, structure, taste)
    out: list[Proposal] = []
    slugs: set[str] = set()
    taken = taken_at_top(ctx.current, lib)
    for family in pick(scores):
        nodes, lands, principle = _BUILDERS[family](ctx)
        nodes = _clear_of(nodes, lands, taken)
        word = _WORDS[family](ctx)
        name = _norm(f"{word} {NOUNS[family]}") if word else FALLBACK_NAMES[family]
        slug, n = slug_of(name, family), 2
        base = slug
        while slug in slugs:
            slug, n = f"{base}-{n}", n + 1
        slugs.add(slug)
        dumps = sum(1 for p in ctx.playlists if p.dump and p.node.id in lands.to)
        tree = TreeDoc(tuple(nodes), {"name": name, "family": family, "principle": principle})
        out.append(Proposal(
            slug=slug, name=name, family=family, principle=principle, tree=tree,
            lands=lands.rows(ctx.playlists), cost_minutes=cost_of(nodes, dumps, ctx.current),
            trigger=trigger_for(name),
            score=scores[family]["score"],
        ))  # fmt: skip
    return out


# -- structure/proposals.yaml ----------------------------------------------------------------


class _Dumper(yaml.SafeDumper):
    """The safe dumper, list items indented under their key, no &anchors (as treeschema)."""

    def increase_indent(self, flow: bool = False, indentless: bool = False) -> Any:
        return super().increase_indent(flow, False)

    def ignore_aliases(self, data: Any) -> bool:
        return True


def _represent_str(dumper: yaml.SafeDumper, data: str) -> yaml.ScalarNode:
    style = '"' if "\x85" in data else None  # NEL reads back as a space unless double-quoted
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


_Dumper.add_representer(str, _represent_str)

_HEAD_FIRST = re.compile(r"^# Restructure proposals for your library, generated from .+ on \d{4}-\d{2}-\d{2}\.$")
_HEAD_FIXED = (
    "# Rename a proposal or change its tree here, then render the report again: it shows this file.",
    '# Keep each trigger "Build me the <name> structure". The next propose run rewrites this file; a copy you edited is kept first.',
)
_FINGERPRINT = re.compile(r"^# fingerprint: ([0-9a-f]{12})\s*$")


def _fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def dumps(proposals: Sequence[Proposal], *, source: str, today: date) -> str:
    """The text of structure/proposals.yaml. Checked: it reads back as the same proposals."""
    data = [p.data() for p in proposals]
    body = yaml.dump(data, Dumper=_Dumper, sort_keys=False, allow_unicode=True, default_flow_style=False, width=4096)
    back = yaml.safe_load(body)
    for proposal, entry in zip(proposals, back or []):
        if treeschema.parse(entry["tree"], "proposals") != TreeDoc(proposal.tree.nodes):
            raise ProposalsError(f"{proposal.slug}: the tree would read back changed")
    if back != data:
        raise ProposalsError("the proposals would read back changed")
    head = (
        f"# Restructure proposals for your library, generated from {_norm(source)} on {today.isoformat()}.\n"
        f"{_HEAD_FIXED[0]}\n{_HEAD_FIXED[1]}\n"
    )
    return f"{head}# fingerprint: {_fingerprint(head + body)}\n{body}"


def edited(text: str) -> bool:
    """True unless the file is exactly what the tool wrote (header shape and fingerprint)."""
    lines = text.split("\n")
    if len(lines) < 5 or not _HEAD_FIRST.match(lines[0]) or tuple(lines[1:3]) != _HEAD_FIXED:
        return True
    stamp = _FINGERPRINT.match(lines[3])
    return stamp is None or _fingerprint("\n".join(lines[:3] + lines[4:])) != stamp.group(1)


def _keep_copy(folder: LibraryFolder, data: bytes, today: date) -> Path:
    """The edited file, byte for byte, under a new name; O_EXCL, so nothing is overwritten."""
    stem = f"proposals.edited-{today.isoformat()}"
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


def write_proposals(
    folder: LibraryFolder | str | Path,
    proposals: Sequence[Proposal],
    today: date | None = None,
    *,
    source: str = "the latest export",
) -> list[Path]:
    """Write structure/proposals.yaml; returns [it] or [it, the kept copy of an edited file].
    `source` (relative to the folder) is named in the first comment line. Only into a
    scaffolded dj-library (`common.library_folder`)."""
    folder = library_folder(folder)
    today = today or date.today()
    if not source.strip() or "\n" in source or source.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", source):
        raise ValueError(f"source must be a path relative to the library folder, got {source!r}")
    text = dumps(proposals, source=source, today=today)
    folder.structure.mkdir(parents=True, exist_ok=True)
    path = folder.root / PROPOSALS_YAML
    kept = None
    if path.is_file():
        data = path.read_bytes()
        old = data.decode("utf-8", "replace")
        if old != text and edited(old):
            kept = _keep_copy(folder, data, today)
    write_text(path, text)
    return [path] if kept is None else [path, kept]


def _one_line(value: Any, where: str, key: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\n" in value or "\r" in value:
        raise ProposalsError(f"{where}: `{key}` must be one line of text, got {value!r}")
    return value.strip()


def load(path: str | Path) -> list[dict[str, Any]]:
    """structure/proposals.yaml, checked part by part. Each entry comes back with `tree` as a
    TreeDoc. Fewer than 2 or more than 3 proposals (an empty file too), a missing part, an
    unknown key, a slug off the pattern or used twice, a name used twice (case ignored), a
    trigger that is not "Build me the <name> structure" or a tree that breaks the schema ->
    ProposalsError naming the proposal and the part."""
    path = Path(path)
    where_file = PROPOSALS_YAML if path.name == "proposals.yaml" else path.name
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ProposalsError(f"{where_file}: not valid YAML: {exc}") from exc
    except UnicodeDecodeError as exc:
        raise ProposalsError(f"{where_file}: not UTF-8 text") from exc
    if data is None:
        data = []
    if not isinstance(data, list):
        raise ProposalsError(f"{where_file}: expected a list of proposals")
    if not MIN_PROPOSALS <= len(data) <= MAX_PROPOSALS:
        raise ProposalsError(
            f"{where_file}: {len(data)} proposals; the report shows {MIN_PROPOSALS} or {MAX_PROPOSALS}"
        )
    out, slugs, names = [], set(), {}
    for n, entry in enumerate(data, 1):
        where = f"{where_file}: proposal {n}"
        if not isinstance(entry, dict):
            raise ProposalsError(f"{where}: expected a mapping with {', '.join(KEYS)}")
        missing = [k for k in KEYS if k not in entry]
        unknown = sorted(map(str, set(entry) - set(KEYS)))
        if missing or unknown:
            parts = ([f"missing {', '.join(missing)}"] if missing else []) + (
                [f"unknown {', '.join(unknown)}"] if unknown else [])  # fmt: skip
            raise ProposalsError(f"{where}: {'; '.join(parts)}")
        slug = entry["slug"]
        if not isinstance(slug, str) or not SLUG.match(slug) or slug in slugs:
            raise ProposalsError(f"{where}: slug {slug!r} must be unique and match {SLUG.pattern}")
        slugs.add(slug)
        name = _one_line(entry["name"], where, "name")
        if name.casefold() in names:
            raise ProposalsError(
                f"{where}: name {name!r} is also proposal {names[name.casefold()]}'s; each name and "
                "its trigger must be unique"
            )
        names[name.casefold()] = n
        if entry["family"] not in FAMILIES:
            raise ProposalsError(f"{where}: family must be one of {', '.join(FAMILIES)}")
        principle = _one_line(entry["principle"], where, "principle")
        cost = entry["cost_minutes"]
        if isinstance(cost, bool) or not isinstance(cost, int) or cost < 0:
            raise ProposalsError(f"{where}: cost_minutes must be a whole number of minutes, got {cost!r}")
        if entry["trigger"] != trigger_for(name):
            raise ProposalsError(f"{where}: trigger must be exactly {trigger_for(name)!r} (rename both together)")
        lands = entry["lands"]
        if not isinstance(lands, list) or not all(
            isinstance(row, dict) and set(row) == {"from", "to"} and all(isinstance(v, str) for v in row.values())
            for row in lands
        ):
            raise ProposalsError(f"{where}: lands must be a list of {{from, to}} text pairs")
        if not isinstance(entry["tree"], list):
            raise ProposalsError(f"{where}: tree must be a list of nodes")
        try:
            tree = treeschema.parse(entry["tree"], where)
        except TreeSchemaError as exc:
            raise ProposalsError(str(exc)) from exc
        out.append({
            "slug": slug, "name": name, "family": entry["family"], "principle": principle,
            "cost_minutes": cost, "trigger": entry["trigger"], "lands": lands, "tree": tree,
        })  # fmt: skip
    return out


# -- running ---------------------------------------------------------------------------------


def source_name(folder: LibraryFolder, path: Path) -> str:
    """The export relative to the folder; an XML outside it by its file name only."""
    try:
        return relative(folder.root, path)
    except LibraryFolderError:
        return path.name


def read_export(folder: LibraryFolder, xml: str | Path | None = None) -> tuple[Library, str]:
    """The Library of the latest export (or `xml`) and its name relative to the folder."""
    path = resolve_xml(folder.root, xml) if xml else latest_export(folder.root)
    return read_xml(path), source_name(folder, path)


def log_time(today: date | None) -> datetime | None:
    return datetime.combine(today, time()) if today else None


def run(folder: LibraryFolder | str | Path, *, xml: str | Path | None = None, today: date | None = None) -> dict[str, Any]:
    """Read the latest export (or `xml`), build the candidates, write structure/proposals.yaml,
    append one log.md line. Returns counts first, then the proposals, written and kept files.
    A folder without a valid library.yaml -> common.NotALibraryFolder, nothing written."""
    folder = library_folder(folder)
    lib, source = read_export(folder, xml)
    proposals = candidates(lib)
    paths = write_proposals(folder, proposals, today, source=source)
    line = append_log(folder.root, "proposals", {"proposals": len(proposals)}, PROPOSALS_YAML, now=log_time(today))
    return {
        "counts": {"proposals": len(proposals), "files": len(paths)},
        "source": source,
        "proposals": [p.summary() for p in proposals],
        "written": [folder.relative(paths[0])],
        "kept": [folder.relative(p) for p in paths[1:]],
        "log": line,
    }
