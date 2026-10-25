"""Crate me: a crate for a night, picked from the DJ's own library (R-601..R-604, R-702).

Door 1 core: stdlib + PyYAML only (contract section 0). Reads the latest export XML
(`dj.readers.xml`), `taste/` and `crates/<slug>.spec.yaml`; never opens master.db, never imports
pyrekordbox.

    spec = load_spec(folder.crates / "saturday.spec.yaml")
    result = select(lib, spec, taste_facts, vetoes)   # pure: same spec + same library, same crate
    p = preview(folder, "saturday")    # writes nothing but the gate record in .cache/previews/
    ... the DJ reads the preview and says yes ...
    r = apply(folder, "saturday", p.preview_id)   # proposals/crate-saturday.xml, crates/saturday.md,
                                                  # one log.md line

The spec. Claude turns the DJ's brief into `crates/<slug>.spec.yaml` (R-602), only with the fields
the brief supports::

    name: Saturday Rooftop          # the playlist name in rekordbox
    size: 50                        # 30, 50 or 70 picks
    brief: rooftop, sunset into the night, vocal house
    bpm: [118, 124]                 # BPM window, inclusive
    lanes: ["118-124"]              # lanes of taste/lanes.md: label, key or one of its playlists
    genres: [House, Deep House]     # the genre holds one of these (whole words, any case)
    exclude_genres: [Techno]
    keys: [8A, Am]                  # Camelot, classic or Open Key; neighbours on the wheel fit too
    anchors: ["9", "13"]            # track ids the crate is built around: always in
    my_tags: [Vocal]                # scores only: the XML export carries no My Tags
    min_rating: 3                   # stars, 0-5
    curve: warmup                   # flat (default) | warmup | peak

`name`, `size` and `brief` are required; the rest is optional. Unknown keys are errors.
`load_spec` reports every problem, each in one line.

Who can be picked (the pool): a track with a file location and a BPM (rekordbox analysed it)
that passes every filter the spec sets (`bpm`, `lanes`, `genres`, `exclude_genres`, `keys`,
`min_rating`) and that `taste/vetoes.md` does not veto ("never propose", R-702). A veto names
the song, so it holds for every copy of the vetoed track (same artist and title,
`Vetoes.with_copies`), and a never-pair holds between every copy of one side and every copy of
the other. A lane holds a track when its BPM, rounded half up, lies inside the lane's range. A
key fits when it is the same Camelot code or a neighbour (one step round the wheel, or the
relative major / minor).

Score (whole numbers, so ties are exact; ties go to the lower track id):
- lane: +10 when the BPM sits inside one of the DJ's lanes (`taste/facts.json` lanes; the named
  ones when the spec names lanes); up to +10 more for sitting near the centre of the spec's
  window (named lanes, else `bpm`): 10 minus the BPM distance from the centre.
- co-occurrence: +4 per playlist the track shares with an anchor (`taste/cooccurrence.json`),
  at most +40. The anchors are the spec's; without them, the DJ's anchors (`taste/facts.json`)
  that are in the pool, and those anchors get +10 themselves.
- genre: +8 for a genre equal to one asked for, +4 when it only holds it ("Deep House" for
  "House"). key: +8 the same key, +4 a neighbour. My Tags: +10 per tag asked for, at most +20.
- rating: +4 per star. plays: +2 per binary digit of the play count (1 -> 2, 31 -> 10, 255+ -> 16).
- gig feedback (`taste/feedback.md`, R-702): +1 for a track whose latest signed line says it worked
  (`- [date] + Artist - Title: note`), -1 for one that flopped (`- [date] - Artist - Title: note`);
  a line names the song, so every copy of it counts (`taste_files.feedback_scores`).

Picks: the spec's anchors first (in spec order; a vetoed anchor, one without a file location or
a second copy of an earlier anchor is left out with a warning; two anchors that are a
never-pair -> CrateError), then the pool by
score. A track is skipped when it is a never-pair partner of a track already in the crate (R-702)
or a second copy of one (same artist and title, `dj.analysis.common.dup_key`). Exactly `size`
picks; when fewer tracks fit -> NotEnoughTracks, naming the count and the filter whose widening
lets in the most tracks.

Spares (R-604): ceil(0.2 * size) more tracks from the rest of the pool, by score, spread over
three energy tiers = BPM terciles of the pool (low <= the 1/3 quantile < mid <= the 2/3
quantile < high). Each tier gets a third; what does not divide goes to mid, then high. A tier
that runs short is filled from the others. Spares obey the same vetoes and pairs as picks (one
crate). A track that flopped at a gig (feedback -1) is never a spare. Fewer spares than asked -> a
warning, not an error.

Order (R-602): flat = by score; warmup = BPM rising; peak = BPM rising to the top, then easing
for the last fifth (the easing tracks are every other track of the top two fifths, so the peak
track stays at the top of the climb). Spares: low, mid, high, BPM rising within each.

Each track carries one factual reason, built from what scored ("lane 118-124 · plays with
Tessa Quorum - Open Plan in 3 playlists · 5 stars"); Claude may say it in its own words, never
with other numbers (R-601, R-302).

Writing (R-603) is behind the gate (`dj.gate`, kind "crate", args `{"crate": slug}`): `preview`
records the digest of the spec, the export and the crate (ids and reasons); `apply` computes it
again and refuses (GateError, before any file is written) without a valid preview id or after
any change. It writes `proposals/crate-<slug>.xml` (one folder "Crates" holding the playlist
`<name>` with the picks in order and `<name> spares`, left out when no spares fit; create-only,
`-2`, `-3`) and
`crates/<slug>.md` (the crate record: the full picks and spares tables; create-only too), then
one `log.md` line. When the DJ's tree (the latest export, and `structure/current-tree.yaml` when
there is one) already has a top-level "Crates" folder, the XML uses its spelling and the import
card says to drag the two playlists into it; a playlist of that name already in it blocks the
crate (hard rule 5: rename it in the spec). The export cannot show a crate written after it, so
the crate XMLs in `proposals/` newer than the export count too: one holding a playlist of that
name blocks the crate the same way (the DJ may have imported it), and one holding a Crates folder
while the tree has none makes the import card drag the two playlists into that folder, with a
warning. Once the XML is written, a later failure (the MD file, marking the preview used, the
log line) is a warning, not an error.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import yaml

from dj import libfolder, treeschema
from dj.analysis import taste as taste_analysis
from dj.analysis.common import dup_key
from dj.build_library import DB_READ, read_for_build
from dj.build_structure import import_steps, product_version
from dj.gate import Gate, GateError, preview_id_for, require_id
from dj.libfolder import LibraryFolder, LibraryFolderError
from dj.model import Library, LibraryError, Track, id_sort_key
from dj.readers.xml import read_xml
from dj.taste_files import Vetoes, feedback_scores, read_gig_feedback, read_vetoes
from dj.treeschema import TreeSchemaError
from dj.writers.rekordbox_xml import BuildError, build_lists_xml, numbered, write_xml

__all__ = [
    "CrateError",
    "CratePreview",
    "CrateResult",
    "CrateSpec",
    "CrateSpecError",
    "CrateWriteResult",
    "GateError",
    "NotEnoughTracks",
    "Pick",
    "apply",
    "camelot",
    "load_spec",
    "parse_spec",
    "preview",
    "select",
    "spec_path",
]

MODULE = "dj.crate"
KIND = "crate"  # the gate kind
SIZES = (30, 50, 70)
CURVES = ("flat", "warmup", "peak")
TIERS = ("low", "mid", "high")
CRATES_FOLDER = "Crates"
SPARES_SUFFIX = " spares"
SPEC_SUFFIX = ".spec.yaml"
VETOES_FILE = "taste/vetoes.md"
FEEDBACK_FILE = "taste/feedback.md"
CURRENT_TREE = "structure/current-tree.yaml"
TASTE_FACTS = "taste/facts.json"
TASTE_PAIRS = "taste/cooccurrence.json"
SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
QUOTES = "\"'`“”‘’«»"
MAX_BPM = 300
MAX_NAME = 100
PICKS_LIMIT = 30  # picks in a JSON result; the rest are counted (NFR-03); the MD file has all
SHOWN = 5  # names in a message (lists <= 5)

W_LANE = 10  # BPM inside one of the DJ's lanes
W_CENTRE = 10  # at most, for sitting at the centre of the spec's window
W_PAIR = 4  # per playlist shared with an anchor
MAX_PAIR = 40
W_TASTE_ANCHOR = 10  # one of the DJ's anchors (taste/facts.json), when the spec names none
W_GENRE, W_GENRE_NEAR = 8, 4
W_KEY, W_KEY_NEAR = 8, 4
W_TAG, MAX_TAG = 10, 20
W_STAR = 4
W_PLAYS = 2  # per binary digit of min(play count, 255)
W_FEEDBACK = 1  # taste/feedback.md: + worked at a gig, - flopped (R-702, Q-19)

FILTERS = ("bpm", "lanes", "genres", "exclude_genres", "keys", "min_rating")
SPEC_KEYS = ("name", "size", "brief", "bpm", "lanes", "genres", "exclude_genres", "keys", "anchors",
             "my_tags", "min_rating", "curve")  # fmt: skip
LIST_KEYS = ("lanes", "genres", "exclude_genres", "keys", "my_tags")


class CrateError(ValueError):
    """The crate cannot be made as asked. Nothing was written."""


class CrateSpecError(CrateError):
    """The spec file has problems; `errors` holds one line per problem."""

    def __init__(self, where: str, errors: Iterable[str]) -> None:
        self.where = where
        self.errors = tuple(errors)
        super().__init__(f"{where}: " + "; ".join(self.errors) + ". Fix the spec and preview again.")


class NotEnoughTracks(CrateError):
    """Fewer tracks fit the spec than the crate needs. `widen` names the filter to widen."""

    def __init__(self, message: str, *, found: int, needed: int, widen: str | None) -> None:
        super().__init__(message)
        self.found = found
        self.needed = needed
        self.widen = widen


# -- keys and genres -----------------------------------------------------------------------

_CAMELOT = re.compile(r"^(1[0-2]|0?[1-9])\s*([AB])$", re.IGNORECASE)
_OPEN_KEY = re.compile(r"^(1[0-2]|0?[1-9])\s*([MD])$", re.IGNORECASE)
_CLASSIC = re.compile(r"^([A-G])\s*([#♯b♭]?)\s*(m|min|minor|maj|major)?$", re.IGNORECASE)
_PITCH = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
_SHIFT = {"#": 1, "♯": 1, "b": -1, "B": -1, "♭": -1}
_NOT_WORD = re.compile(r"[\W_]+")


def camelot(key: str) -> str | None:
    """A key in Camelot ("8A"), classic ("Am", "F#m", "Bb") or Open Key ("1m") form as its
    Camelot code; None when it is not a key."""
    text = " ".join(str(key or "").split())
    if not text:
        return None
    if m := _CAMELOT.match(text):
        return f"{int(m.group(1))}{m.group(2).upper()}"
    if m := _OPEN_KEY.match(text):  # 1m = A minor = 8A, 1d = C major = 8B
        return f"{(int(m.group(1)) + 6) % 12 + 1}{'A' if m.group(2).upper() == 'M' else 'B'}"
    if m := _CLASSIC.match(text):
        pitch = _PITCH[m.group(1).upper()] + _SHIFT.get(m.group(2), 0)
        minor = (m.group(3) or "").lower() in ("m", "min", "minor")
        number = ((7 * pitch + 5) if minor else (8 + 7 * pitch)) % 12 or 12  # a fifth up = one step
        return f"{number}{'A' if minor else 'B'}"
    return None


def neighbours(code: str) -> tuple[str, ...]:
    """The keys that mix with a Camelot code: one step either way, and the relative key."""
    number, letter = int(code[:-1]), code[-1]
    other = "B" if letter == "A" else "A"
    return (f"{number % 12 + 1}{letter}", f"{(number - 2) % 12 + 1}{letter}", f"{number}{other}")


def key_fit(key: str, wanted: Sequence[str]) -> tuple[int, str]:
    """(2 = the same key, 1 = a neighbour, 0 = no fit; the wanted key it fits)."""
    code = camelot(key)
    if code is None:
        return 0, ""
    if code in wanted:
        return 2, code
    for want in wanted:
        if code in neighbours(want):
            return 1, want
    return 0, ""


def _words(text: str) -> str:
    return " ".join(_NOT_WORD.sub(" ", str(text or "").casefold()).split())


def genre_fit(genre: str, wanted: Sequence[str]) -> int:
    """2 = the genre is one asked for, 1 = it holds one as whole words ("Deep House" holds
    "House"), 0 = neither. Case and punctuation do not count."""
    have = _words(genre)
    if not have:
        return 0
    asked = [_words(w) for w in wanted if _words(w)]
    if have in asked:
        return 2
    return 1 if any(f" {w} " in f" {have} " for w in asked) else 0


# -- the spec ------------------------------------------------------------------------------


@dataclass(frozen=True)
class CrateSpec:
    """What the crate is for. `keys` hold Camelot codes; lists keep the order given, each once."""

    name: str
    size: int
    brief: str
    bpm: tuple[float, float] | None = None
    lanes: tuple[str, ...] = ()
    genres: tuple[str, ...] = ()
    exclude_genres: tuple[str, ...] = ()
    keys: tuple[str, ...] = ()
    anchors: tuple[str, ...] = ()
    my_tags: tuple[str, ...] = ()
    min_rating: int = 0
    curve: str = "flat"

    @property
    def spares(self) -> int:
        """How many spares the crate gets: ceil(0.2 * size) (R-604)."""
        return math.ceil(self.size / 5)

    def to_dict(self) -> dict[str, Any]:
        """The spec as plain data: the set fields only, in the documented order."""
        out: dict[str, Any] = {"name": self.name, "size": self.size, "brief": self.brief}
        if self.bpm:
            out["bpm"] = [_num(self.bpm[0]), _num(self.bpm[1])]
        for key in ("lanes", "genres", "exclude_genres", "keys", "anchors", "my_tags"):
            if getattr(self, key):
                out[key] = list(getattr(self, key))
        if self.min_rating:
            out["min_rating"] = self.min_rating
        out["curve"] = self.curve
        return out

    def filters_text(self) -> str:
        """The filters in a few words, for the MD summary and the CLI."""
        parts = []
        if self.bpm:
            parts.append(f"bpm {_num(self.bpm[0])}-{_num(self.bpm[1])}")
        if self.lanes:
            parts.append("lanes " + ", ".join(self.lanes))
        if self.genres:
            parts.append("genres " + ", ".join(self.genres))
        if self.exclude_genres:
            parts.append("not " + ", ".join(self.exclude_genres))
        if self.keys:
            parts.append("keys " + ", ".join(self.keys) + " and neighbours")
        if self.min_rating:
            parts.append(f"{self.min_rating}+ stars")
        return "; ".join(parts) if parts else "no filters"


def _num(value: float) -> float | int:
    """One decimal at most; a whole number as an int (120, 122.5)."""
    rounded = round(float(value), 1)
    return int(rounded) if rounded == int(rounded) else rounded


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _one_line(value: Any) -> str:
    return " ".join(str(value).split())


def _text(data: Mapping[str, Any], key: str, errors: list[str]) -> str:
    value = data.get(key)
    if value is None:
        errors.append(f"`{key}` is missing")
        return ""
    if not isinstance(value, str) or not value.strip():
        errors.append(f"`{key}` must be a non-empty text, got {value!r}")
        return ""
    return _one_line(value)


def _texts(data: Mapping[str, Any], key: str, errors: list[str]) -> tuple[str, ...]:
    """A list of texts (a bare text counts as a list of one), each once (case ignored)."""
    value = data.get(key)
    if value is None:
        return ()
    items = [value] if isinstance(value, (str, int)) and not isinstance(value, bool) else value
    if not isinstance(items, list):
        errors.append(f"`{key}` must be a list, got {value!r}")
        return ()
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        if isinstance(item, bool) or not isinstance(item, (str, int)) or not str(item).strip():
            errors.append(f"`{key}`: {item!r} is not a non-empty text")
            continue
        text = _one_line(item)
        if text.casefold() not in seen:
            seen.add(text.casefold())
            out.append(text)
    return tuple(out)


def parse_spec(data: Any, where: str = "spec") -> CrateSpec:
    """Check a spec mapping (see the module docstring). Every problem -> one line in
    CrateSpecError.errors."""
    if not isinstance(data, Mapping):
        raise CrateSpecError(where, [f"expected a mapping with name, size and brief, got {type(data).__name__}"])
    errors: list[str] = []
    unknown = sorted(str(k) for k in data if k not in SPEC_KEYS)
    if unknown:
        errors.append(f"unknown key(s) {', '.join(unknown)} (known: {', '.join(SPEC_KEYS)})")

    name = _text(data, "name", errors)
    control = next((ch for ch in name if unicodedata.category(ch) == "Cc"), None)
    if control is not None:  # rekordbox XML cannot carry most of them: the playlist name would change
        errors.append(f"`name` holds a control character ({control!r}): use letters, digits and punctuation")
    elif name and not "".join(ch for ch in name if not unicodedata.category(ch).startswith("C")).strip():
        errors.append(f"`name` must be a non-empty text you can see, got {name!r}")  # zero-width only
    elif len(name) > MAX_NAME:
        errors.append(f"`name` must be at most {MAX_NAME} characters, got {len(name)}")
    brief = _text(data, "brief", errors)
    size = data.get("size")
    if size is None:
        errors.append("`size` is missing (30, 50 or 70)")
    elif isinstance(size, bool) or size not in SIZES:
        errors.append(f"`size` must be 30, 50 or 70, got {size!r}")

    bpm: tuple[float, float] | None = None
    raw_bpm = data.get("bpm")
    if raw_bpm is not None:
        if (
            not isinstance(raw_bpm, list)
            or len(raw_bpm) != 2
            or not all(_is_number(v) for v in raw_bpm)
            or not 0 < raw_bpm[0] <= raw_bpm[1] <= MAX_BPM
        ):
            errors.append(f"`bpm` must be [low, high] with 0 < low <= high <= {MAX_BPM}, got {raw_bpm!r}")
        else:
            bpm = (float(raw_bpm[0]), float(raw_bpm[1]))

    lists = {key: _texts(data, key, errors) for key in LIST_KEYS}
    codes: list[str] = []
    for key in lists["keys"]:
        code = camelot(key)
        if code is None:
            errors.append(f"`keys`: {key!r} is not a key (write Am, 8A or 1m)")
        elif code not in codes:
            codes.append(code)
    anchors = _texts(data, "anchors", errors)

    min_rating = data.get("min_rating", 0)
    if min_rating is None:
        min_rating = 0
    if isinstance(min_rating, bool) or not isinstance(min_rating, int) or not 0 <= min_rating <= 5:
        errors.append(f"`min_rating` must be a whole number of stars, 0 to 5, got {min_rating!r}")
        min_rating = 0
    curve = data.get("curve", "flat")
    if curve is None:
        curve = "flat"
    if curve not in CURVES:
        errors.append(f"`curve` must be one of {', '.join(CURVES)}, got {curve!r}")
        curve = "flat"

    if errors:
        raise CrateSpecError(where, errors)
    return CrateSpec(
        name=name,
        size=int(size),
        brief=brief,
        bpm=bpm,
        lanes=lists["lanes"],
        genres=lists["genres"],
        exclude_genres=lists["exclude_genres"],
        keys=tuple(codes),
        anchors=anchors,
        my_tags=lists["my_tags"],
        min_rating=min_rating,
        curve=curve,
    )


def load_spec(path: str | Path, where: str | None = None) -> CrateSpec:
    """Read and check `crates/<slug>.spec.yaml`. Problems -> CrateSpecError (one line each)."""
    path = Path(path)
    where = where or path.name
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise CrateError(f"{where} not found. Write the spec first (dj-crate shows the format).") from None
    except (yaml.YAMLError, UnicodeDecodeError) as exc:
        raise CrateSpecError(where, [f"not valid YAML ({_one_line(exc)})"]) from exc
    except OSError as exc:
        raise CrateError(f"{where}: cannot read it ({exc.strerror or exc}).") from exc
    return parse_spec(data, where)


def _folder(folder: LibraryFolder | str | Path) -> LibraryFolder:
    return folder if isinstance(folder, LibraryFolder) else LibraryFolder(Path(folder))


def spec_path(folder: LibraryFolder | str | Path, ref: str) -> tuple[str, Path]:
    """(slug, path) of a spec named by its slug or by its path (relative to the library
    folder, or absolute). It must be `crates/<slug>.spec.yaml` inside the library folder."""
    folder = _folder(folder)
    text = str(ref or "").strip().strip(QUOTES + " \t")
    if not text:
        raise CrateError("Name the crate: its slug, or the path of crates/<slug>.spec.yaml.")
    if SLUG.match(text):
        rel = f"crates/{text}{SPEC_SUFFIX}"
    else:
        candidate = Path(text)
        try:
            rel = folder.relative(candidate if candidate.is_absolute() else folder.root / candidate)
        except LibraryFolderError:
            raise CrateError(f"{text} is outside the library folder: a spec is crates/<slug>.spec.yaml.") from None
        parts = rel.split("/")
        stem = parts[-1][: -len(SPEC_SUFFIX)] if parts[-1].endswith(SPEC_SUFFIX) else ""
        if len(parts) != 2 or parts[0] != "crates" or not SLUG.match(stem):
            raise CrateError(
                f"{text}: a spec is crates/<slug>.spec.yaml, the slug in lower-case letters, digits and '-'."
            )
    path = folder.root / rel
    if not path.is_file():
        raise CrateError(f"{rel} not found. Write the spec first (dj-crate shows the format).")
    return path.name[: -len(SPEC_SUFFIX)], path


# -- selection -----------------------------------------------------------------------------


@dataclass(frozen=True)
class Pick:
    """One track of the crate."""

    id: str
    track: str  # "Artist - Title"
    bpm: float
    key: str
    genre: str
    rating: int
    plays: int
    score: int
    reason: str
    tier: str  # low | mid | high: BPM tercile of the pool
    anchor: bool = False  # named in the spec's anchors
    spare: bool = False

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.id,
            "track": self.track,
            "bpm": _num(self.bpm),
            "key": self.key,
            "genre": self.genre,
            "rating": self.rating,
            "score": self.score,
            "tier": self.tier,
            "reason": self.reason,
        }
        if self.anchor:
            out["anchor"] = True
        return out


@dataclass(frozen=True)
class CrateResult:
    picks: tuple[Pick, ...]
    spares: tuple[Pick, ...]
    counts: dict[str, int] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    tiers: tuple[float, float] = (0.0, 0.0)  # the BPM tercile bounds of the pool


@dataclass(frozen=True)
class _Lane:
    label: str
    lo: int
    hi: int
    key: str
    playlists: tuple[str, ...]

    def holds(self, bpm: float) -> bool:
        return self.lo <= _half_up(bpm) <= self.hi

    @property
    def centre(self) -> float:
        return (self.lo + self.hi) / 2


def _half_up(value: float) -> int:
    return math.floor(value + 0.5)


def _taste_parts(taste_facts: Mapping[str, Any] | None) -> tuple[list[_Lane], list[str], dict[tuple[str, str], int]]:
    """(lanes by low end, anchor ids, pair -> shared playlists) from taste facts: the dict
    `load_taste` returns, or `dj.analysis.taste.facts(lib)` itself."""
    facts = taste_facts or {}
    try:
        lanes = sorted(
            (
                _Lane(str(x["label"]), int(x["lo"]), int(x["hi"]), str(x.get("key", "")),
                      tuple(str(p) for p in x.get("playlists", ())))
                for x in facts.get("lanes", [])
            ),
            key=lambda lane: (lane.lo, lane.hi, lane.label),
        )  # fmt: skip
        anchors = [str(a["id"]) if isinstance(a, Mapping) else str(a) for a in facts.get("anchors", [])]
        raw = facts.get("pairs")
        if raw is None:
            raw = (facts.get("cooccurrence") or {}).get("pairs", [])
        pairs: dict[tuple[str, str], int] = {}
        for a, b, n in raw:
            pairs[_pair(str(a), str(b))] = int(n)
    except (KeyError, TypeError, ValueError) as exc:
        raise CrateError(f"the taste facts are not in the expected shape ({exc!r}). Run dj-taste again.") from exc
    return lanes, anchors, pairs


def _pair(a: str, b: str) -> tuple[str, str]:
    return (a, b) if id_sort_key(a) <= id_sort_key(b) else (b, a)


def _named_lanes(spec: CrateSpec, lanes: list[_Lane]) -> list[_Lane]:
    """The lanes the spec names: by label ("118-124"), key ("lane:..." or without the prefix)
    or one of its playlists. An unknown name -> CrateError listing the lanes there are."""
    named: list[_Lane] = []
    unknown = []
    for ref in spec.lanes:
        want = ref.strip().casefold()
        hits = [
            lane for lane in lanes
            if want in {lane.label.casefold(), lane.key.casefold(), lane.key.casefold().removeprefix("lane:")}
            or want in {p.casefold() for p in lane.playlists}
        ]  # fmt: skip
        if not hits:
            unknown.append(ref)
        for lane in hits:
            if lane not in named:
                named.append(lane)
    if unknown:
        known = ", ".join(lane.label for lane in lanes[:SHOWN])
        known += f" (+{len(lanes) - SHOWN} more)" if len(lanes) > SHOWN else ""
        there = f"Lanes in taste/lanes.md: {known}."
        if not lanes:
            there = "taste/ has no lanes yet: run dj-taste, or use `bpm`."
        raise CrateError(f"`lanes`: no lane {', '.join(map(repr, unknown))}. {there}")
    return named


def _failed(track: Track, spec: CrateSpec, named: list[_Lane]) -> list[str]:
    """The filters `track` fails, in FILTERS order (empty: it passes them all)."""
    out = []
    if spec.bpm and not spec.bpm[0] <= track.bpm <= spec.bpm[1]:
        out.append("bpm")
    if named and not any(lane.holds(track.bpm) for lane in named):
        out.append("lanes")
    if spec.genres and not genre_fit(track.genre, spec.genres):
        out.append("genres")
    if spec.exclude_genres and genre_fit(track.genre, spec.exclude_genres):
        out.append("exclude_genres")
    if spec.keys and not key_fit(track.key, spec.keys)[0]:
        out.append("keys")
    if track.rating < spec.min_rating:
        out.append("min_rating")
    return out


@dataclass(frozen=True)
class _Scored:
    track: Track
    score: int
    reason: str


def _plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one}" if n == 1 else f"{n} {many or one + 's'}"


class _Scorer:
    def __init__(
        self,
        lib: Library,
        spec: CrateSpec,
        lanes: list[_Lane],
        named: list[_Lane],
        pairs: dict[tuple[str, str], int],
        refs: list[str],
        taste_anchors: set[str],
        feedback: Mapping[str, int] | None = None,
    ) -> None:
        self.lib, self.spec, self.lanes, self.named, self.pairs = lib, spec, lanes, named, pairs
        self.refs, self.taste_anchors = refs, taste_anchors
        self.feedback = feedback or {}
        if named:
            self.centres = [lane.centre for lane in named]
        elif spec.bpm:
            self.centres = [(spec.bpm[0] + spec.bpm[1]) / 2]
        else:
            self.centres = []

    def lane_of(self, bpm: float) -> _Lane | None:
        return next((lane for lane in (self.named or self.lanes) if lane.holds(bpm)), None)

    def score(self, t: Track) -> _Scored:
        spec = self.spec
        points, parts = 0, []
        if t.id in spec.anchors:
            parts.append("anchor you named")
        lane = self.lane_of(t.bpm)
        if lane is not None:
            points += W_LANE
            parts.append(f"lane {lane.label}")
        else:
            parts.append(f"{_num(t.bpm)} BPM")
        if self.centres:
            distance = min(abs(t.bpm - c) for c in self.centres)
            points += max(0, W_CENTRE - _half_up(distance))
        shared = [(self.pairs.get(_pair(t.id, a), 0), n, a) for n, a in enumerate(self.refs) if a != t.id]
        total = sum(s for s, _n, _a in shared)
        if total:
            points += min(MAX_PAIR, W_PAIR * total)
            best, _n, partner = max(shared, key=lambda x: (x[0], -x[1]))
            parts.append(f"plays with {self.lib.tracks[partner].label_line} in {_plural(best, 'playlist')}")
        if t.id in self.taste_anchors:
            points += W_TASTE_ANCHOR
            parts.append("one of your anchors")
        if spec.genres:
            fit = genre_fit(t.genre, spec.genres)
            if fit:
                points += W_GENRE if fit == 2 else W_GENRE_NEAR
                parts.append(t.genre.strip())
        if spec.keys:
            fit, want = key_fit(t.key, spec.keys)
            if fit == 2:
                points += W_KEY
                parts.append(f"key {want}")
            elif fit == 1:
                points += W_KEY_NEAR
                parts.append(f"key {camelot(t.key)}, next to {want}")
        if spec.my_tags:
            have = {tag.casefold() for tag in t.my_tags}
            tags = [tag for tag in spec.my_tags if tag.casefold() in have]
            if tags:
                points += min(MAX_TAG, W_TAG * len(tags))
                parts.append(("My Tag " if len(tags) == 1 else "My Tags ") + ", ".join(tags))
        stars = max(0, min(5, t.rating))
        if stars:
            points += W_STAR * stars
            parts.append(_plural(stars, "star"))
        if t.play_count > 0:
            points += W_PLAYS * min(t.play_count, 255).bit_length()
            parts.append("played once" if t.play_count == 1 else f"played {t.play_count} times")
        sign = self.feedback.get(t.id, 0)
        if sign:
            points += W_FEEDBACK * sign
            parts.append("worked at a gig" if sign > 0 else "flopped at a gig")
        return _Scored(t, points, " · ".join(parts))


def _quantile(values: list[float], q: float) -> float:
    """Linear interpolation between closest ranks (as dj.analysis.taste does)."""
    pos = (len(values) - 1) * q
    low = math.floor(pos)
    high = min(low + 1, len(values) - 1)
    return values[low] + (values[high] - values[low]) * (pos - low)


def _tier(bpm: float, bounds: tuple[float, float]) -> str:
    if bpm <= bounds[0]:
        return TIERS[0]
    return TIERS[1] if bpm <= bounds[1] else TIERS[2]


def _quotas(spares: int) -> dict[str, int]:
    """A third of the spares per tier; what does not divide goes to mid, then high."""
    base, extra = divmod(spares, 3)
    return {"low": base, "mid": base + (extra >= 1), "high": base + (extra >= 2)}


def _set_filters(spec: CrateSpec) -> list[str]:
    """The filters the spec sets, in FILTERS order."""
    return [name for name in FILTERS if getattr(spec, name)]


def _widen(spec: CrateSpec, rows: list[tuple[Track, list[str]]]) -> tuple[str | None, int]:
    """The set filter whose widening lets in the most tracks (ties: FILTERS order), and how
    many tracks fit without it. (None, 0) when the spec sets no filter."""
    best: tuple[str | None, int] = (None, 0)
    for name in _set_filters(spec):
        n = sum(1 for _t, failed in rows if set(failed) <= {name})
        if best[0] is None or n > best[1]:
            best = (name, n)
    return best


def select(
    lib: Library,
    spec: CrateSpec,
    taste_facts: Mapping[str, Any] | None = None,
    vetoes: Vetoes | None = None,
    feedback: Mapping[str, int] | None = None,
) -> CrateResult:
    """Pick exactly `spec.size` tracks and ceil(0.2 * size) spares from `lib` (see the module
    docstring). Pure and deterministic: no files, no clock. Too few tracks fit ->
    NotEnoughTracks; an unknown anchor or lane, or two anchors that are a never-pair ->
    CrateError. A veto names the song: it holds for every copy of a vetoed track in `lib`
    (`Vetoes.with_copies`), so the FLAC of a vetoed MP3 stays out too (R-702). `feedback`: track id
    -> +1 (worked at a gig) / -1 (flopped), from `taste_files.feedback_scores`: added to the score;
    a flopped track is never a spare."""
    named_vetoes = vetoes or Vetoes()
    feedback = {str(k): v for k, v in (feedback or {}).items() if v}
    vetoes = named_vetoes.with_copies(lib.tracks.values())
    lanes, taste_anchor_list, pairs = _taste_parts(taste_facts)
    named = _named_lanes(spec, lanes)
    tracks = sorted(lib.tracks.values(), key=lambda t: id_sort_key(t.id))
    warnings: list[str] = []

    unknown = [a for a in spec.anchors if a not in lib.tracks]
    if unknown:
        raise CrateError(f"`anchors`: {', '.join(unknown)} not in the library (track ids from the export).")

    counts = {"no_file": 0, "no_bpm": 0, "vetoed": 0}
    rows: list[tuple[Track, list[str]]] = []  # tracks that could be picked, with the filters they fail
    pool: list[Track] = []
    for t in tracks:
        if not t.location:
            counts["no_file"] += 1
            continue
        if t.bpm <= 0:
            counts["no_bpm"] += 1
            continue
        failed = _failed(t, spec, named)
        if vetoes.blocks(t.id):
            counts["vetoed"] += 0 if failed else 1  # vetoed and would have fitted
            continue
        rows.append((t, failed))
        if not failed:
            pool.append(t)
    pool_ids = {t.id for t in pool}

    anchors: list[Track] = []
    for tid in spec.anchors:
        t = lib.tracks[tid]
        if vetoes.blocks(tid):
            how = "is vetoed" if named_vetoes.blocks(tid) else "is a copy of a track vetoed"
            warnings.append(f"Anchor {t.label_line} ({tid}) {how} in {VETOES_FILE}: left out.")
            continue
        if not t.location:
            warnings.append(f"Anchor {t.label_line} ({tid}) has no file location: left out.")
            continue
        key = dup_key(t.artist, t.title, t.remixer)
        twin = next((a for a in anchors if key and dup_key(a.artist, a.title, a.remixer) == key), None)
        if twin is not None:
            warnings.append(
                f"Anchor {t.label_line} ({tid}) is a second copy of anchor {twin.id}: left out (one copy per crate)."
            )
            continue
        clash = next((a for a in anchors if vetoes.blocks_pair(a.id, tid)), None)
        if clash is not None:
            raise CrateError(
                f"Anchors {clash.label_line} ({clash.id}) and {t.label_line} ({tid}) are a never-pair in "
                f"{VETOES_FILE}: drop one of them from `anchors`."
            )
        if tid not in pool_ids:
            why = ", ".join(_failed(t, spec, named)) or ("no BPM" if t.bpm <= 0 else "")
            warnings.append(f"Anchor {t.label_line} ({tid}) is outside the spec ({why}): in because you named it.")
        anchors.append(t)
    if len(anchors) > spec.size:
        raise CrateError(f"`anchors` name {len(anchors)} tracks; a crate of {spec.size} holds at most {spec.size}.")

    refs = [t.id for t in anchors] if spec.anchors else [a for a in taste_anchor_list if a in pool_ids]
    taste_anchors = set() if spec.anchors else set(refs)
    scorer = _Scorer(lib, spec, lanes, named, pairs, refs, taste_anchors, feedback)
    anchor_ids = {t.id for t in anchors}
    scored = {t.id: scorer.score(t) for t in pool}
    for t in anchors:
        scored.setdefault(t.id, scorer.score(t))
    ranked = sorted(
        (scored[t.id] for t in pool if t.id not in anchor_ids), key=lambda s: (-s.score, id_sort_key(s.track.id))
    )

    crate: list[_Scored] = [scored[t.id] for t in anchors]
    copies = {dup_key(t.artist, t.title, t.remixer) for t in anchors} - {""}

    def blocked(s: _Scored) -> bool:
        key = dup_key(s.track.artist, s.track.title, s.track.remixer)
        if key and key in copies:
            return True
        return any(vetoes.blocks_pair(s.track.id, c.track.id) for c in crate)

    def take(s: _Scored) -> None:
        crate.append(s)
        key = dup_key(s.track.artist, s.track.title, s.track.remixer)
        if key:
            copies.add(key)

    for s in ranked:
        if len(crate) >= spec.size:
            break
        if not blocked(s):
            take(s)
    if len(crate) < spec.size:
        widen, could = _widen(spec, rows)
        found = len(crate)
        left_out = []
        if counts["vetoed"]:
            left_out.append(f"{counts['vetoed']} vetoed")
        held = len(pool) + len([t for t in anchors if t.id not in pool_ids]) - found
        if held > 0:
            left_out.append(f"{held} never-pair partners or second copies")
        after = f" ({', '.join(left_out)} left out)" if left_out else ""
        if widen:
            how = f" Widen `{widen}`: without it {could} tracks fit."
        else:
            how = f" The library has {len(rows)} tracks with a file and a BPM that are not vetoed."
        smaller = [s for s in SIZES if s <= found]
        size_hint = f" Or make it a crate of {smaller[-1]}." if smaller else ""
        raise NotEnoughTracks(
            f"Only {found} tracks fit this spec{after}; the crate needs {spec.size}.{how}{size_hint}",
            found=found,
            needed=spec.size,
            widen=widen,
        )
    picks_ids = {s.track.id for s in crate}

    bpms = sorted(t.bpm for t in pool)
    bounds = (_quantile(bpms, 1 / 3), _quantile(bpms, 2 / 3)) if bpms else (0.0, 0.0)
    quota = _quotas(spec.spares)
    spares: list[_Scored] = []
    # a track that flopped at a gig is never a spare (R-702); it can still be a pick, a point lower
    rest = [s for s in ranked if s.track.id not in picks_ids and feedback.get(s.track.id, 0) >= 0]
    for s in rest:  # pass 1: by score, within each tier's share
        if len(spares) >= spec.spares:
            break
        tier = _tier(s.track.bpm, bounds)
        if quota[tier] > 0 and not blocked(s):
            quota[tier] -= 1
            take(s)
            spares.append(s)
    for s in rest:  # pass 2: a tier ran short, fill from the others
        if len(spares) >= spec.spares:
            break
        if s not in spares and not blocked(s):
            take(s)
            spares.append(s)
    if len(spares) < spec.spares:
        widen, _could = _widen(spec, rows)
        more = f" Widen `{widen}` for more." if widen else ""
        if spares:
            warnings.append(f"Only {len(spares)} spares fit (the crate wants {spec.spares}).{more}")
        else:
            warnings.append(f"No spares fit (the crate wants {spec.spares}): no spares playlist.{more}")

    in_crate = {s.track.id for s in crate}
    never_pair = duplicates = 0
    keys = {dup_key(s.track.artist, s.track.title, s.track.remixer) for s in crate} - {""}
    for t in pool:
        if t.id in in_crate:
            continue
        if any(vetoes.blocks_pair(t.id, other) for other in in_crate):
            never_pair += 1
        elif dup_key(t.artist, t.title, t.remixer) in keys:
            duplicates += 1
    if spec.my_tags and not any(t.my_tags for t in tracks):
        warnings.append(
            "My Tags are not in the XML export: `my_tags` did not count (the engine reads them from master.db)."
        )

    def pick(s: _Scored, spare: bool) -> Pick:
        t = s.track
        return Pick(
            id=t.id, track=t.label_line, bpm=t.bpm, key=t.key, genre=t.genre, rating=t.rating,
            plays=t.play_count, score=s.score, reason=s.reason, tier=_tier(t.bpm, bounds),
            anchor=t.id in anchor_ids, spare=spare,
        )  # fmt: skip

    picks = _ordered([pick(s, False) for s in crate[: spec.size]], spec.curve)
    spare_picks = sorted((pick(s, True) for s in spares), key=lambda p: (TIERS.index(p.tier), p.bpm, id_sort_key(p.id)))
    return CrateResult(
        picks=tuple(picks),
        spares=tuple(spare_picks),
        counts={
            "picks": len(picks),
            "spares": len(spare_picks),
            "candidates": len(pool),
            "vetoed": counts["vetoed"],
            "never_pair": never_pair,
            "duplicates": duplicates,
            "no_file": counts["no_file"],
            "no_bpm": counts["no_bpm"],
            "worked": sum(feedback.get(t.id, 0) > 0 for t in pool),
            "flopped": sum(feedback.get(t.id, 0) < 0 for t in pool),
            "tracks": len(lib.tracks),
        },
        warnings=tuple(warnings),
        tiers=(round(bounds[0], 2), round(bounds[1], 2)),
    )


def _ordered(picks: list[Pick], curve: str) -> list[Pick]:
    """The picks in the order of the curve (see the module docstring)."""
    if curve == "flat":
        return sorted(picks, key=lambda p: (-p.score, id_sort_key(p.id)))
    rising = sorted(picks, key=lambda p: (p.bpm, -p.score, id_sort_key(p.id)))
    if curve == "warmup":
        return rising
    tail = len(picks) // 5
    if tail == 0:
        return rising
    top = rising[len(rising) - 2 * tail :]
    easing = [p for i, p in enumerate(top) if (len(top) - 1 - i) % 2 == 1]
    climb = [p for p in rising if p not in easing]
    return climb + list(reversed(easing))


# -- the library folder: spec, export, taste, vetoes ---------------------------------------


def _library(folder: LibraryFolder, source: str | None = None) -> tuple[Library, str]:
    """The latest export, or a master.db snapshot for `source` db (library.yaml's when None, W-38)."""
    try:
        return read_for_build(folder, source)
    except (LibraryFolderError, LibraryError, ValueError) as exc:
        raise CrateError(str(exc)) from exc


def load_taste(
    folder: LibraryFolder | str | Path, lib: Library, export: str = "the export"
) -> tuple[dict[str, Any], str, tuple[str, ...]]:
    """(taste facts for `select`, where they came from, warnings).

    `taste/facts.json` (lanes, anchors) and `taste/cooccurrence.json` (pairs) when dj-taste has
    run; else the same facts measured now from the library (`dj.analysis.taste.facts`)."""
    folder = _folder(folder)
    facts_path, pairs_path = folder.root / TASTE_FACTS, folder.root / TASTE_PAIRS
    if facts_path.is_file():
        try:
            facts = json.loads(facts_path.read_text(encoding="utf-8"))
            pairs = json.loads(pairs_path.read_text(encoding="utf-8")).get("pairs", []) if pairs_path.is_file() else []
        except (OSError, ValueError, AttributeError) as exc:
            raise CrateError(f"{TASTE_FACTS} or {TASTE_PAIRS}: cannot read it ({exc}). Run dj-taste again.") from exc
        if not isinstance(facts, dict):
            raise CrateError(f"{TASTE_FACTS}: expected a mapping. Run dj-taste again.")
        warnings = () if pairs_path.is_file() else (f"{TASTE_PAIRS} is missing: co-occurrence did not count.",)
        source = TASTE_FACTS + (f" and {TASTE_PAIRS}" if pairs_path.is_file() else "")
        return {"lanes": facts.get("lanes", []), "anchors": facts.get("anchors", []), "pairs": pairs}, source, warnings
    measured = taste_analysis.facts(lib)
    data = {"lanes": measured["lanes"], "anchors": measured["anchors"], "pairs": measured["cooccurrence"]["pairs"]}
    warning = f"{TASTE_FACTS} is missing: lanes and anchors measured now from {export}."
    return data, f"measured now from {export}", (warning,)


def _vetoes(folder: LibraryFolder) -> Vetoes:
    try:
        return read_vetoes(folder.root / VETOES_FILE)
    except LibraryError as exc:
        raise CrateError(f"{VETOES_FILE}: {exc}") from exc
    except OSError as exc:
        raise CrateError(f"{VETOES_FILE}: cannot read it ({exc.strerror or exc}).") from exc


def _feedback(folder: LibraryFolder, lib: Library) -> dict[str, int]:
    """Track id -> +1 / -1 from the signed lines of taste/feedback.md (none when it is missing)."""
    try:
        return feedback_scores(read_gig_feedback(folder.root / FEEDBACK_FILE), lib.tracks.values())
    except LibraryError as exc:
        raise CrateError(f"{FEEDBACK_FILE}: {exc}") from exc
    except OSError as exc:
        raise CrateError(f"{FEEDBACK_FILE}: cannot read it ({exc.strerror or exc}).") from exc


def _playlist_names(name: str, result: CrateResult) -> tuple[str, ...]:
    """The crate's playlists: `<name>` with the picks, and `<name> spares` when spares fit."""
    return (name, name + SPARES_SUFFIX) if result.spares else (name,)


@dataclass(frozen=True)
class _Top:
    """A top-level node of the DJ's tree: names and kinds only."""

    name: str
    folder: bool
    children: tuple[str, ...]
    where: str = ""  # "" = the latest export; else the file that lists it


def _tops(folder: LibraryFolder, lib: Library) -> tuple[list[_Top], tuple[str, ...]]:
    """(the top level of the DJ's tree, warnings): the latest export's, then
    `structure/current-tree.yaml`'s when dj-structure has written one (it can be newer)."""
    tops = [_Top(n.name, n.kind == "folder", tuple(c.name for c in n.children)) for n in lib.roots]
    path = folder.root / CURRENT_TREE
    if not path.is_file():
        return tops, ()
    try:
        doc = treeschema.load(path)
    except (TreeSchemaError, UnicodeDecodeError, OSError) as exc:
        return tops, (f"{CURRENT_TREE} cannot be read ({_one_line(exc)}): only the export's tree was checked.",)
    tops += [_Top(n.name, n.kind == "folder", tuple(c.name for c in n.children), CURRENT_TREE) for n in doc.nodes]
    return tops, ()


def _same(a: str, b: str) -> bool:
    return treeschema.norm(a) == treeschema.norm(b)


def _placement(
    tops: Sequence[_Top], names: Sequence[str], slug: str
) -> tuple[str, list[dict[str, str]], str | None]:
    """(the folder name the XML uses, where the DJ drags what, why the crate is blocked or None).

    A top-level folder "Crates" in the DJ's tree (the export, or structure/current-tree.yaml) is
    used as it is spelled; a playlist of the crate's name already in it blocks the crate (hard
    rule 5). `names`: the crate's playlists (`_playlist_names`)."""
    hits = [t for t in tops if _same(t.name, CRATES_FOLDER)]
    if not hits:
        return CRATES_FOLDER, [{"node": CRATES_FOLDER, "into": "Playlists"}], None
    folders = [t for t in hits if t.folder]
    if not folders:
        listed = f" ({hits[0].where} lists it)" if hits[0].where else ""
        return CRATES_FOLDER, [], (
            f"A playlist named {hits[0].name!r} sits at the top of your tree{listed}, where the crate's "
            f"{CRATES_FOLDER} folder goes. Rename it in rekordbox, then preview again."
        )
    spelled = folders[0].name
    for want in names:
        for top in folders:
            taken = next((c for c in top.children if _same(c, want)), None)
            if taken is not None:
                listed = f" ({top.where} lists it)" if top.where else ""
                return spelled, [], (
                    f"{spelled}/{taken} exists in rekordbox already{listed}. Change `name:` in "
                    f"crates/{slug}{SPEC_SUFFIX}, then preview again."
                )
    return spelled, [{"node": f"{spelled}/{n}", "into": spelled} for n in names], None


@dataclass(frozen=True)
class _Written:
    """A crate XML written since the latest export: the DJ may have imported it already."""

    file: str  # relative to the library folder
    when: str  # local 'YYYY-MM-DD HH:MM' (the file's time)
    folder: str  # its Crates folder, as spelled
    playlists: tuple[str, ...]


def _own_file(folder: LibraryFolder, slug: str, digest: str) -> str | None:
    """The file this exact crate was written to already (its gate record is used), or None."""
    try:
        record = Gate(folder.cache).load(preview_id_for(KIND, {"crate": slug}, digest))
    except GateError:
        return None
    return record.written if record.used else None


def _written_since(folder: LibraryFolder, export: str, skip: str | None) -> list[_Written]:
    """The crate XMLs in proposals/ written since the latest export, oldest first. Both times are
    file times (one clock). `skip`: the file this exact crate went to (the preview says
    "Already written" for it). A file that does not read as a rekordbox XML is not a crate."""
    try:
        since = (folder.root / export).stat().st_mtime_ns
    except OSError:
        return []
    found: list[tuple[int, _Written]] = []
    for path in sorted(folder.proposals.glob("crate-*.xml")):
        rel = folder.relative(path)
        if rel == skip:
            continue
        try:
            stamp = path.stat().st_mtime_ns
            if stamp < since:
                continue
            roots = read_xml(path).roots
        except (OSError, LibraryError):
            continue
        when = datetime.fromtimestamp(stamp / 1e9).strftime("%Y-%m-%d %H:%M")
        for node in roots:
            if node.kind == "folder" and _same(node.name, CRATES_FOLDER):
                found.append((stamp, _Written(rel, when, node.name, tuple(c.name for c in node.children))))
    return [w for _stamp, w in sorted(found, key=lambda x: (x[0], x[1].file))]


def _since_export(
    written: Sequence[_Written],
    tops: Sequence[_Top],
    folder_name: str,
    moves: list[dict[str, str]],
    names: Sequence[str],
    slug: str,
) -> tuple[list[dict[str, str]], str | None, tuple[str, ...]]:
    """(moves, why blocked or None, warnings) once the crates written since the latest export
    count: the export cannot show them, but the DJ may have imported them (hard rule 5). A
    playlist of the crate's name in one blocks the crate, as one in rekordbox does; a Crates
    folder in one, while the tree has none, makes the import card drag the two playlists into
    that folder, with a warning for the case it was not imported."""
    for w in written:
        for want in names:
            taken = next((p for p in w.playlists if _same(p, want)), None)
            if taken is not None:
                return moves, (
                    f"{w.folder}/{taken} is in {w.file}, written {w.when}, after your latest export: if you "
                    f"imported it, rekordbox has that playlist. Change `name:` in crates/{slug}{SPEC_SUFFIX}, "
                    "or, if you did not import it, export the collection again; then preview again."
                ), ()
    if not written or any(t.folder and _same(t.name, CRATES_FOLDER) for t in tops):
        return moves, None, ()
    last = written[-1]
    into = [{"node": f"{folder_name}/{n}", "into": last.folder} for n in names]
    lists = "the two playlists" if len(names) == 2 else "the playlist"
    warning = (
        f"{last.file} (written {last.when}, after your latest export) holds a {last.folder} folder too: "
        f"if you imported it, drag {lists} into that folder, as the import card says; if not, "
        f"drag the whole {folder_name} folder into Playlists."
    )
    return into, None, (warning,)


@dataclass(frozen=True)
class _State:
    slug: str
    spec: CrateSpec
    spec_file: str
    result: CrateResult
    export: str
    taste: str
    folder_name: str
    moves: tuple[dict[str, str], ...]
    blocked: str | None
    digest: str
    warnings: tuple[str, ...]
    lib: Library
    playlists: tuple[str, ...] = ()  # the playlists in the Crates folder: the picks, the spares if any
    placement_warnings: tuple[str, ...] = ()  # the import card needs them too (a crate since the export)


def _digest(slug: str, spec: CrateSpec, export: str, folder_name: str, result: CrateResult) -> str:
    payload = {
        "crate": slug,
        "spec": spec.to_dict(),
        "export": export,
        "folder": folder_name,
        "picks": [[p.id, p.reason] for p in result.picks],
        "spares": [[p.id, p.tier, p.reason] for p in result.spares],
    }
    text = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _state(folder: LibraryFolder, ref: str, source: str | None = None) -> _State:
    slug, path = spec_path(folder, ref)
    spec_file = folder.relative(path)
    spec = load_spec(path, spec_file)
    lib, export = _library(folder, source)
    taste, taste_source, taste_warnings = load_taste(folder, lib, export)
    result = select(lib, spec, taste, _vetoes(folder), _feedback(folder, lib))
    names = _playlist_names(spec.name, result)
    tops, tree_warnings = _tops(folder, lib)
    folder_name, moves, blocked = _placement(tops, names, slug)
    digest = _digest(slug, spec, export, folder_name, result)
    since_warnings: tuple[str, ...] = ()
    if blocked is None:
        written = _written_since(folder, export, _own_file(folder, slug, digest))
        moves, blocked, since_warnings = _since_export(written, tops, folder_name, moves, names, slug)
    return _State(
        slug=slug,
        spec=spec,
        spec_file=spec_file,
        result=result,
        export=export,
        taste=taste_source,
        folder_name=folder_name,
        moves=tuple(moves),
        blocked=blocked,
        digest=digest,
        warnings=tuple(taste_warnings) + result.warnings + tree_warnings + since_warnings,
        lib=lib,
        playlists=names,
        placement_warnings=since_warnings,
    )


# -- preview (R-601, R-602, R-604) ---------------------------------------------------------


@dataclass(frozen=True)
class CratePreview:
    picks: tuple[Pick, ...]
    spares: tuple[Pick, ...]
    counts: dict[str, int]
    digest: str
    preview_id: str | None  # None when the crate is blocked: nothing to approve
    slug: str = ""
    name: str = ""
    spec_file: str = ""
    export: str = ""
    taste: str = ""
    curve: str = "flat"
    playlists: tuple[str, ...] = ()
    blocked: str | None = None
    warnings: tuple[str, ...] = ()
    filters: str = ""

    def to_dict(self, limit: int = PICKS_LIMIT) -> dict[str, Any]:
        """`limit` picks in the result (0 = all of them: the MCP tool pages them, NFR-03)."""
        limit = limit if limit > 0 else len(self.picks)
        shown = [{"n": n, **p.to_dict()} for n, p in enumerate(self.picks[:limit], 1)]
        return {
            "counts": self.counts,
            "crate": self.slug,
            "name": self.name,
            "preview_id": self.preview_id,
            "blocked": self.blocked,
            "written": "Nothing written yet.",
            "spec": self.spec_file,
            "export": self.export,
            "taste": self.taste,
            "filters": self.filters,
            "curve": self.curve,
            "playlists": list(self.playlists),
            "picks": shown,
            "picks_more": max(0, len(self.picks) - limit),
            "spares": [{"n": n, **p.to_dict()} for n, p in enumerate(self.spares, 1)],
            "warnings": list(self.warnings),
        }


def _local(stamp: str) -> str:
    """A stored ISO time as local 'YYYY-MM-DD HH:MM' (the text as it is if unreadable)."""
    try:
        moment = datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        return str(stamp)
    return (moment.astimezone() if moment.tzinfo else moment).strftime("%Y-%m-%d %H:%M")


def preview(
    folder: LibraryFolder | str | Path,
    spec_ref: str,
    *,
    today: date | None = None,
    now: datetime | None = None,
    source: str | None = None,
) -> CratePreview:
    """The crate the spec gives, and a preview id for the gate. Writes nothing but the gate
    record in `.cache/previews/` (no XML, no MD). `today` is accepted for the shared interface
    (the files carry their date at `apply`); `now` dates the gate record (tests)."""
    del today
    folder = _folder(folder)
    state = _state(folder, spec_ref, source)
    preview_id, blocked = None, state.blocked
    if blocked is None:
        gate = Gate(folder.cache)
        preview_id = gate.record(KIND, {"crate": state.slug}, state.digest, now=now)
        if gate.load(preview_id).written == DB_READ:  # written into rekordbox, gone from its tree since (W-38)
            preview_id = gate.record(KIND, {"crate": state.slug}, state.digest, now=now, rearm=True)
        record = gate.load(preview_id)
        if record.used:
            blocked = (
                f"Already written on {_local(record.used)}: {record.written or 'an XML in proposals/'}. "
                f"Import that file; it holds this exact crate. For another crate, change "
                f"{state.spec_file} and preview again."
            )
            preview_id = None
    name = state.spec.name
    return CratePreview(
        picks=state.result.picks,
        spares=state.result.spares,
        counts=state.result.counts,
        digest=state.digest,
        preview_id=preview_id,
        slug=state.slug,
        name=name,
        spec_file=state.spec_file,
        export=state.export,
        taste=state.taste,
        curve=state.spec.curve,
        playlists=tuple(f"{state.folder_name}/{n}" for n in state.playlists),
        blocked=blocked,
        warnings=state.warnings,
        filters=state.spec.filters_text(),
    )


# -- apply (R-603) -------------------------------------------------------------------------


@dataclass(frozen=True)
class CrateWriteResult:
    xml_path: Path
    md_path: Path | None  # None when the MD file could not be written (see warnings)
    import_steps: tuple[str, ...]
    log_line: str
    slug: str = ""
    name: str = ""
    xml_file: str = ""  # relative to the library folder
    md_file: str = ""
    counts: dict[str, int] = field(default_factory=dict)
    device: str = ""
    warnings: tuple[str, ...] = ()  # the XML is written; where to drag it (a crate since the export), what failed after it

    def to_dict(self) -> dict[str, Any]:
        return {
            "counts": self.counts,
            "crate": self.slug,
            "name": self.name,
            "written": self.xml_file,
            "record": self.md_file,
            "device": self.device,
            "import_steps": list(self.import_steps),
            "log_line": self.log_line,
            "warnings": list(self.warnings),
        }


def _meta_device(folder: LibraryFolder) -> str:
    try:
        meta = libfolder.load_meta(folder.root)
    except LibraryFolderError as exc:
        raise CrateError(f"{exc} Nothing was written.") from exc
    errors = libfolder.validate_meta(meta)
    if errors:
        raise CrateError("library.yaml: " + "; ".join(errors) + ". Nothing was written.")
    return str(meta["device"])


def _preflight(folder: LibraryFolder) -> None:
    """Before the XML is written: log.md takes a line. Opening it to append writes nothing; it
    fails when the file is a folder, read-only or held by another program."""
    if not folder.log.exists():
        return  # created with its title line by append_log
    try:
        with open(folder.log, "a", encoding="utf-8"):
            pass
    except OSError as exc:
        raise CrateError(
            f"log.md cannot be written ({exc.strerror or exc}). Close what holds it open, then write "
            "again with the same preview id. Nothing was written."
        ) from exc


def _cell(value: Any) -> str:
    return " ".join(str(value).replace("|", "\\|").split())


def render_md(state: _State, xml_file: str, day: date) -> str:
    """crates/<slug>.md: title, provenance, a summary of at most 5 lines, then the full picks
    and spares tables (the crate record)."""
    spec, result = state.spec, state.result
    c = result.counts
    folder = state.folder_name
    left = [f"{c['vetoed']} vetoed", f"{c['never_pair']} never-pair partners", f"{c['duplicates']} second copies"]
    summary = [
        f"{c['picks']} picks and {c['spares']} spares for: {spec.brief}. Curve: {spec.curve}.",
        f"Picked from {c['candidates']} tracks that fit ({spec.filters_text()}); taste from {state.taste}.",
        "Left out: " + ", ".join(left) + ".",
        ("Written into rekordbox: playlists " if xml_file == DB_READ else f"Import {xml_file}: playlists ")
        + " and ".join(f"{folder}/{n}" for n in state.playlists) + ".",
    ]
    if state.warnings:
        summary.append("Note: " + " ".join(state.warnings))
    lines = [
        f"# Crate: {spec.name}",
        "",
        f"> Measured by code: {MODULE} from {state.spec_file} and {state.export}, {day.isoformat()}.",
        "",
        "## Summary",
        "",
        *[f"- {_cell(line)}" for line in summary],
        "",
        "## Picks",
        "",
        "| # | Track | BPM | Key | Genre | Reason |",
        "|---|---|---|---|---|---|",
    ]
    for n, p in enumerate(result.picks, 1):
        cells = (n, _cell(p.track), _num(p.bpm), _cell(p.key), _cell(p.genre), _cell(p.reason))
        lines.append("| " + " | ".join(str(c) for c in cells) + " |")
    lines += ["", "## Spares", "", "| # | Track | Energy | BPM | Key | Reason |", "|---|---|---|---|---|---|"]
    for n, p in enumerate(result.spares, 1):
        cells = (n, _cell(p.track), p.tier, _num(p.bpm), _cell(p.key), _cell(p.reason))
        lines.append("| " + " | ".join(str(c) for c in cells) + " |")
    return "\n".join(lines) + "\n"


def _write_new(path: Path, text: str) -> Path:
    """`path`, or the first free `<stem>-N<suffix>` next to it; never over an existing file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    for candidate in numbered(path):
        if libfolder.write_new_text(candidate, text):
            return candidate
    raise CrateError(f"{path.name}: every numbered name is taken. Nothing was written.")


def checked(
    folder: LibraryFolder | str | Path, spec_ref: str, preview_id: str, *, now: datetime | None = None,
    source: str | None = None,
) -> tuple[LibraryFolder, _State, Gate]:
    """Everything a write needs checked before it writes, for the XML (`apply`) and for master.db
    (`dj.db_write`): the id's shape, the crate, no block, the gate record (same content, unused),
    log.md writable. GateError / CrateError, nothing written."""
    require_id(preview_id)  # no id, no write: refused before anything is read
    folder = _folder(folder)
    _meta_device(folder)
    state = _state(folder, spec_ref, source)
    if state.blocked:
        raise CrateError(state.blocked + " Nothing was written.")
    gate = Gate(folder.cache)
    gate.check(preview_id, KIND, {"crate": state.slug}, state.digest, now=now)
    _preflight(folder)
    return folder, state, gate


def playlist_lists(state: _State) -> list[tuple[tuple[str, str], list[str]]]:
    """The crate's playlists in its Crates folder with their track ids: the picks, the spares."""
    name, result = state.spec.name, state.result
    lists = [((state.folder_name, name), [p.id for p in result.picks])]
    if result.spares:  # none fit: no empty spares playlist (the preview warned)
        lists.append(((state.folder_name, name + SPARES_SUFFIX), [p.id for p in result.spares]))
    return lists


def apply(
    folder: LibraryFolder | str | Path,
    spec_ref: str,
    preview_id: str,
    *,
    today: date | None = None,
    now: datetime | None = None,
    source: str | None = None,
) -> CrateWriteResult:
    """Write `proposals/crate-<slug>.xml` and `crates/<slug>.md` for a preview the DJ said yes
    to, then one log.md line. Refuses (GateError / CrateError, nothing written) without a valid
    preview id, after any change since the preview, when the crate is blocked, or when log.md
    cannot take its line. Once the XML is written, a later failure is a warning in the result.
    Never opens master.db."""
    folder, state, gate = checked(folder, spec_ref, preview_id, now=now, source=source)
    device = _meta_device(folder)
    name, result = state.spec.name, state.result
    lists = playlist_lists(state)
    try:
        text = build_lists_xml(lists, state.lib, product_version=product_version())
    except BuildError as exc:
        raise CrateError(f"{exc}. Nothing was written.") from exc
    xml_path = write_xml(text, folder.proposals / f"crate-{state.slug}.xml")
    # The XML is written: from here on the crate is done, and a failure below is a warning.
    xml_file = folder.relative(xml_path)
    day = today or (now.date() if now else date.today())
    warnings: list[str] = list(state.placement_warnings)  # where the playlists go, for the import card
    md_path: Path | None = None
    md_file = ""
    try:
        md_path = _write_new(folder.crates / f"{state.slug}.md", render_md(state, xml_file, day))
        md_file = folder.relative(md_path)
    except (CrateError, OSError) as exc:
        warnings.append(
            f"crates/{state.slug}.md was not written ({exc}). The XML is written; preview again for the list."
        )
    try:
        gate.consume(preview_id, now=now, written=xml_file)
    except (GateError, OSError) as exc:
        warnings.append(f"Preview {preview_id} could not be marked used ({exc}). Do not use it again.")
    counts = {"picks": len(result.picks), "spares": len(result.spares)}
    if result.counts.get("vetoed"):
        counts["vetoed"] = result.counts["vetoed"]
    try:
        log_line = libfolder.append_log(folder.root, f"crate {state.slug}", counts, file=xml_path, now=now, today=today)
    except (LibraryFolderError, OSError) as exc:
        told = ", ".join(f"{n} {key}" for key, n in counts.items())
        log_line = f"{libfolder.log_clock(today, now)} crate {state.slug} -> {told}; {xml_file}"
        warnings.append(f"log.md: the crate line was not added ({exc}). Add it by hand: {log_line}")
    return CrateWriteResult(
        xml_path=xml_path,
        md_path=md_path,
        import_steps=import_steps(device, xml_file, list(state.moves)),
        log_line=log_line,
        slug=state.slug,
        name=name,
        xml_file=xml_file,
        md_file=md_file,
        counts=counts,
        device=device,
        warnings=tuple(warnings),
    )
