"""dj-taste: the DJ's taste measured from the library (R-331), kept in `taste/` (R-332).

Door 1 core: stdlib + PyYAML only (contract section 0). `facts` is pure, `write` appends to the
taste files through `dj.taste_files` (never regenerates them), `run` reads the export, computes,
writes and logs. Measured facts come from code; the words around them come from Claude (R-302).
Nothing here writes to rekordbox, Spotify or audio files (R-341): it reads an XML export and
writes text files under `taste/` plus one `log.md` line (and on a rebuild a copy of the old
taste files under `.cache/`).

What is measured. Every sort has an explicit tie-break (name, then track id), so the same
library always gives the same facts.

- labels: the top 20 labels by tracks, each with its playlist count, its top 3 artists and its
  cluster. Names are grouped case-insensitively; the most common spelling is shown.
- artists: the top 20 by tracks and the top 20 by the number of playlists they appear in.
- lanes: for each playlist with >= 3 BPM-tagged tracks, the median and the middle half
  (25th to 75th percentile, linear interpolation, rounded half up to whole BPM). A playlist whose
  middle half spans more than 12 BPM is mixed (a dump or a whole-night set), not a lane. The other
  ranges, taken by their low end, join the lane before them when they overlap it by more than a
  boundary BPM or when one holds the other ("119-122" and "122-124" stay two lanes; "124-124"
  joins "124-124" and "122-122" joins "120-122"), and only while the lane stays within 12 BPM, so
  a ladder of overlapping ranges (deep house up to hard techno) never collapses into one lane.
  A lane is labelled by its range ("119-122") and keyed by its biggest playlist, so its key
  survives a range that shifts by a BPM.
- keys: the top keys by tracks, and the minor/major share. Classic ("Am", "F#"), Camelot ("8A")
  and Open Key ("1m") notation are read; anything else counts as unknown.
- cooccurrence: track pairs that sit together in >= 2 playlists, with counts. Playlists over
  100 tracks are skipped here (crates or dumps; their pairs would be noise and grow with the
  square of the size). `top` holds the 20 strongest with names; `pairs` holds the 5,000
  strongest as `[a, b, count]` (`count` is how many pairs there are in all, `kept` how many are
  listed), which is what `cooccurrence.json` gets, one pair per line.
- clusters: each track stands for its label, or its artist when the label is empty. Greedy and
  deterministic: take the name with the most tracks, pull in every unassigned name whose
  playlists overlap its playlists with Jaccard >= 0.5, repeat with the next unassigned name.
  Only playlists that are not mixed count (a dump says nothing about what sounds alike); a name
  that appears in none of them joins no cluster; clusters of one track are left out. A cluster
  is named after its biggest label, else its biggest artist.
- top_rated (rating >= 4) and most_played (play count): the top 20 each.
- anchors: 1-3 per cluster. Ranked by rating, then play count, then co-occurrence degree (how
  many tracks it pairs with), then track id. The first is always an anchor; the second and third
  only with >= 4 stars. A duplicate (same artist and title) of an anchor is skipped.
- vocabulary: words from folder and playlist names: lower case, letters only, >= 3 letters,
  numbers and separators dropped, stop words and tool words ("untitled", "playlist") dropped.
  Count = how many names use the word. Top 20, each with up to 3 example paths.

Files (`write`): `taste/lanes.md`, `labels-artists.md`, `anchors.md`, `vocabulary.md` through
`taste_files` with stable keys (`lane:<slug>`, `label:<name>`, `artist:<name>`,
`anchor:<track id>`, `word:<token>`) and at most 5 Now lines each; `taste/facts.json` and
`taste/cooccurrence.json` are data and are rewritten on every run. A run gives each MD file at
most 5 entries (lists <= 5, contract section 0): the top 5 lanes, the top 3 labels and then
artists up to 5, anchors one per cluster in turn up to 5, the top 5 words. The full lists are in
the JSON files. A name keeps its dashes in its key: a dash that follows a dash is written `%2D`
(and `%` as `%25`), so "Night--Shift" and "Night-Shift" get two keys and no key holds `--`.

`write` checks all four MD files before it writes any (a file that is not UTF-8 stops the run
with nothing written). With `rebuild=True` it first copies the MD files that exist to
`.cache/taste-rebuild-<date>/`, so the lines the rebuild drops (the DJ's own included) are kept.
`run` appends one `taste` line to `log.md`, also when a write fails part way (TasteWriteError
names the files that were written and carries their added lines).
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from datetime import date
from fractions import Fraction
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Iterable

from dj.libfolder import (
    LibraryFolder,
    LibraryFolderError,
    append_log,
    latest_export,
    relative,
    write_text,
)
from dj.model import Library, LibraryError, PlaylistNode, Track, id_sort_key
from dj.readers.xml import read_xml
from dj.taste_files import NOW_LIMIT, AppendPlan, Entry, plan_entries, write_plan

MODULE = "dj.analysis.taste"

TOP_LABELS = 20
TOP_ARTISTS = 20
TOP_KEYS = 12
TOP_TRACKS = 20
TOP_PAIRS = 20
TOP_WORDS = 20
LABEL_ARTISTS = 3  # top artists shown per label
CLUSTER_ARTISTS = 5  # top artists shown per cluster

MIN_LANE_TRACKS = 3  # BPM-tagged tracks a playlist needs to have a lane
MAX_LANE_WIDTH = 12  # BPM; a wider middle half is a mixed playlist, not a lane
MIN_PAIR_PLAYLISTS = 2
MAX_PAIR_PLAYLIST = 100  # tracks; bigger playlists are skipped for co-occurrence
MAX_PAIRS = 5000  # pairs listed in facts and cooccurrence.json (the strongest); `count` has all
CLUSTER_JACCARD = Fraction(1, 2)
MIN_CLUSTER_TRACKS = 2
MAX_ANCHORS = 3
ANCHOR_RATING = 4  # stars the 2nd and 3rd anchor need
TOP_RATING = 4  # stars for top_rated
MIN_WORD = 3  # letters

# Entries one run gives each MD file: lists <= 5 (contract section 0). Full lists: facts.json.
LOG_ENTRIES = NOW_LIMIT
LOG_LABELS = 3  # labels first in labels-artists.md, then artists up to LOG_ENTRIES
NAMES_IN_TEXT = 3  # names spelled out inside one line, then "and N more"

STOP_WORDS = frozenset(
    """
    the and for with from into onto not but nor all any are was were this that these those
    you your yours our ours its his her hers their them they who whom what when where which
    how why than then too very can will just out off over under per via also has have had
    been being yet etc
    untitled playlist playlists folder folders copy
    """.split()
)

FILES = {
    "lanes": ("lanes.md", "BPM lanes"),
    "labels": ("labels-artists.md", "Labels and artists"),
    "anchors": ("anchors.md", "Anchor tracks"),
    "words": ("vocabulary.md", "Naming vocabulary"),
}
FACTS_JSON = "facts.json"
PAIRS_JSON = "cooccurrence.json"

_WORD = re.compile(r"[^\W\d_]+")
_SLUG = re.compile(r"[\W_]+")
_CAMELOT = re.compile(r"^(?:1[0-2]|0?[1-9])\s*([AB])$", re.IGNORECASE)
_OPEN_KEY = re.compile(r"^(?:1[0-2]|0?[1-9])\s*([MD])$", re.IGNORECASE)
_CLASSIC = re.compile(r"^[A-G](?:#|b|♯|♭)?\s*(m|min|minor|maj|major)?$")
_DRIVE = re.compile(r"^[A-Za-z]:")
_SECOND_DASH = re.compile(r"(?<=-)-")  # a dash right after a dash


class NotALibraryFolder(LibraryFolderError):
    """The folder has no library.yaml: the tool writes taste files only into a dj-library
    folder (scripts exit 2, refused)."""


class TasteWriteError(LibraryError):
    """A write failed part way. `written` and `added` hold the files that were written before
    it and their added lines, so the diff can still be shown and logged (R-332, R-904)."""

    def __init__(self, message: str, written: list[str], added: dict[str, list[str]]) -> None:
        super().__init__(message)
        self.written = written
        self.added = added


# -- the library, indexed once -------------------------------------------------------------


class _View:
    """Tracks in id order and the playlists with their known, distinct members."""

    def __init__(self, lib: Library) -> None:
        self.lib = lib
        self.tracks: list[Track] = sorted(lib.tracks.values(), key=lambda t: id_sort_key(t.id))
        self.playlists: list[tuple[PlaylistNode, tuple[str, ...]]] = []
        for node in lib.playlists():
            members = tuple(dict.fromkeys(i for i in node.track_ids if i in lib.tracks))
            self.playlists.append((node, members))
        self.in_playlists: dict[str, list[int]] = {t.id: [] for t in self.tracks}
        for index, (_node, members) in enumerate(self.playlists):
            for track_id in members:
                self.in_playlists[track_id].append(index)

    def path(self, index: int) -> str:
        return self.playlists[index][0].path_str


def _norm(text: str) -> str:
    return " ".join(str(text or "").split())


def _fold(text: str) -> str:
    return _norm(text).casefold()


def _spelling(spellings: Counter) -> str:
    """The most common spelling; ties go to the first in sort order."""
    return sorted(spellings.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]


def _ranked_names(names: Iterable[str], limit: int | None = None) -> list[tuple[str, int]]:
    """(display name, count) by count, then name; grouped case-insensitively; empties dropped."""
    counts: Counter = Counter()
    spellings: dict[str, Counter] = {}
    for raw in names:
        name = _norm(raw)
        if name:
            counts[name.casefold()] += 1
            spellings.setdefault(name.casefold(), Counter())[name] += 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    rows = [(_spelling(spellings[key]), n) for key, n in ranked]
    return rows if limit is None else rows[:limit]


def _num(value: float) -> float | int:
    """One decimal at most; a whole number as an int (120, 122.8)."""
    rounded = round(value, 1)
    return int(rounded) if rounded == int(rounded) else rounded


def _half_up(value: float) -> int:
    return math.floor(value + 0.5)


def _quantile(sorted_values: list[float], q: float) -> float:
    """Linear interpolation between closest ranks (the common 'inclusive' method)."""
    pos = (len(sorted_values) - 1) * q
    low = math.floor(pos)
    high = min(low + 1, len(sorted_values) - 1)
    return sorted_values[low] + (sorted_values[high] - sorted_values[low]) * (pos - low)


def _track_row(t: Track) -> dict[str, Any]:
    return {
        "id": t.id,
        "track": t.label_line,
        "rating": t.rating,
        "play_count": t.play_count,
        "bpm": _num(t.bpm),
        "key": t.key,
    }


# -- facts ---------------------------------------------------------------------------------


def facts(lib: Library, *, today: date | None = None) -> dict[str, Any]:
    """Every taste fact of `lib`, JSON-serialisable. Pure: no files, no clock (`today` is
    accepted for the shared analysis interface; nothing here depends on the date)."""
    del today
    view = _View(lib)
    bpm_rows, lanes = _lanes(view)
    mixed = {row["index"] for row in bpm_rows if row["mixed"]}
    pairs, skipped = _pairs(view)
    degree: Counter = Counter()
    for a, b, _n in pairs:
        degree[a] += 1
        degree[b] += 1
    clusters = _clusters(view, mixed)
    anchors = _anchors(view, clusters, degree)
    cluster_of = {name: c["name"] for c in clusters for name in c["labels"]}
    return {
        "tracks": len(view.tracks),
        "labels": _labels(view, cluster_of),
        "artists": _artists(view),
        "clusters": clusters,
        "lanes": lanes,
        "bpm_playlists": [{k: v for k, v in row.items() if k != "index"} for row in bpm_rows],
        "keys": _keys(view),
        "cooccurrence": _cooccurrence(view, pairs, skipped),
        "top_rated": _top_rated(view),
        "most_played": _most_played(view),
        "anchors": anchors,
        "vocabulary": _vocabulary(lib),
    }


def _labels(view: _View, cluster_of: dict[str, str]) -> dict[str, Any]:
    groups: dict[str, list[Track]] = {}
    spellings: dict[str, Counter] = {}
    for t in view.tracks:
        name = _norm(t.label)
        if name:
            groups.setdefault(name.casefold(), []).append(t)
            spellings.setdefault(name.casefold(), Counter())[name] += 1
    rows = []
    for key, tracks in groups.items():
        name = _spelling(spellings[key])
        playlists = {i for t in tracks for i in view.in_playlists[t.id]}
        rows.append({
            "name": name,
            "tracks": len(tracks),
            "playlists": len(playlists),
            "top_artists": [n for n, _ in _ranked_names((t.artist for t in tracks), LABEL_ARTISTS)],
            "cluster": cluster_of.get(name),
        })  # fmt: skip
    rows.sort(key=lambda r: (-r["tracks"], -r["playlists"], r["name"].casefold(), r["name"]))
    return {
        "distinct": len(rows),
        "without_label": sum(1 for t in view.tracks if not _norm(t.label)),
        "top": rows[:TOP_LABELS],
    }


def _artists(view: _View) -> dict[str, Any]:
    groups: dict[str, list[Track]] = {}
    spellings: dict[str, Counter] = {}
    for t in view.tracks:
        name = _norm(t.artist)
        if name:
            groups.setdefault(name.casefold(), []).append(t)
            spellings.setdefault(name.casefold(), Counter())[name] += 1
    rows = []
    for key, tracks in groups.items():
        playlists = {i for t in tracks for i in view.in_playlists[t.id]}
        rows.append({
            "name": _spelling(spellings[key]),
            "tracks": len(tracks),
            "playlists": len(playlists),
            "labels": [n for n, _ in _ranked_names((t.label for t in tracks), 2)],
        })  # fmt: skip
    by_tracks = sorted(rows, key=lambda r: (-r["tracks"], -r["playlists"], r["name"].casefold(), r["name"]))
    by_playlists = sorted(
        (r for r in rows if r["playlists"]),
        key=lambda r: (-r["playlists"], -r["tracks"], r["name"].casefold(), r["name"]),
    )
    return {
        "distinct": len(rows),
        "without_artist": sum(1 for t in view.tracks if not _norm(t.artist)),
        "by_tracks": by_tracks[:TOP_ARTISTS],
        "by_playlists": by_playlists[:TOP_ARTISTS],
    }


def key_mode(key: str) -> str:
    """'minor', 'major' or 'unknown' for a rekordbox key in classic, Camelot or Open Key form."""
    text = _norm(key)
    if m := _CAMELOT.match(text):
        return "minor" if m.group(1).upper() == "A" else "major"
    if m := _OPEN_KEY.match(text):
        return "minor" if m.group(1).upper() == "M" else "major"
    if m := _CLASSIC.match(text):
        suffix = (m.group(1) or "").lower()
        return "minor" if suffix in ("m", "min", "minor") else "major"
    return "unknown"


def _keys(view: _View) -> dict[str, Any]:
    keyed = [_norm(t.key) for t in view.tracks if _norm(t.key)]
    modes = Counter(key_mode(k) for k in keyed)
    known = modes["minor"] + modes["major"]
    top = sorted(Counter(keyed).items(), key=lambda kv: (-kv[1], kv[0]))[:TOP_KEYS]
    return {
        "tagged": len(keyed),
        "untagged": len(view.tracks) - len(keyed),
        "minor": modes["minor"],
        "major": modes["major"],
        "unknown": modes["unknown"],
        "minor_share": round(modes["minor"] / known, 2) if known else None,
        "major_share": round(modes["major"] / known, 2) if known else None,
        "top": [{"key": k, "tracks": n} for k, n in top],
    }


def _slug(text: str) -> str:
    return _SLUG.sub("-", text.casefold()).strip("-") or "x"


def _lanes(view: _View) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(one row per playlist with >= 3 BPM-tagged tracks, the merged lanes)."""
    rows: list[dict[str, Any]] = []
    for index, (node, members) in enumerate(view.playlists):
        bpms = sorted(view.lib.tracks[i].bpm for i in members if view.lib.tracks[i].bpm > 0)
        if len(bpms) < MIN_LANE_TRACKS:
            continue
        lo, hi = _half_up(_quantile(bpms, 0.25)), _half_up(_quantile(bpms, 0.75))
        rows.append({
            "index": index,
            "path": node.path_str,
            "tracks": len(bpms),
            "median": _num(_quantile(bpms, 0.5)),
            "range": f"{lo}-{hi}",
            "lo": lo,
            "hi": hi,
            "mixed": hi - lo > MAX_LANE_WIDTH,
            "lane": None,
        })  # fmt: skip

    groups: list[dict[str, Any]] = []
    for row in sorted((r for r in rows if not r["mixed"]), key=lambda r: (r["lo"], r["hi"], r["index"])):
        if groups and _joins(groups[-1], row):
            groups[-1]["hi"] = max(groups[-1]["hi"], row["hi"])
            groups[-1]["rows"].append(row)
        else:
            groups.append({"lo": row["lo"], "hi": row["hi"], "rows": [row]})

    lanes: list[dict[str, Any]] = []
    keys: set[str] = set()
    for group in groups:
        members = sorted(group["rows"], key=lambda r: r["index"])
        label = f"{group['lo']}-{group['hi']}"
        main = sorted(members, key=lambda r: (-r["tracks"], r["index"]))[0]
        key, n = f"lane:{_slug(main['path'])}", 2
        while key in keys:
            key, n = f"lane:{_slug(main['path'])}-{n}", n + 1
        keys.add(key)
        ids = dict.fromkeys(
            i for r in members for i in view.playlists[r["index"]][1] if view.lib.tracks[i].bpm > 0
        )
        bpms = sorted(view.lib.tracks[i].bpm for i in ids)
        for r in members:
            r["lane"] = label
        lanes.append({
            "label": label,
            "lo": group["lo"],
            "hi": group["hi"],
            "key": key,
            "playlists": [r["path"] for r in members],
            "tracks": len(ids),
            "median": _num(_quantile(bpms, 0.5)),
        })  # fmt: skip
    return rows, lanes


def _joins(group: dict[str, Any], row: dict[str, Any]) -> bool:
    """Does `row` (sorted by its low end, so row lo >= group lo) belong to the lane `group`?
    They overlap by more than a boundary BPM, or one holds the other, and the lane stays within
    MAX_LANE_WIDTH."""
    overlaps = (
        row["lo"] < group["hi"]  # more than a shared boundary BPM
        or row["hi"] <= group["hi"]  # the lane holds the row ("122-122" in "120-122")
        or row["lo"] == group["lo"]  # the row holds the lane ("120-122" over "120-120")
    )
    return overlaps and max(group["hi"], row["hi"]) - group["lo"] <= MAX_LANE_WIDTH


def _pairs(view: _View) -> tuple[list[tuple[str, str, int]], list[str]]:
    """Track pairs (a before b in id order) in >= 2 playlists, most shared first."""
    eligible = [len(members) <= MAX_PAIR_PLAYLIST for _node, members in view.playlists]
    skipped = [view.path(i) for i, ok in enumerate(eligible) if not ok and view.playlists[i][1]]
    order = {t.id: n for n, t in enumerate(view.tracks)}
    pairs: list[tuple[str, str, int]] = []
    for t in view.tracks:  # one small counter per track: memory follows the result, not n^2
        partners: Counter = Counter()
        for index in view.in_playlists[t.id]:
            if eligible[index]:
                partners.update(b for b in view.playlists[index][1] if order[b] > order[t.id])
        pairs += [(t.id, b, n) for b, n in partners.items() if n >= MIN_PAIR_PLAYLISTS]
    pairs.sort(key=lambda p: (-p[2], order[p[0]], order[p[1]]))
    return pairs, skipped


def _cooccurrence(view: _View, pairs: list[tuple[str, str, int]], skipped: list[str]) -> dict[str, Any]:
    top = []
    for a, b, n in pairs[:TOP_PAIRS]:
        shared = sorted(set(view.in_playlists[a]) & set(view.in_playlists[b]))
        top.append({
            "a": a,
            "b": b,
            "count": n,
            "tracks": [view.lib.tracks[a].label_line, view.lib.tracks[b].label_line],
            "playlists": [view.path(i) for i in shared if len(view.playlists[i][1]) <= MAX_PAIR_PLAYLIST],
        })  # fmt: skip
    kept = pairs[:MAX_PAIRS]
    return {
        "min_playlists": MIN_PAIR_PLAYLISTS,
        "max_playlist_size": MAX_PAIR_PLAYLIST,
        "skipped_playlists": skipped,
        "count": len(pairs),
        "max_pairs": MAX_PAIRS,
        "kept": len(kept),
        "top": top,
        "pairs": [[a, b, n] for a, b, n in kept],  # [track id, track id, playlists], strongest first
    }


def _clusters(view: _View, mixed: set[int]) -> list[dict[str, Any]]:
    focus = {i for i, (_node, members) in enumerate(view.playlists) if members and i not in mixed}
    tracks_of: dict[tuple[int, str], list[Track]] = {}
    spellings: dict[tuple[int, str], Counter] = {}
    for t in view.tracks:
        label, artist = _norm(t.label), _norm(t.artist)
        kind, name = (0, label) if label else (1, artist)  # 0 = label, 1 = artist
        if not name:
            continue
        ident = (kind, name.casefold())
        tracks_of.setdefault(ident, []).append(t)
        spellings.setdefault(ident, Counter())[name] += 1
    playlists_of = {
        ident: {i for t in tracks for i in view.in_playlists[t.id] if i in focus}
        for ident, tracks in tracks_of.items()
    }
    order = sorted((k for k in tracks_of if playlists_of[k]), key=lambda k: (-len(tracks_of[k]), k))
    rank = {ident: n for n, ident in enumerate(order)}
    names_in: dict[int, set[tuple[int, str]]] = {}
    for ident in order:
        for i in playlists_of[ident]:
            names_in.setdefault(i, set()).add(ident)

    clusters: list[dict[str, Any]] = []
    assigned: set[tuple[int, str]] = set()
    for seed in order:
        if seed in assigned:
            continue
        assigned.add(seed)
        members = [seed]
        near = {other for i in playlists_of[seed] for other in names_in[i]} - assigned
        for other in sorted(near, key=rank.__getitem__):
            shared = len(playlists_of[seed] & playlists_of[other])
            union = len(playlists_of[seed] | playlists_of[other])
            if Fraction(shared, union) >= CLUSTER_JACCARD:
                members.append(other)
                assigned.add(other)
        tracks = sorted((t for m in members for t in tracks_of[m]), key=lambda t: id_sort_key(t.id))
        if len(tracks) < MIN_CLUSTER_TRACKS:
            continue
        names = [_spelling(spellings[m]) for m in members]
        labels = [n for m, n in zip(members, names) if m[0] == 0]
        clusters.append({
            "name": labels[0] if labels else names[0],
            "labels": labels,
            "names": names,
            "artists": [n for n, _ in _ranked_names((t.artist for t in tracks), CLUSTER_ARTISTS)],
            "tracks": len(tracks),
            "playlists": len(set().union(*(playlists_of[m] for m in members))),
            "track_ids": [t.id for t in tracks],
            "anchors": [],
        })  # fmt: skip
    return clusters


def _anchors(view: _View, clusters: list[dict[str, Any]], degree: Counter) -> list[dict[str, Any]]:
    out = []
    for cluster in clusters:
        ranked = sorted(
            (view.lib.tracks[i] for i in cluster["track_ids"]),
            key=lambda t: (-t.rating, -t.play_count, -degree[t.id], id_sort_key(t.id)),
        )
        chosen: list[Track] = []
        seen: set[tuple[str, str]] = set()
        for t in ranked:
            ident = (_fold(t.artist), _fold(t.title))
            if ident in seen:
                continue
            if chosen and t.rating < ANCHOR_RATING:
                break  # ranked by rating: nothing after this one has the stars either
            chosen.append(t)
            seen.add(ident)
            if len(chosen) == MAX_ANCHORS:
                break
        cluster["anchors"] = [t.id for t in chosen]
        out += [{**_track_row(t), "cluster": cluster["name"], "partners": degree[t.id]} for t in chosen]
    return out


def _top_rated(view: _View) -> dict[str, Any]:
    rated = sorted(
        (t for t in view.tracks if t.rating >= TOP_RATING),
        key=lambda t: (-t.rating, -t.play_count, id_sort_key(t.id)),
    )
    return {"min_rating": TOP_RATING, "count": len(rated), "top": [_track_row(t) for t in rated[:TOP_TRACKS]]}


def _most_played(view: _View) -> dict[str, Any]:
    played = sorted(
        (t for t in view.tracks if t.play_count > 0),
        key=lambda t: (-t.play_count, -t.rating, id_sort_key(t.id)),
    )
    return {"count": len(played), "top": [_track_row(t) for t in played[:TOP_TRACKS]]}


def words_of(name: str) -> list[str]:
    """The vocabulary words of one folder or playlist name, each once, in order."""
    out: list[str] = []
    for word in _WORD.findall(name.casefold()):
        if len(word) >= MIN_WORD and word not in STOP_WORDS and word not in out:
            out.append(word)
    return out


def _vocabulary(lib: Library) -> dict[str, Any]:
    nodes = lib.walk()
    counts: Counter = Counter()
    examples: dict[str, list[str]] = {}
    for node in nodes:
        for word in words_of(node.name):
            counts[word] += 1
            seen = examples.setdefault(word, [])
            if len(seen) < NAMES_IN_TEXT:
                seen.append(node.path_str)
    top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:TOP_WORDS]
    return {
        "names": len(nodes),
        "distinct": len(counts),
        "top": [{"word": w, "count": n, "examples": examples[w]} for w, n in top],
    }


# -- the MD files --------------------------------------------------------------------------


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _names(names: list[str], limit: int = NAMES_IN_TEXT) -> str:
    shown = ", ".join(names[:limit])
    return shown + (f" and {len(names) - limit} more" if len(names) > limit else "")


def _key(prefix: str, value: str, *, fold: bool = True) -> str:
    """A stable entry key: `<prefix>:<value>`, a name in lower case (`fold`), an id as it is.
    `%` becomes `%25` and a dash right after a dash `%2D`: no key holds `--` (it would close
    its HTML comment), and two different names never share a key."""
    text = (_fold(value) if fold else _norm(value)).replace("%", "%25")
    return f"{prefix}:{_SECOND_DASH.sub('%2D', text)}"


def _lane_text(lane: dict[str, Any]) -> str:
    return (
        f"{lane['label']} BPM: {_names(lane['playlists'])}; "
        f"{_plural(lane['tracks'], 'track')}, median {lane['median']}"
    )


def _lanes_doc(data: dict[str, Any]) -> tuple[list[str], list[Entry]]:
    lanes = data["lanes"]
    biggest = sorted(lanes, key=lambda lane: (-lane["tracks"], lane["lo"]))
    shown = sorted(biggest[:NOW_LIMIT], key=lambda lane: lane["lo"])
    now = [_lane_text(lane) for lane in shown]
    mixed = [f"{r['path']} ({r['range']})" for r in data["bpm_playlists"] if r["mixed"]]
    if mixed and len(now) < NOW_LIMIT:
        now.append(f"Mixed BPM, not a lane: {_names(mixed)}")
    if not now:
        now = [f"No playlist has {MIN_LANE_TRACKS} or more BPM-tagged tracks yet."]
    logged = sorted(biggest[:LOG_ENTRIES], key=lambda lane: lane["lo"])
    return now, [Entry(lane["key"], _lane_text(lane)) for lane in logged]


def _counted(rows: list[dict[str, Any]], field: str) -> str:
    return ", ".join(f"{r['name']} {r[field]}" for r in rows[:NOW_LIMIT])


def _labels_doc(data: dict[str, Any]) -> tuple[list[str], list[Entry]]:
    labels, artists = data["labels"]["top"], data["artists"]
    now = []
    if labels:
        now.append(f"Labels by tracks: {_counted(labels, 'tracks')}")
    if artists["by_tracks"]:
        now.append(f"Artists by tracks: {_counted(artists['by_tracks'], 'tracks')}")
    if artists["by_playlists"]:
        now.append(f"Artists across playlists: {_counted(artists['by_playlists'], 'playlists')}")
    for cluster in data["clusters"][: NOW_LIMIT - len(now)]:
        now.append(
            f"Cluster {cluster['name']}: {_names(cluster['names'])}; "
            f"{_plural(cluster['tracks'], 'track')} in {_plural(cluster['playlists'], 'playlist')}"
        )
    if not now:
        now = ["No labels or artists tagged yet."]

    entries = []
    for label in labels[:LOG_LABELS]:
        text = (
            f"{label['name']}: {_plural(label['tracks'], 'track')} in "
            f"{_plural(label['playlists'], 'playlist')}; most from {_names(label['top_artists'])}"
        )
        if label["cluster"]:
            text += f"; cluster {label['cluster']}"
        entries.append(Entry(_key("label", label["name"]), text))
    seen: set[str] = set()
    for artist in artists["by_tracks"] + artists["by_playlists"]:
        if len(entries) >= LOG_ENTRIES:
            break
        key = _key("artist", artist["name"])
        if key in seen:  # the same artist in both rankings
            continue
        seen.add(key)
        text = (
            f"{artist['name']}: {_plural(artist['tracks'], 'track')} in "
            f"{_plural(artist['playlists'], 'playlist')}"
        )
        if artist["labels"]:
            text += f"; on {_names(artist['labels'])}"
        entries.append(Entry(key, text))
    return now, entries


def _anchor_text(anchor: dict[str, Any]) -> str:
    text = (
        f"{anchor['track']}: anchor for {anchor['cluster']}; "
        f"{_plural(anchor['rating'], 'star')}, {_plural(anchor['play_count'], 'play')}"
    )
    if anchor["bpm"]:
        text += f", {anchor['bpm']} BPM"
    if anchor["key"]:
        text += f", key {anchor['key']}"
    return text


def _anchors_doc(data: dict[str, Any]) -> tuple[list[str], list[Entry]]:
    by_id = {a["id"]: a for a in data["anchors"]}
    now = [
        f"{c['name']}: {_names([by_id[i]['track'] for i in c['anchors']], MAX_ANCHORS)}"
        for c in data["clusters"][:NOW_LIMIT]
        if c["anchors"]
    ]
    if not now:
        now = ["No clusters yet: tracks need a label or artist and a playlist."]
    # one anchor per cluster in turn (the first of each, then the second ...), up to LOG_ENTRIES
    turns = sorted(
        (rank, n, track_id) for n, c in enumerate(data["clusters"]) for rank, track_id in enumerate(c["anchors"])
    )
    logged = {track_id for _rank, _n, track_id in turns[:LOG_ENTRIES]}
    entries = [
        Entry(_key("anchor", a["id"], fold=False), _anchor_text(a)) for a in data["anchors"] if a["id"] in logged
    ]
    return now, entries


def _word_text(word: dict[str, Any]) -> str:
    return f"{word['word']}: {_plural(word['count'], 'name')}, e.g. {_names(word['examples'])}"


def _words_doc(data: dict[str, Any]) -> tuple[list[str], list[Entry]]:
    words = data["vocabulary"]["top"]
    now = [_word_text(w) for w in words[:NOW_LIMIT]] or ["No folder or playlist names yet."]
    return now, [Entry(f"word:{w['word']}", _word_text(w)) for w in words[:LOG_ENTRIES]]


_DOCS = {"lanes": _lanes_doc, "labels": _labels_doc, "anchors": _anchors_doc, "words": _words_doc}


# -- write and run -------------------------------------------------------------------------


def _as_folder(folder: LibraryFolder | str | Path) -> LibraryFolder:
    return folder if isinstance(folder, LibraryFolder) else LibraryFolder(Path(folder))


def _check_source(source: str) -> str:
    text = _norm(source)
    if not text or PurePosixPath(text).is_absolute() or PureWindowsPath(text).is_absolute() or _DRIVE.match(text):
        raise LibraryFolderError(f"source must be a path relative to the library folder, got {source!r}")
    return text


def provenance_line(source: str, today: date) -> str:
    """The R-302 line under every generated title (contract section 0)."""
    return f"> Measured by code: {MODULE} from {_check_source(source)}, {today.isoformat()}."


def write(
    folder: LibraryFolder | str | Path,
    facts: dict[str, Any],
    *,
    source: str,
    today: date | None = None,
    rebuild: bool = False,
) -> dict[str, Any]:
    """Append to the four taste MD files, rewrite the two JSON files.

    Returns {"written": [relative paths], "added": {relative MD file: [log lines added]}}: the
    added lines are the diff to show the DJ (R-332), plus "backup" (the folder that holds the
    old MD files, or None). All four MD files are read and checked before any file is written.
    `rebuild=True` (only on --rebuild, after the DJ said yes) writes the MD files from scratch,
    after copying the old ones to `.cache/taste-rebuild-<date>/`. A write that fails part way
    raises TasteWriteError with what was written before it.
    """
    folder = _as_folder(folder)
    today = today or date.today()
    provenance = provenance_line(source, today)
    plans: list[AppendPlan] = []
    for kind, (name, title) in FILES.items():  # phase 1: read and check everything, write nothing
        now, entries = _DOCS[kind](facts)
        plans.append(
            plan_entries(
                folder.taste / name, title, entries, today=today, now_lines=now, provenance=provenance,
                rebuild=rebuild,
            )
        )  # fmt: skip
    measured = {"by": MODULE, "source": _check_source(source), "date": today.isoformat()}
    co = facts["cooccurrence"]
    summary = {**facts, "cooccurrence": {k: v for k, v in co.items() if k != "pairs"}}
    data_files = [
        (folder.taste / FACTS_JSON, json.dumps({"measured": measured, **summary}, indent=2, ensure_ascii=False) + "\n"),
        (folder.taste / PAIRS_JSON, _pairs_json(measured, co)),
    ]

    # phase 2: write
    folder.taste.mkdir(exist_ok=True)
    backup = _back_up(folder, [plan.path for plan in plans], today) if rebuild else None
    written: list[str] = []
    added: dict[str, list[str]] = {}
    current = ""
    try:
        for plan in plans:
            current = folder.relative(plan.path)
            write_plan(plan)
            written.append(current)
            added[current] = plan.added
        for path, text in data_files:
            current = folder.relative(path)
            write_text(path, text)
            written.append(current)
    except OSError as exc:
        done = ", ".join(written) if written else "none"
        kept = f" The old files are in {backup['folder']}." if backup else ""
        raise TasteWriteError(
            f"{current}: cannot write it ({exc.strerror or exc}). Written before it: {done}.{kept} "
            "Close the file if an editor or a sync app holds it, then run again.",
            written,
            added,
        ) from None
    return {"written": written, "added": added, "backup": backup}


def _pairs_json(measured: dict[str, Any], co: dict[str, Any]) -> str:
    """cooccurrence.json: the header indented, then one compact `[a, b, count]` per line."""
    head = {"measured": measured}
    head.update({k: co[k] for k in ("min_playlists", "max_playlist_size", "skipped_playlists", "count",
                                    "max_pairs", "kept")})  # fmt: skip
    text = json.dumps(head, indent=2, ensure_ascii=False)
    rows = ",\n".join("    " + json.dumps(p, ensure_ascii=False, separators=(",", ":")) for p in co["pairs"])
    body = f"[\n{rows}\n  ]" if rows else "[]"
    return text[: -len("\n}")] + f',\n  "pairs": {body}\n}}\n'


def _back_up(folder: LibraryFolder, paths: list[Path], today: date) -> dict[str, Any] | None:
    """Copy the MD files that exist, byte for byte, into a new `.cache/taste-rebuild-<date>`
    folder (`-2`, `-3` ... when that exists; never over an earlier copy).
    Returns {"folder": relative path, "files": [names]}, or None when there was nothing to copy."""
    old = [path for path in paths if path.is_file()]
    if not old:
        return None
    folder.cache.mkdir(exist_ok=True)
    stem, n = f"taste-rebuild-{today.isoformat()}", 1
    while True:
        target = folder.cache / (stem if n == 1 else f"{stem}-{n}")
        try:
            target.mkdir()
            break
        except FileExistsError:
            n += 1
    for path in old:  # bytes as they are (any encoding); "x": the new folder holds no such name
        with open(target / path.name, "xb") as fh:
            fh.write(path.read_bytes())
    return {"folder": folder.relative(target), "files": [path.name for path in old]}


def _source_of(folder: LibraryFolder, path: Path) -> str:
    """The export as a path relative to the folder; just its name when it lies outside."""
    try:
        return relative(folder.root, path)
    except LibraryFolderError:
        return path.name


def _resolve_xml(root: Path, xml: str | Path) -> Path:
    """A `--xml` argument as one absolute path. A relative path is looked up in the library
    folder first, then in the current folder (as dj-start and the other analysis scripts do).
    Not found in either -> LibraryFolderError."""
    given = Path(xml).expanduser()
    path = given
    if not given.is_absolute():
        in_library = root / given
        path = in_library if in_library.is_file() else Path.cwd() / given
    if not path.is_file():
        raise LibraryFolderError(f"{given.as_posix()}: file not found in the library folder or the current folder.")
    return path.resolve()


def _log_counts(added: int, rebuild: bool, backup: dict[str, Any] | None) -> dict[str, int]:
    counts = {"lines added": added}
    if rebuild:
        counts["files rebuilt"] = len(FILES)  # the log keeps that the old lines were dropped ...
    if backup:
        counts[f"old files kept in {backup['folder']}"] = len(backup["files"])  # ... and where they are
    return counts


def run(
    folder: LibraryFolder | str | Path,
    *,
    xml: str | Path | None = None,
    today: date | None = None,
    rebuild: bool = False,
) -> dict[str, Any]:
    """Read the latest export (or `xml`), measure, append to taste/, log one line:
    `<date> <time> taste -> <n> lines added[, 4 files rebuilt, <k> old files kept in
    .cache/taste-rebuild-<date>]; taste` (R-904).

    Returns counts first (NFR-03), then the source, the written files, the added lines per
    file (the diff to show the DJ, R-332) and the rebuild backup. A folder without library.yaml
    -> NotALibraryFolder. A relative `xml` is looked up in the library folder, then in the
    current folder. A write that fails part way still logs what was written, then raises
    TasteWriteError.
    """
    folder = _as_folder(folder)
    if not folder.library_yaml.is_file():
        raise NotALibraryFolder(
            f"{folder.root.name} is not a dj-library folder (no library.yaml). "
            "Set it up with dj-start first. Nothing was written."
        )
    path = _resolve_xml(folder.root, xml) if xml else latest_export(folder.root)
    source = _source_of(folder, path)
    lib = read_xml(path)
    data = facts(lib, today=today)
    try:
        result = write(folder, data, source=source, today=today, rebuild=rebuild)
    except TasteWriteError as exc:
        counts = {
            "lines added": sum(len(lines) for lines in exc.added.values()),
            "files written": len(exc.written),
            "files not written": len(FILES) + 2 - len(exc.written),  # the MD files and the 2 JSON files
        }
        append_log(folder.root, "taste", counts, file=folder.taste, today=today)
        raise
    added = sum(len(lines) for lines in result["added"].values())
    log = append_log(folder.root, "taste", _log_counts(added, rebuild, result["backup"]), file=folder.taste, today=today)
    return {
        "counts": {
            "tracks": data["tracks"],
            "lanes": len(data["lanes"]),
            "clusters": len(data["clusters"]),
            "anchors": len(data["anchors"]),
            "pairs": data["cooccurrence"]["count"],
            "words": data["vocabulary"]["distinct"],
            "lines_added": added,
        },
        "source": source,
        "rebuild": rebuild,
        "written": result["written"],
        "added": result["added"],
        "backup": result["backup"],
        "log": log,
    }
