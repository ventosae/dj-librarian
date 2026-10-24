"""dj-identity: six measured axes, an archetype, the lanes' colours and the fingerprint
(R-1401, R-1402, R-1403). Measured by code; Claude writes the liner notes (R-1404, R-302).

Door 1: stdlib + PyYAML only. It reads the facts the other analysis steps wrote
(`profile/facts.json`, `structure/facts.json`, `taste/facts.json`) and the export they came
from, and writes `profile/identity.json`, `profile/sleeve.svg` (dj.sleeve) and one `log.md`
line, all inside the library folder. Never rekordbox, Spotify or audio files (R-341).

    measure(lib)                        -> the decade x BPM-band counts and the genre counts
    axes(profile, structure, taste, shape, today=...)  -> six axes, each {name, score, inputs, formula}
    pick(scores, table)                 -> (the two top axes, the archetype)
    build(...)                          -> the identity dict (profile/identity.json)
    lanes(taste)                        -> the lanes in BPM order, each with its slot (by size)
    band_slots(lanes)                   -> {BPM band: slot} for any lanes (mini sleeve recolouring)
    run(folder, xml=None, today=None, archetypes=None)  -> write both files, one log line

The six axes, each 0-100 (whole number, rounded half up, clamped). Every input is in
identity.json next to its score. "share" = part / whole, 0 when the whole is 0.

- Depth (era spread, catalogue age), from profile eras:
  100 * (0.6 * min(effective_decades / 5, 1) + 0.4 * min(median_age / 25, 1)).
  effective_decades = e ** (Shannon entropy of the tracks per decade), so a few strays from an
  old decade count for little; median_age = the year of `today` minus the middle of the decade
  that holds the median dated track (1990s -> 1995).
- Selectivity (lossless + 320 kbps share, bitrate floor), from profile bitrates, over the
  tracks with a known bitrate: 100 * (0.4 * high_share + 0.3 * min(lossless_share / 0.5, 1)
  + 0.3 * (1 - min(under_256_share / 0.25, 1))). high = lossless or 320 kbps and up.
- Discipline (named-folder share, dump ratio, orphan share, duplicate groups), from structure
  and profile facts: 100 * (0.2 * in_folders_share + 0.3 * (1 - dump_share) + 0.3 * (1 -
  orphan_share) + 0.2 * (1 - min(2 * duplicate_share, 1))). in_folders = playlists below the
  top level; dump_share = the biggest dump's share of the collection (no playlist with tracks:
  1, the whole collection is the pile); duplicate_share = tracks in duplicate groups / tracks.
- Breadth (genre and BPM-lane spread): 100 * (0.4 * min(effective_genres / 6, 1) + 0.3 *
  min(lanes / 5, 1) + 0.3 * min(bands_used / 6, 1)). effective_genres = e ** (entropy of the
  tracks per Genre tag) from the export (the facts files carry no genre counts); lanes = taste
  lanes; bands_used = BPM bands holding at least 5% of the BPM-tagged tracks.
- Momentum (adds in the last 365 days), from the profile timeline: 100 * (0.4 *
  min(recent_share / 0.25, 1) + 0.3 * min(pace / 2, 1) + 0.3 * freshness). recent = added in
  the 365 days up to the facts' date; pace = recent / (dated adds per year since the first
  add, at least one year); freshness = 1 - days since the last add / 365, at least 0.
- Memory (ratings, colours, comments, My Tags use): the mean fill percentage of those fields,
  only over the fields the source carries (an XML export has no My Tags: `my_tags: null`, left
  out of the mean).
A library with no tracks scores 0 everywhere.

Archetype: the two highest scores (ties by the axis order above) form an unordered pair; the
archetype in `archetypes.yaml` that lists the pair is the DJ's. The table must hold 8
archetypes covering each of the 15 pairs exactly once. The default table ships inside the
package (`dj/analysis/archetypes.yaml`), so `dj library analyze` finds it in any install; the
dj-identity skill script passes the skill's own copy (plugin/skills/dj-identity/), and a test
keeps the two files the same.

Lanes and their colours (Q-30, D-27): the lanes list is the taste lanes in BPM order (low end,
then high end, then label). Slots are assigned here, once, and every chart reads them from
identity.json (the sleeve, the crate wall, the proposal cards); none re-derives or re-folds them.
The COLOURED (4, dj.design.MAX_SLOTS_PER_CHART) lanes with the most tracks get a colour (ties:
the slower lane first, by the BPM order above, then the label); those four take slots 1..4 in
BPM order, the slowest of them slot 1, so size picks which lanes are coloured and BPM picks
which colour, never rank. Every other lane is "Other": `slot: null`, the Other grey of
dj.design. So a DJ's biggest lane always has a colour, and the same lane has the same slot on
every chart of the page and on the sleeve.

Fingerprint: rings = the decades of profile eras that hold tracks, oldest (inner) first;
segments = the fixed BPM bands BANDS (edges 100, 110, 118, 122, 125, 128, 135: the house and
techno range gets the narrow bands, everything under 100 or from 135 up shares one band
each); a cell = tracks of that decade in that band / tracks with both a year and a BPM. A
band is owned by the lane whose range (each end widened by half a BPM, since lane ends are
rounded) overlaps it most (ties: the slower lane) and carries that lane's slot; a band no lane
touches has no owner, and it draws in the Other grey, as does a band owned by an Other lane.

Seed: the sha256 of the export's bytes, so the sleeve changes only when the library does. A
master.db read (dj library analyze --source db) has no export file; its seed is the sha256 of
the measured counts instead. identity.json is deterministic: same facts, export and date ->
same bytes (sorted keys).
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import yaml

from dj import design
from dj import sleeve as sleeve_mod
from dj.analysis.common import library_folder, resolve_xml, write_json
from dj.analysis.profile import decade
from dj.libfolder import (
    DJ_NAME_MAX,
    LibraryFolder,
    LibraryFolderError,
    append_log,
    latest_export,
    load_meta,
    relative,
    write_text,
)
from dj.model import Library, LibraryError
from dj.readers.xml import read_xml
from dj.safety import REPO_ROOT

MODULE = "dj.analysis.identity"
SCHEMA = 1
IDENTITY_JSON = "profile/identity.json"
SLEEVE_SVG = "profile/sleeve.svg"
IDENTITY_MD = "profile/identity.md"  # Claude's liner notes (R-1404); this module never writes it
FACTS = {"profile": "profile/facts.json", "structure": "structure/facts.json", "taste": "taste/facts.json"}

AXES = ("depth", "selectivity", "discipline", "breadth", "momentum", "memory")
AXIS_NAMES = {a: a.capitalize() for a in AXES}
ARCHETYPE_COUNT = 8
PAIRS = tuple((a, b) for i, a in enumerate(AXES) for b in AXES[i + 1:])  # the 15 unordered pairs
ARCHETYPES_YAML = Path(__file__).with_name("archetypes.yaml")  # the packaged copy of the skill's table
SKILL_ARCHETYPES_YAML = REPO_ROOT / "plugin" / "skills" / "dj-identity" / "archetypes.yaml"

BAND_EDGES = (100, 110, 118, 122, 125, 128, 135)
BANDS = ("<100", "100-110", "110-118", "118-122", "122-125", "125-128", "128-135", "135+")
BAND_FLOOR = 0.05  # a band "used" by Breadth holds at least this share of BPM-tagged tracks
COLOURED = design.MAX_SLOTS_PER_CHART  # Q-30, D-27: the biggest lanes that get a colour; the rest are Other
MEMORY_FIELDS = ("rating", "colour", "comment", "my_tags")
DEFAULT_HANDLE = "You"
HANDLE_MAX = DJ_NAME_MAX  # characters, as library.yaml allows
_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class IdentityError(LibraryError):
    """identity cannot run: a facts file is missing or does not read, the archetype table is
    broken, or the facts come from another export. Nothing was written."""


# -- small helpers -------------------------------------------------------------------------------


def _share(part: float, whole: float) -> float:
    return part / whole if whole else 0.0


def _score(value: float) -> int:
    """0..1 -> a whole 0..100, rounded half up (after 6 decimals, so 0.675 is 68 everywhere)."""
    return max(0, min(100, math.floor(round(100 * value, 6) + 0.5)))


def _effective(counts: Iterable[int]) -> float:
    """e ** Shannon entropy: how many equally big groups the counts are worth (0 for none)."""
    values = [c for c in counts if c > 0]
    total = sum(values)
    if not total:
        return 0.0
    return math.exp(-sum(c / total * math.log(c / total) for c in values))


def _r(value: float, places: int = 3) -> float:
    return round(value, places)


def band_of(bpm: float) -> int | None:
    """The index in BANDS of a BPM; None when the track has no BPM."""
    if not bpm or bpm <= 0:
        return None
    for n, edge in enumerate(BAND_EDGES):
        if bpm < edge:
            return n
    return len(BAND_EDGES)


def band_range(n: int) -> tuple[int | None, int | None]:
    """(low edge or None, high edge or None) of band n."""
    return (BAND_EDGES[n - 1] if n else None, BAND_EDGES[n] if n < len(BAND_EDGES) else None)


# -- measuring the export -----------------------------------------------------------------------


def measure(lib: Library) -> dict[str, Any]:
    """Counts the facts files do not hold: tracks per decade x BPM band and per Genre tag.

    {"tracks", "no_year", "no_bpm", "bands": [8 counts], "cells": {decade: [8 counts]},
     "genres": {genre: tracks}}. Genres are grouped case-insensitively under their most common
    spelling; an empty Genre is not counted."""
    bands = [0] * len(BANDS)
    cells: dict[str, list[int]] = {}
    spellings: dict[str, Counter] = {}
    no_year = no_bpm = 0
    for track in lib.tracks.values():
        n = band_of(track.bpm)
        era = decade(track.year)
        if n is None:
            no_bpm += 1
        else:
            bands[n] += 1
        if era == "unknown":
            no_year += 1
        elif n is not None:
            cells.setdefault(era, [0] * len(BANDS))[n] += 1
        genre = " ".join(str(track.genre or "").split())
        if genre:
            spellings.setdefault(genre.casefold(), Counter())[genre] += 1
    genres = {
        sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]: sum(c.values())
        for c in spellings.values()
    }
    return {
        "tracks": len(lib.tracks),
        "no_year": no_year,
        "no_bpm": no_bpm,
        "bands": bands,
        "cells": dict(sorted(cells.items())),
        "genres": dict(sorted(genres.items(), key=lambda kv: (-kv[1], kv[0]))),
    }


# -- the six axes --------------------------------------------------------------------------------


def _depth(profile: Mapping[str, Any], today: date) -> tuple[float, dict[str, Any]]:
    eras = {k: v for k, v in profile.get("eras", {}).items() if k != "unknown" and v}
    dated = sum(eras.values())
    eff = _effective(eras.values())
    median_decade, age = None, 0
    if dated:
        middle, seen = (dated + 1) // 2, 0
        for name in sorted(eras):
            seen += eras[name]
            if seen >= middle:
                median_decade = name
                break
        age = max(0, today.year - (int(median_decade[:4]) + 5))
    value = 0.6 * min(eff / 5, 1) + 0.4 * min(age / 25, 1)
    return value, {
        "dated_tracks": dated,
        "decades": len(eras),
        "effective_decades": _r(eff, 2),
        "oldest": min(eras) if eras else None,
        "newest": max(eras) if eras else None,
        "median_decade": median_decade,
        "median_age_years": age,
    }


def _selectivity(profile: Mapping[str, Any]) -> tuple[float, dict[str, Any]]:
    b = profile.get("bitrates", {})
    total = profile.get("size", {}).get("tracks", 0)
    known = max(0, total - b.get("unknown", 0))
    lossless, at_320 = b.get("lossless", 0), b.get("320", 0)
    under_256 = b.get("<192", 0) + b.get("192-255", 0)
    high, lossless_share, low = _share(lossless + at_320, known), _share(lossless, known), _share(under_256, known)
    value = 0.0 if not known else 0.4 * high + 0.3 * min(lossless_share / 0.5, 1) + 0.3 * (1 - min(low / 0.25, 1))
    return value, {
        "known_bitrate": known,
        "lossless": lossless,
        "at_320": at_320,
        "under_256": under_256,
        "high_share": _r(high),
        "lossless_share": _r(lossless_share),
        "under_256_share": _r(low),
    }


def _discipline(profile: Mapping[str, Any], structure: Mapping[str, Any]) -> tuple[float, dict[str, Any]]:
    tracks = profile.get("size", {}).get("tracks", 0)
    levels = {str(k): v for k, v in structure.get("depth", {}).get("playlists_by_level", {}).items()}
    playlists = sum(levels.values())
    in_folders = playlists - levels.get("1", 0)
    sizes = structure.get("sizes", {})
    dumps = structure.get("dumps", {})
    holds_tracks = bool(sizes.get("playlists")) and bool(sizes.get("max"))
    if not holds_tracks:
        dump_share = 1.0
    elif dumps.get("count") and dumps.get("top"):
        dump_share = float(dumps["top"][0].get("share", 0.0))
    else:
        dump_share = 0.0
    orphan_share = float(structure.get("orphans", {}).get("share", 0.0))
    duplicates = profile.get("duplicates", {})
    dup_share = _share(duplicates.get("tracks", 0), tracks)
    named = _share(in_folders, playlists)
    value = 0.0 if not tracks else (
        0.2 * named + 0.3 * (1 - dump_share) + 0.3 * (1 - orphan_share) + 0.2 * (1 - min(2 * dup_share, 1))
    )
    return value, {
        "playlists": playlists,
        "in_folders": in_folders,
        "in_folders_share": _r(named),
        "dumps": dumps.get("count", 0),
        "dump_share": _r(dump_share),
        "orphan_share": _r(orphan_share),
        "duplicate_groups": duplicates.get("groups", 0),
        "duplicate_share": _r(dup_share),
    }


def _breadth(taste: Mapping[str, Any], shape: Mapping[str, Any]) -> tuple[float, dict[str, Any]]:
    genres = shape.get("genres", {})
    eff = _effective(genres.values())
    lanes = len(taste.get("lanes", []))
    bands = shape.get("bands", [0] * len(BANDS))
    tagged = sum(bands)
    used = sum(1 for n in bands if tagged and n / tagged >= BAND_FLOOR)
    value = 0.4 * min(eff / 6, 1) + 0.3 * min(lanes / 5, 1) + 0.3 * min(used / 6, 1)
    return value, {
        "genres": len(genres),
        "effective_genres": _r(eff, 2),
        "lanes": lanes,
        "bpm_tagged": tagged,
        "bands_used": used,
    }


def _momentum(profile: Mapping[str, Any], today: date) -> tuple[float, dict[str, Any]]:
    t = profile.get("timeline", {})
    tracks = profile.get("size", {}).get("tracks", 0)
    recent = t.get("last_365_days", 0)
    dated = max(0, tracks - t.get("undated", 0))
    first = date.fromisoformat(t["first_added"]) if t.get("first_added") else None
    last = date.fromisoformat(t["last_added"]) if t.get("last_added") else None
    years = max(1.0, (today - first).days / 365.25) if first else 1.0
    per_year = dated / years if dated else 0.0
    pace = _share(recent, per_year)
    since = max(0, (today - last).days) if last else None
    fresh = max(0.0, 1 - since / 365) if since is not None else 0.0
    recent_share = _share(recent, tracks)
    value = 0.0 if not dated else 0.4 * min(recent_share / 0.25, 1) + 0.3 * min(pace / 2, 1) + 0.3 * fresh
    return value, {
        "added_last_365_days": recent,
        "recent_share": _r(recent_share),
        "adds_per_year": _r(per_year, 1),
        "pace": _r(pace, 2),
        "days_since_last_add": since,
        "freshness": _r(fresh),
    }


def _memory(profile: Mapping[str, Any]) -> tuple[float, dict[str, Any]]:
    fields = profile.get("fields", {})
    tracks = profile.get("size", {}).get("tracks", 0)
    inputs: dict[str, Any] = {}
    carried = []
    for name in MEMORY_FIELDS:
        share = fields.get(name)
        inputs[name] = None if share is None else share.get("pct", 0)
        if share is not None:
            carried.append(share.get("pct", 0))
    inputs["carried"] = len(carried)
    value = 0.0 if not tracks or not carried else sum(carried) / len(carried) / 100
    return value, inputs


FORMULAS = {
    "depth": "100 * (0.6 * min(effective_decades / 5, 1) + 0.4 * min(median_age_years / 25, 1))",
    "selectivity": "100 * (0.4 * high_share + 0.3 * min(lossless_share / 0.5, 1) + 0.3 * (1 - min(under_256_share / 0.25, 1)))",
    "discipline": "100 * (0.2 * in_folders_share + 0.3 * (1 - dump_share) + 0.3 * (1 - orphan_share) + 0.2 * (1 - min(2 * duplicate_share, 1)))",
    "breadth": "100 * (0.4 * min(effective_genres / 6, 1) + 0.3 * min(lanes / 5, 1) + 0.3 * min(bands_used / 6, 1))",
    "momentum": "100 * (0.4 * min(recent_share / 0.25, 1) + 0.3 * min(pace / 2, 1) + 0.3 * freshness)",
    "memory": "mean fill % of rating, colour, comment, my_tags (only the fields the source carries)",
}  # fmt: skip


def axes(
    profile: Mapping[str, Any],
    structure: Mapping[str, Any],
    taste: Mapping[str, Any],
    shape: Mapping[str, Any],
    *,
    today: date,
) -> dict[str, dict[str, Any]]:
    """The six axes: {axis: {"name", "score" 0..100, "inputs", "formula"}}. Pure."""
    measured = {
        "depth": _depth(profile, today),
        "selectivity": _selectivity(profile),
        "discipline": _discipline(profile, structure),
        "breadth": _breadth(taste, shape),
        "momentum": _momentum(profile, today),
        "memory": _memory(profile),
    }
    empty = not profile.get("size", {}).get("tracks", 0)
    return {
        axis: {
            "name": AXIS_NAMES[axis],
            "score": 0 if empty else _score(value),
            "inputs": inputs,
            "formula": FORMULAS[axis],
        }
        for axis, (value, inputs) in measured.items()
    }


# -- the archetype -------------------------------------------------------------------------------


def _line(value: Any, what: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\n" in value.strip():
        raise IdentityError(f"archetypes.yaml: {what} must be one line of text")
    return " ".join(value.split())


def check_archetypes(data: Any) -> list[dict[str, Any]]:
    """The archetype table, checked: 8 entries, each with slug, name, meaning, booth_line and
    pairs; every one of the 15 axis pairs in exactly one entry; every entry owns a pair."""
    entries = data.get("archetypes") if isinstance(data, dict) else None
    if not isinstance(entries, list) or len(entries) != ARCHETYPE_COUNT:
        raise IdentityError(f"archetypes.yaml: expected {ARCHETYPE_COUNT} archetypes under `archetypes:`")
    out, owner = [], {}
    for n, entry in enumerate(entries, 1):
        if not isinstance(entry, dict):
            raise IdentityError(f"archetypes.yaml: entry {n} is not a mapping")
        slug = entry.get("slug")
        if not isinstance(slug, str) or not _SLUG.match(slug):
            raise IdentityError(f"archetypes.yaml: entry {n} needs a slug like crate-digger")
        item = {
            "slug": slug,
            "name": _line(entry.get("name"), f"{slug}.name"),
            "meaning": _line(entry.get("meaning"), f"{slug}.meaning"),
            "booth_line": _line(entry.get("booth_line"), f"{slug}.booth_line"),
        }
        pairs = entry.get("pairs")
        if not isinstance(pairs, list) or not pairs:
            raise IdentityError(f"archetypes.yaml: {slug} owns no pair")
        for pair in pairs:
            if not isinstance(pair, list) or len(pair) != 2 or pair[0] == pair[1] or any(a not in AXES for a in pair):
                raise IdentityError(f"archetypes.yaml: {slug}: {pair!r} is not a pair of two axes ({', '.join(AXES)})")
            key = tuple(sorted(pair, key=AXES.index))
            if key in owner:
                raise IdentityError(f"archetypes.yaml: {key[0]} + {key[1]} belongs to {owner[key]} and {slug}")
            owner[key] = slug
        item["pairs"] = [list(k) for k in sorted((tuple(sorted(p, key=AXES.index)) for p in pairs), key=PAIRS.index)]
        out.append(item)
    if len({i["slug"] for i in out}) != len(out):
        raise IdentityError("archetypes.yaml: two archetypes share a slug")
    missing = [p for p in PAIRS if p not in owner]
    if missing:
        raise IdentityError("archetypes.yaml: no archetype for " + ", ".join(f"{a} + {b}" for a, b in missing))
    return out


def load_archetypes(path: str | Path | None = None) -> list[dict[str, Any]]:
    """The checked table from `path`, default the copy packaged with dj (ARCHETYPES_YAML)."""
    path = Path(path) if path else ARCHETYPES_YAML
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise IdentityError(f"archetypes.yaml not found at {path.name}: the dj-identity skill folder or the dj "
                            "package is incomplete") from None
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise IdentityError(f"archetypes.yaml does not read: {exc}") from None
    return check_archetypes(data)


def top_two(scores: Mapping[str, int]) -> tuple[str, str]:
    """The two highest axes, ties by axis order, as (first, second) in axis order."""
    ranked = sorted(AXES, key=lambda a: (-scores[a], AXES.index(a)))
    return tuple(sorted(ranked[:2], key=AXES.index))  # type: ignore[return-value]


def pick(scores: Mapping[str, int], table: Sequence[Mapping[str, Any]]) -> tuple[tuple[str, str], dict[str, Any]]:
    """(the two top axes, the archetype that owns their pair: slug, name, meaning, booth_line)."""
    pair = top_two(scores)
    for entry in table:
        if list(pair) in entry["pairs"]:
            return pair, {k: entry[k] for k in ("slug", "name", "meaning", "booth_line")}
    raise IdentityError(f"archetypes.yaml: no archetype for {pair[0]} + {pair[1]}")


# -- lanes and the fingerprint -------------------------------------------------------------------


def bpm_key(lane: Mapping[str, Any]) -> tuple[float, float, str]:
    """The BPM order of lanes: low end, then high end, then label (slowest first)."""
    return (lane.get("lo") or 0, lane.get("hi") or 0, str(lane.get("label", "")))


def size_key(lane: Mapping[str, Any]) -> tuple[float, float, float, str]:
    """The size order of lanes: most tracks first, ties to the slower lane, then the label."""
    return (-(lane.get("tracks") or 0), *bpm_key(lane))


def lanes(taste: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Taste lanes by BPM, low to high, each with its palette slot: the COLOURED biggest lanes
    (size_key) take slots 1..COLOURED in BPM order, every other lane None ("Other")."""
    rows = sorted(taste.get("lanes", []), key=bpm_key)
    coloured = sorted(sorted(range(len(rows)), key=lambda n: size_key(rows[n]))[:COLOURED])  # BPM order
    slots = {n: k for k, n in enumerate(coloured, 1)}
    out = []
    for n, lane in enumerate(rows):
        out.append({
            "label": str(lane.get("label", "")),
            "lo": lane.get("lo"),
            "hi": lane.get("hi"),
            "key": lane.get("key"),
            "tracks": lane.get("tracks", 0),
            "median": lane.get("median"),
            "playlists": list(lane.get("playlists", [])),
            "slot": slots.get(n),
        })  # fmt: skip
    return out


def _overlap(lane: Mapping[str, Any], n: int) -> float:
    lo, hi = band_range(n)
    a, b = float(lane["lo"]) - 0.5, float(lane["hi"]) + 0.5
    return max(0.0, min(b, hi if hi is not None else math.inf) - max(a, lo if lo is not None else 0.0))


def owner(lane_rows: Sequence[Mapping[str, Any]], n: int) -> Mapping[str, Any] | None:
    """The lane that owns band n: the biggest overlap, ties to the slower lane; None if none."""
    best, best_overlap = None, 0.0
    for lane in lane_rows:
        if lane.get("lo") is None or lane.get("hi") is None:
            continue
        overlap = _overlap(lane, n)
        if overlap > best_overlap:
            best, best_overlap = lane, overlap
    return best


def band_slots(lane_rows: Sequence[Mapping[str, Any]]) -> dict[str, int | None]:
    """{band: the slot of the lane that owns it, or None} for any set of lanes with `lo`, `hi`
    and `slot` (a proposal's lanes, say): the `slots` argument of dj.sleeve.mini_sleeve_svg.
    Lanes are taken slowest first, so a tie goes to the slower lane as in the fingerprint."""
    ordered = sorted(lane_rows, key=lambda l: (l.get("lo") is None, l.get("lo") or 0, l.get("hi") or 0))
    out: dict[str, int | None] = {}
    for n, name in enumerate(BANDS):
        lane = owner(ordered, n)
        out[name] = lane.get("slot") if lane else None
    return out


def fingerprint(profile: Mapping[str, Any], shape: Mapping[str, Any], lane_rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Rings (decades, oldest first), bands (BPM, each with its owning lane and slot) and cells
    (rows = rings, columns = bands): `counts` in tracks, `shares` of the placed tracks."""
    eras = {k: v for k, v in profile.get("eras", {}).items() if k != "unknown" and v}
    dated = sum(eras.values())
    decades = sorted(eras)
    cells = shape.get("cells", {})
    counts = [list(cells.get(d, [0] * len(BANDS))) for d in decades]
    placed = sum(map(sum, counts))
    band_counts = list(shape.get("bands", [0] * len(BANDS)))
    tagged = sum(band_counts)
    bands = []
    for n, name in enumerate(BANDS):
        lo, hi = band_range(n)
        lane = owner(lane_rows, n)
        bands.append({
            "band": name,
            "lo": lo,
            "hi": hi,
            "tracks": band_counts[n],
            "share": _r(_share(band_counts[n], tagged), 4),
            "lane": lane["label"] if lane else None,
            "slot": lane["slot"] if lane else None,
        })  # fmt: skip
    return {
        "edges": list(BAND_EDGES),
        "bands": bands,
        "rings": [{"decade": d, "tracks": eras[d], "share": _r(_share(eras[d], dated), 4)} for d in decades],
        "counts": counts,
        "shares": [[_r(_share(c, placed), 4) for c in row] for row in counts],
        "placed": placed,
        "no_year": shape.get("no_year", 0),
        "no_bpm": shape.get("no_bpm", 0),
    }


# -- the identity --------------------------------------------------------------------------------


def handle_of(meta: Mapping[str, Any] | None) -> str:
    """library.yaml `dj_name` on one line, at most HANDLE_MAX characters; empty -> "You"."""
    raw = (meta or {}).get("dj_name")
    text = " ".join(str(raw).split()) if isinstance(raw, str) else ""
    text = "".join(ch for ch in text if ch.isprintable())
    return text[:HANDLE_MAX].strip() or DEFAULT_HANDLE


def seed_of(path: str | Path) -> str:
    """sha256 of the file's bytes, hex."""
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def seed_of_counts(shape: Mapping[str, Any]) -> str:
    """The seed of a source without an export file (master.db): sha256 of the measured counts."""
    return hashlib.sha256(json.dumps(shape, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def build(
    profile: Mapping[str, Any],
    structure: Mapping[str, Any],
    taste: Mapping[str, Any],
    shape: Mapping[str, Any],
    *,
    seed: str,
    source: str,
    handle: str = DEFAULT_HANDLE,
    today: date,
    table: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """The identity dict written to profile/identity.json. Pure."""
    measured = axes(profile, structure, taste, shape, today=today)
    scores = {a: measured[a]["score"] for a in AXES}
    pair, archetype = pick(scores, table)
    lane_rows = lanes(taste)
    fp = fingerprint(profile, shape, lane_rows)
    return {
        "schema": SCHEMA,
        "by": MODULE,
        "date": today.isoformat(),
        "source": source,
        "seed": seed,
        "handle": handle,
        "counts": {
            "tracks": profile.get("size", {}).get("tracks", 0),
            "axes": len(AXES),
            "lanes": len(lane_rows),
            "decades": len(fp["rings"]),
            "bands": len(BANDS),
        },
        "order": list(AXES),
        "axes": measured,
        "top": list(pair),
        "archetype": archetype,
        "lanes": lane_rows,
        "fingerprint": fp,
    }


def write(folder: LibraryFolder, identity: Mapping[str, Any]) -> list[Path]:
    """profile/identity.json and profile/sleeve.svg (tool-owned, rewritten each run)."""
    folder.profile.mkdir(exist_ok=True)
    svg = sleeve_mod.sleeve_svg(identity)  # built first: a bad identity writes nothing
    data = write_json(folder.root / IDENTITY_JSON, identity)
    art = write_text(folder.root / SLEEVE_SVG, svg)
    return [data, art]


def summary(folder: LibraryFolder, identity: Mapping[str, Any], written: Sequence[Path], log: str) -> dict[str, Any]:
    """Counts first, then the archetype, the scores, the handle, the files and the log line."""
    return {
        "counts": dict(identity["counts"]),
        "archetype": {k: identity["archetype"][k] for k in ("slug", "name")},
        "top": list(identity["top"]),
        "scores": {a: identity["axes"][a]["score"] for a in AXES},
        "handle": identity["handle"],
        "source": identity["source"],
        "written": [folder.relative(p) for p in written],
        "log": log,
    }


def _read_facts(folder: LibraryFolder) -> dict[str, dict[str, Any]]:
    out = {}
    for name, rel in FACTS.items():
        path = folder.root / rel
        if not path.is_file():
            raise IdentityError(f"{rel} not found: run dj-{name} first. Nothing was written.")
        try:
            data = json.loads(path.read_bytes().decode("utf-8"))
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            raise IdentityError(f"{rel} does not read ({exc}): run dj-{name} again. Nothing was written.") from None
        if not isinstance(data, dict):
            raise IdentityError(f"{rel} is not a facts file: run dj-{name} again. Nothing was written.")
        out[name] = data
    return out


def _measured_from(facts: Mapping[str, dict[str, Any]]) -> dict[str, str | None]:
    """The export each facts file was measured from (None: the file does not say; an older
    structure/facts.json carries no `export`)."""
    export = facts["structure"].get("export")
    return {
        "profile": (facts["profile"].get("provenance") or {}).get("source"),
        "structure": export if isinstance(export, str) else None,
        "taste": (facts["taste"].get("measured") or {}).get("source"),
    }


def _source_name(folder: LibraryFolder, path: Path) -> str:
    try:
        return relative(folder.root, path)
    except LibraryFolderError:
        return path.name


def _as_of(facts: Mapping[str, dict[str, Any]]) -> date | None:
    stamp = (facts["profile"].get("provenance") or {}).get("date")
    try:
        return date.fromisoformat(stamp) if isinstance(stamp, str) else None
    except ValueError:
        return None


def from_library(
    folder: LibraryFolder,
    lib: Library,
    profile: Mapping[str, Any],
    structure: Mapping[str, Any],
    taste: Mapping[str, Any],
    *,
    source: str,
    today: date | None = None,
    archetypes: str | Path | None = None,
) -> tuple[dict[str, Any], list[Path]]:
    """The identity of a Library already read and measured (dj library analyze): build, write
    both files. No log line (the caller logs). Returns (identity, written paths)."""
    shape = measure(lib)
    if lib.source == "xml" and lib.source_path and Path(lib.source_path).is_file():
        seed = seed_of(lib.source_path)
    else:
        seed = seed_of_counts(shape)
    identity = build(
        profile, structure, taste, shape, seed=seed, source=source, handle=handle_of(_meta(folder)),
        today=today or date.today(), table=load_archetypes(archetypes),
    )  # fmt: skip
    return identity, write(folder, identity)


def _meta(folder: LibraryFolder) -> dict[str, Any] | None:
    try:
        return load_meta(folder.root)
    except LibraryFolderError:
        return None


def run(
    folder: LibraryFolder | str | Path,
    *,
    xml: str | Path | None = None,
    today: date | None = None,
    archetypes: str | Path | None = None,
) -> dict[str, Any]:
    """Read the three facts files and the export they came from (latest, or `xml`), write
    profile/identity.json and profile/sleeve.svg, append one log.md line. Returns the summary.

    `today` (the date the axes are measured at) defaults to the date in profile/facts.json, so
    the same facts always give the same identity. A folder that is not a dj-library ->
    NotALibraryFolder; a missing facts file, facts from another export or a broken archetype
    table -> IdentityError. Nothing is written in either case."""
    folder = library_folder(folder)
    facts = _read_facts(folder)
    table = load_archetypes(archetypes)
    path = resolve_xml(folder.root, xml) if xml else latest_export(folder.root)
    source = _source_name(folder, path)
    stale = {k: v for k, v in _measured_from(facts).items() if v is not None and v != source}
    if stale:
        names = ", ".join(f"{FACTS[k]} ({v})" for k, v in sorted(stale.items()))
        raise IdentityError(
            f"{names} measured another export than {source}: run profile, structure and taste again first. "
            "Nothing was written."
        )
    lib = read_xml(path)
    shape = measure(lib)
    day = today or _as_of(facts) or date.today()
    identity = build(
        facts["profile"], facts["structure"], facts["taste"], shape, seed=seed_of(path), source=source,
        handle=handle_of(_meta(folder)), today=day, table=table,
    )  # fmt: skip
    written = write(folder, identity)
    log = append_log(
        folder.root, "identity", {"axes": len(AXES), "lanes": identity["counts"]["lanes"]}, IDENTITY_JSON, today=today
    )
    return summary(folder, identity, written, log)
