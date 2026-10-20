"""Style Barber: a short question session that sharpens the DJ's taste profile (R-701, R-703).

Door 1 core: stdlib + PyYAML only (contract section 0), so the skill script runs it in Cowork's
sandbox. It reads the latest export and writes text: dated lines in `taste/*.md` through
`dj.taste_files` (appended, never rewritten, R-332), its own state in `.cache/barber.json` and
one `log.md` line per answer that added a line (R-904). Nothing goes to rekordbox, master.db,
Spotify or audio files.

The session (`plan_session`). At most 8 questions (R-703: about a minute each, so a session
stays under 10 minutes), deterministic from the library, the taste facts and the date: no
randomness, no clock. The kinds come in a fixed cycle (name_lane, ab, pair, veto), each taking
its next candidate, and the last question is the gig question, so a full session on a
library with lanes, clusters, pairs and an odd track mixes all five kinds. A kind that runs out
of candidates gives its turn to the others. Each kind's candidates are rotated by an offset
taken from a hash of the date, so a new day starts in another place; questions whose key is
already in the taste files (`skip`, the gig question included) and tracks the DJ vetoed are
left out. A session can come out shorter than 8, or empty when everything was answered.

- ab: two of the DJ's own tracks. From a lane (taste facts `lanes`): its top track inside the
  lane's BPM range (rating, then plays, then track id) against the track of the lane's
  playlists furthest from the lane median: "which one belongs?". From a cluster (`clusters`):
  its two slowest BPM-tagged tracks: "which one opens the night?". Answer A or B.
- name_lane: a lane's BPM range and its 3 top tracks inside the range (fewer only when the
  lane has fewer); the DJ names it (free text, at most 60 characters).
- veto: a track that sits oddly in its playlists: its BPM lies 3 BPM or more outside the range
  of the lane its playlist belongs to (furthest first), else a 1-star track that still sits in
  a playlist. Keep proposing it, or never?
- pair: two tracks that sit together in 2 or more playlists (taste facts `cooccurrence`, the
  60 strongest). Good pair, or never pair?
- gig: what worked at the last gig (free text, at most 300 characters, optional). The last gig
  is the playlist with "gig" in its name and the latest date in it. The key names that playlist
  (`gig:<slug of its path>`), so a gig answered once is not asked about again; without a gig
  playlist the key is the session date.

Two tracks in one question are never duplicates of each other (same artist and title), and a
track is asked about (ab, veto, pair) in at most one question of a session. The anchors a
name_lane question shows are context, not the thing answered: they may show up in another
question too, so every lane gets its 3 anchors.

What an answer writes (`record`), one dated line through `taste_files.append_entries`:

    ab         taste/anchors.md   prefers <A> over <B> for <the lane / opening the night (cluster)>
                                  <!-- key:ab:<id1>,<id2> -->            (ids in id order)
    name_lane  taste/lanes.md     named lane <slug>: <name>  <!-- key:lane-name:<slug> -->
    veto       taste/vetoes.md    never propose: <label>     <!-- key:veto:<id> -->
                                  keep proposing: <label>    (same key: lifts an earlier veto)
    pair       taste/vetoes.md    never pair: <A> + <B>      <!-- key:pair:<id1>,<id2> -->
                                  good pair: <A> + <B>       (same key: lifts an earlier one)
    gig        taste/feedback.md  what worked at <playlist>: <text>  <!-- key:gig:<playlist slug> -->

The never lines are exactly what `taste_files.read_vetoes` reads, so Crate me honours them
(R-702). The same answer twice adds nothing; a changed answer appends an `updated:` line. An
answer is checked against the question first: the option itself ("A", "never"), its number
("1", "2") or its chip text, "skip" for any question, or free text for name_lane and gig. Anything
else raises BarberError and writes nothing. "skip" writes no taste line; it marks the question
done so the session moves on. A file the barber creates gets the title dj-taste uses for it and
the section-0 provenance line `> Measured by code: dj.barber from <export>, <date>.` (the
tracks in its lines come from that export), so a later dj-taste run replaces it with its own
line in anchors.md and lanes.md: one provenance line per file. An existing file keeps its head
as it is. Answered keys are read from every keyed line of the four files, dated or not
(`taste_files.read_keys`, the lines `read_vetoes` reads).

State: `<library>/.cache/barber.json` holds today's plan and the answers so far (machine state,
gitignored, library-relative paths only). `start` resumes it on the same day and plans a new
session on a new day. The DJ can stop at any point: every answer is saved as it comes.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time
from pathlib import Path
from typing import Any, Iterable, Sequence

from dj.analysis import taste as taste_analysis
from dj.analysis.common import library_folder
from dj.analysis.common import provenance_line as measured_line
from dj.libfolder import (
    LibraryFolder,
    LibraryFolderError,
    append_log,
    latest_export,
    write_text,
)
from dj.model import Library, LibraryError, PlaylistNode, Track, id_sort_key
from dj.readers.xml import read_xml
from dj.taste_files import (
    Entry,
    Vetoes,
    append_entries,
    canonical_key,
    read_keys,
    read_vetoes,
)

MODULE = "dj.barber"

MAX_QUESTIONS = 8  # R-703: about a minute each keeps a session under 10 minutes
MINUTES_PER_QUESTION = 1
KINDS = ("ab", "name_lane", "veto", "pair", "gig")
CYCLE = ("name_lane", "ab", "pair", "veto")  # the gig question always comes last
CHOICE_KINDS = ("ab", "veto", "pair")
ODD_BPM = 3  # BPM outside a lane's range that makes a track sit oddly in it
LOW_RATING = 1  # stars: a track rated this low that still sits in a playlist is a veto candidate
POOL = 20  # candidates per kind, before the daily rotation
PAIR_POOL = 60  # pairs drop out fast (a track is used once per session), so more of them
ANCHORS_SHOWN = 3
NAME_MAX = 60
FEEDBACK_MAX = 300
SKIP = "skip"
STATE_FILE = "barber.json"
STATE_SCHEMA = 1

FILES = {
    "ab": taste_analysis.FILES["anchors"],
    "name_lane": taste_analysis.FILES["lanes"],
    "veto": ("vetoes.md", "Vetoes"),
    "pair": ("vetoes.md", "Vetoes"),
    "gig": ("feedback.md", "Gig feedback"),
}
KNOWN_FILES = ("anchors.md", "lanes.md", "vetoes.md", "feedback.md")  # where answered keys live

_GIG = re.compile(r"\bgigs?\b", re.IGNORECASE)
_DATE_IN_NAME = re.compile(r"(?<!\d)((?:19|20)\d{2})(?:[-./ ](\d{1,2}))?(?:[-./ ](\d{1,2}))?(?!\d)")
_SPACE = re.compile(r"\s+")
_NOT_SLUG = re.compile(r"[^a-z0-9]+")


class BarberError(LibraryError):
    """A question or an answer the session cannot take. Nothing was written."""


# -- the session --------------------------------------------------------------------------


@dataclass(frozen=True)
class TrackRef:
    """A track as a question shows it."""

    id: str
    label: str
    bpm: float | int = 0
    key: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "label": self.label, "bpm": self.bpm, "key": self.key}


@dataclass(frozen=True)
class Question:
    """One question. `options` are the answers a chip question takes (empty: free text),
    `chips` what each chip shows, `key` the taste-file key an answer writes, `file` the file
    it goes to, `subject` what the recorded line names (a lane, a slug, a playlist)."""

    n: int
    total: int
    kind: str
    key: str
    prompt: str
    options: tuple[str, ...]
    chips: tuple[str, ...]
    tracks: tuple[TrackRef, ...]
    context: str
    subject: str
    file: str

    @property
    def track_ids(self) -> tuple[str, ...]:
        return tuple(t.id for t in self.tracks)

    @property
    def free_text(self) -> bool:
        return not self.options

    @property
    def progress(self) -> str:
        return progress_line(self.n, self.total)

    def to_dict(self) -> dict[str, Any]:
        return {
            "n": self.n,
            "total": self.total,
            "progress": self.progress,
            "kind": self.kind,
            "prompt": self.prompt,
            "options": list(self.options),
            "chips": list(self.chips),
            "free_text": self.free_text,
            "track_ids": list(self.track_ids),
            "tracks": [t.to_dict() for t in self.tracks],
            "context": self.context,
            "subject": self.subject,
            "file": self.file,
            "key": self.key,
        }


@dataclass
class Session:
    """Today's questions and the answers so far: {n: {"status": "answered"|"skipped",
    "answer": text, "added": [lines]}}."""

    day: date
    questions: tuple[Question, ...]
    source: str = ""
    answers: dict[int, dict[str, Any]] = field(default_factory=dict)

    def open_questions(self) -> list[Question]:
        return [q for q in self.questions if q.n not in self.answers]

    def next_question(self) -> Question | None:
        left = self.open_questions()
        return left[0] if left else None

    @property
    def done(self) -> bool:
        return not self.open_questions()

    def counts(self) -> dict[str, int]:
        statuses = [a.get("status") for a in self.answers.values()]
        answered, skipped = statuses.count("answered"), statuses.count("skipped")
        return {
            "questions": len(self.questions),
            "answered": answered,
            "skipped": skipped,
            "left": len(self.questions) - answered - skipped,
        }

    def files(self) -> list[str]:
        """The taste files this session added lines to, in question order."""
        out: list[str] = []
        for q in self.questions:
            if self.answers.get(q.n, {}).get("added") and q.file not in out:
                out.append(q.file)
        return out

    def to_json(self) -> dict[str, Any]:
        return {
            "schema": STATE_SCHEMA,
            "by": MODULE,
            "date": self.day.isoformat(),
            "source": self.source,
            "questions": [q.to_dict() for q in self.questions],
            "answers": {str(n): self.answers[n] for n in sorted(self.answers)},
        }

    @classmethod
    def from_json(cls, data: Any) -> Session:
        """The inverse of to_json. Anything malformed -> BarberError."""
        try:
            if data.get("schema") != STATE_SCHEMA:
                raise BarberError("barber.json has another schema")
            questions = tuple(_question_from(q) for q in data["questions"])
            answers = {int(n): dict(a) for n, a in data["answers"].items()}
            session = cls(date.fromisoformat(data["date"]), questions, str(data.get("source", "")), answers)
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            raise BarberError(f"barber.json does not read: {exc}") from None
        if [q.n for q in questions] != list(range(1, len(questions) + 1)) or not set(answers) <= {
            q.n for q in questions
        }:
            raise BarberError("barber.json does not read: questions out of order")
        return session


def _question_from(data: dict[str, Any]) -> Question:
    kind = str(data["kind"])
    if kind not in KINDS:
        raise ValueError(f"unknown kind {kind!r}")
    return Question(
        n=int(data["n"]),
        total=int(data["total"]),
        kind=kind,
        key=str(data["key"]),
        prompt=str(data["prompt"]),
        options=tuple(str(o) for o in data["options"]),
        chips=tuple(str(c) for c in data["chips"]),
        tracks=tuple(TrackRef(str(t["id"]), str(t["label"]), t.get("bpm", 0), str(t.get("key", ""))) for t in data["tracks"]),
        context=str(data["context"]),
        subject=str(data["subject"]),
        file=str(data["file"]),
    )


def progress_line(n: int, total: int) -> str:
    """`Question 3 of 8 · about 6 minutes left`: this question and the ones after it, a minute each."""
    minutes = (total - n + 1) * MINUTES_PER_QUESTION
    return f"Question {n} of {total} · about {minutes} minute{'' if minutes == 1 else 's'} left"


def question(session: Session, n: int) -> Question:
    """Question `n` (1-based) of the session; BarberError when there is no such question."""
    if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= len(session.questions):
        raise BarberError(f"There is no question {n!r}: this session has {len(session.questions)}.")
    return session.questions[n - 1]


# -- planning -----------------------------------------------------------------------------


def _norm(text: str) -> str:
    return _SPACE.sub(" ", str(text or "")).strip()


def _bpm(value: float) -> float | int:
    rounded = round(float(value), 1)
    return int(rounded) if rounded == int(rounded) else rounded


def _half_up(value: float) -> int:
    return int(value + 0.5)


def _label(t: Track) -> str:
    return _norm(t.label_line) or f"track {t.id}"


def _ref(t: Track) -> TrackRef:
    return TrackRef(t.id, _label(t), _bpm(t.bpm), _norm(t.key))


def _ident(t: Track) -> tuple[str, str]:
    return (_norm(t.artist).casefold(), _norm(t.title).casefold())


def _safe_id(track_id: str) -> bool:
    """An id that fits in a key: one word without ',' and '--' (keys sit in HTML comments)."""
    text = str(track_id)
    return bool(text) and text == text.strip() and not _SPACE.search(text) and "," not in text and "--" not in text


def _offset(day: date, salt: str, n: int) -> int:
    if n <= 0:
        return 0
    digest = hashlib.sha256(f"{day.isoformat()}|{salt}".encode()).digest()
    return int.from_bytes(digest[:8], "big") % n


def _rotate(items: list[Any], day: date, salt: str) -> list[Any]:
    k = _offset(day, salt, len(items))
    return items[k:] + items[:k]


def _rank(t: Track) -> tuple:
    return (-t.rating, -t.play_count, id_sort_key(t.id))


def _names(names: Sequence[str], limit: int = 3) -> str:
    shown = ", ".join(names[:limit])
    return shown + (f" and {len(names) - limit} more" if len(names) > limit else "")


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


@dataclass
class _Draft:
    kind: str
    key: str
    prompt: str
    options: tuple[str, ...]
    chips: tuple[str, ...]
    tracks: tuple[TrackRef, ...]
    context: str
    subject: str


class _Planner:
    """The library indexed once, plus what to leave out (answered keys, vetoed tracks)."""

    def __init__(self, lib: Library, facts: dict[str, Any], day: date, skip: Iterable[str], vetoes: Vetoes) -> None:
        self.lib = lib
        self.facts = facts
        self.day = day
        self.skip = {canonical_key(k) for k in skip}
        self.vetoes = vetoes
        self.by_path: dict[str, list[PlaylistNode]] = {}
        for node in lib.playlists():
            self.by_path.setdefault(node.path_str, []).append(node)
        self.used: set[str] = set()

    # -- shared helpers

    def shown(self, t: Track) -> bool:
        """A track a question may show as context: a safe id, not vetoed."""
        return _safe_id(t.id) and not self.vetoes.blocks(t.id)

    def ok(self, t: Track) -> bool:
        """A track a question may ask about: shown, and not asked about in another question yet."""
        return self.shown(t) and t.id not in self.used

    def members(self, paths: Iterable[str]) -> list[Track]:
        """Distinct known tracks of these playlists, in playlist order."""
        ids: dict[str, None] = {}
        for path in paths:
            for node in self.by_path.get(path, []):
                ids.update((i, None) for i in node.track_ids if i in self.lib.tracks)
        return [self.lib.tracks[i] for i in ids]

    def lane_tracks(self, lane: dict[str, Any]) -> list[Track]:
        return [t for t in self.members(lane.get("playlists", [])) if t.bpm > 0]

    @staticmethod
    def in_range(t: Track, lane: dict[str, Any]) -> bool:
        return lane["lo"] <= _half_up(t.bpm) <= lane["hi"]

    def free(self, key: str) -> bool:
        return canonical_key(key) not in self.skip

    def lanes(self) -> list[dict[str, Any]]:
        lanes = [lane for lane in self.facts.get("lanes", []) if str(lane.get("key", "")).startswith("lane:")]
        return sorted(lanes, key=lambda lane: (-lane["tracks"], lane["lo"], lane["key"]))[:POOL]

    # -- candidates per kind

    def candidates(self, kind: str) -> list[tuple[str, Any]]:
        if kind == "name_lane":
            return [("lane", lane) for lane in self.lanes()]
        if kind == "ab":
            clusters = [("cluster", c) for c in self.facts.get("clusters", [])][:POOL]
            lanes = [("lane", lane) for lane in self.lanes()]
            mixed: list[tuple[str, Any]] = []
            for i in range(max(len(clusters), len(lanes))):
                mixed += clusters[i : i + 1] + lanes[i : i + 1]
            return mixed[:POOL]
        if kind == "pair":
            co = self.facts.get("cooccurrence", {})
            raw = co.get("pairs") or [[p["a"], p["b"], p["count"]] for p in co.get("top", [])]
            return [("pair", (str(a), str(b), int(n))) for a, b, n in raw[:PAIR_POOL]]
        if kind == "veto":
            return [("veto", c) for c in self.odd_tracks()[:POOL]]
        raise ValueError(kind)

    def odd_tracks(self) -> list[tuple[str, str]]:
        """(track id, why) for tracks that sit oddly in their playlists, oddest first."""
        far: dict[str, tuple[float, str]] = {}
        for lane in self.facts.get("lanes", []):
            for path in lane.get("playlists", []):
                for t in self.lane_tracks({"playlists": [path]}):
                    gap = max(lane["lo"] - t.bpm, t.bpm - lane["hi"])
                    if gap >= ODD_BPM and gap > far.get(t.id, (0.0, ""))[0]:
                        why = f"{_bpm(t.bpm)} BPM in {path}, a {lane['label']} BPM lane"
                        far[t.id] = (gap, why)
        odd = sorted(far.items(), key=lambda kv: (-kv[1][0], id_sort_key(kv[0])))
        out = [(track_id, why) for track_id, (_gap, why) in odd]
        counts: dict[str, int] = {}
        for node in self.lib.playlists():
            for track_id in dict.fromkeys(node.track_ids):
                counts[track_id] = counts.get(track_id, 0) + 1
        low = sorted(
            (t for t in self.lib.tracks.values() if t.rating == LOW_RATING and counts.get(t.id) and t.id not in far),
            key=lambda t: id_sort_key(t.id),
        )
        out += [(t.id, f"rated {_plural(t.rating, 'star')}, in {_plural(counts[t.id], 'playlist')}") for t in low]
        return out

    # -- one question from one candidate (None: it cannot make one now)

    def build(self, kind: str, candidate: tuple[str, Any]) -> _Draft | None:
        what, item = candidate
        if kind == "name_lane":
            return self.name_lane(item)
        if kind == "ab":
            return self.ab_lane(item) if what == "lane" else self.ab_cluster(item)
        if kind == "pair":
            return self.pair(*item)
        if kind == "veto":
            return self.veto(*item)
        raise ValueError(kind)

    def name_lane(self, lane: dict[str, Any]) -> _Draft | None:
        slug = str(lane["key"]).split(":", 1)[1]
        key = f"lane-name:{slug}"
        if not slug or "--" in key or not self.free(key):
            return None
        tracks = self.lane_tracks(lane)  # anchors are context: other questions may show them too
        pool = sorted((t for t in tracks if self.in_range(t, lane) and self.shown(t)), key=_rank)
        pool = pool or sorted((t for t in tracks if self.shown(t)), key=_rank)
        anchors: list[Track] = []
        for t in pool:
            if _ident(t) not in {_ident(a) for a in anchors}:
                anchors.append(t)
            if len(anchors) == ANCHORS_SHOWN:
                break
        if not anchors:
            return None
        label = lane["label"]
        return _Draft(
            kind="name_lane",
            key=key,
            prompt=f"What do you call your {label} BPM lane?",
            options=(),
            chips=(),
            tracks=tuple(_ref(t) for t in anchors),
            context=f"{label} BPM: {_names(lane['playlists'])}; {_plural(lane['tracks'], 'track')}, median {lane['median']}",
            subject=slug,
        )

    def _ab(self, a: Track, b: Track, prompt: str, subject: str, context: str) -> _Draft | None:
        ids = sorted((a.id, b.id), key=id_sort_key)
        key = f"ab:{ids[0]},{ids[1]}"
        if not self.free(key):
            return None
        if _offset(self.day, key, 2):  # which track is A changes with the day, never with the library
            a, b = b, a
        return _Draft(
            kind="ab",
            key=key,
            prompt=prompt,
            options=("A", "B"),
            chips=(f"A: {_label(a)}", f"B: {_label(b)}"),
            tracks=(_ref(a), _ref(b)),
            context=context.format(a=_bpm(a.bpm), b=_bpm(b.bpm)),
            subject=subject,
        )

    def ab_lane(self, lane: dict[str, Any]) -> _Draft | None:
        tracks = [t for t in self.lane_tracks(lane) if self.ok(t)]
        cores = sorted((t for t in tracks if self.in_range(t, lane)), key=_rank)[:3]
        median = float(lane["median"])
        edges = sorted(tracks, key=lambda t: (-abs(t.bpm - median), id_sort_key(t.id)))[:3]
        label = lane["label"]
        for core in cores:
            for edge in edges:
                if edge.id == core.id or _ident(edge) == _ident(core):
                    continue
                draft = self._ab(
                    core, edge, f"Which one belongs in your {label} BPM lane?", f"the {label} BPM lane",
                    f"{label} BPM lane, median {lane['median']}: A {{a}} BPM, B {{b}} BPM",
                )  # fmt: skip
                if draft:
                    return draft
        return None

    def ab_cluster(self, cluster: dict[str, Any]) -> _Draft | None:
        tracks = [self.lib.tracks[i] for i in cluster.get("track_ids", []) if i in self.lib.tracks]
        slow: list[Track] = []
        for t in sorted((t for t in tracks if t.bpm > 0 and self.ok(t)), key=lambda t: (t.bpm, id_sort_key(t.id))):
            if _ident(t) not in {_ident(s) for s in slow}:
                slow.append(t)
        slow = slow[:3]
        name = cluster["name"]
        for i in range(len(slow)):
            for j in range(i + 1, len(slow)):
                draft = self._ab(
                    slow[i], slow[j], "Which one opens the night?", f"opening the night ({name})",
                    f"{name}: two of its slowest tracks, A {{a}} BPM, B {{b}} BPM",
                )  # fmt: skip
                if draft:
                    return draft
        return None

    def pair(self, a_id: str, b_id: str, count: int) -> _Draft | None:
        a, b = self.lib.tracks.get(a_id), self.lib.tracks.get(b_id)
        if a is None or b is None or not (self.ok(a) and self.ok(b)) or _ident(a) == _ident(b):
            return None
        if self.vetoes.blocks_pair(a.id, b.id):
            return None
        ids = sorted((a.id, b.id), key=id_sort_key)
        key = f"pair:{ids[0]},{ids[1]}"
        if not self.free(key):
            return None
        shared = [
            path for path, nodes in self.by_path.items()
            if any(a.id in n.track_ids and b.id in n.track_ids for n in nodes)
        ]  # fmt: skip
        return _Draft(
            kind="pair",
            key=key,
            prompt=f"{_label(a)} + {_label(b)}: good pair, or never pair?",
            options=("good", "never"),
            chips=("Good pair", "Never pair"),
            tracks=(_ref(a), _ref(b)),
            context=f"together in {_plural(count, 'playlist')}: {_names(shared)}",
            subject="",
        )

    def veto(self, track_id: str, why: str) -> _Draft | None:
        t = self.lib.tracks.get(track_id)
        if t is None or not self.ok(t):
            return None
        key = f"veto:{t.id}"
        if not self.free(key):
            return None
        return _Draft(
            kind="veto",
            key=key,
            prompt=f"{_label(t)}: keep proposing it, or never?",
            options=("keep", "never"),
            chips=("Keep proposing", "Never"),
            tracks=(_ref(t),),
            context=why,
            subject="",
        )

    def gig(self) -> _Draft | None:
        """The gig question; None when the last gig was answered before."""
        gigs = [
            (i, node) for i, node in enumerate(self.lib.playlists())
            if _GIG.search(node.name) or any(_GIG.search(p) for p in node.path[:-1])
        ]  # fmt: skip

        def when(item: tuple[int, PlaylistNode]) -> tuple:
            i, node = item
            m = _DATE_IN_NAME.search(node.name)
            stamp = tuple(int(g or 0) for g in m.groups()) if m else (0, 0, 0)
            return (stamp, bool(node.track_ids), i)

        last = max(gigs, key=when)[1] if gigs else None
        subject = _norm(last.name) if last else ""
        slug = _NOT_SLUG.sub("-", last.path_str.casefold()).strip("-") if last else ""
        key = f"gig:{slug or self.day.isoformat()}"
        if not self.free(key):
            return None
        where = f" ({subject})" if subject else ""
        return _Draft(
            kind="gig",
            key=key,
            prompt=f"What worked at your last gig{where}? One line, or skip.",
            options=(),
            chips=(),
            tracks=(),
            context=f"last gig playlist: {last.path_str}" if last else "no playlist with gig in its name",
            subject=subject,
        )


def plan_session(
    lib: Library,
    taste_facts: dict[str, Any],
    *,
    today: date | None = None,
    size: int = MAX_QUESTIONS,
    skip: Iterable[str] = (),
    vetoes: Vetoes | None = None,
    source: str = "",
) -> Session:
    """Today's questions (at most `size`, 1 to 8), deterministic from the library, the taste
    facts (`dj.analysis.taste.facts`) and the date (see the module docstring). `skip` holds
    keys already answered in the taste files; tracks `vetoes` never proposes are left out, so
    the session can be shorter, or empty when everything was answered. `source` is the export,
    relative to the library folder, kept in the state file."""
    if isinstance(size, bool) or not isinstance(size, int) or not 1 <= size <= MAX_QUESTIONS:
        raise ValueError(f"a session holds 1 to {MAX_QUESTIONS} questions, got {size!r}")
    day = today or date.today()
    planner = _Planner(lib, taste_facts, day, skip, vetoes or Vetoes())
    pools = {kind: _rotate(planner.candidates(kind), day, kind) for kind in CYCLE}
    cursor = dict.fromkeys(CYCLE, 0)
    gig = planner.gig()
    slots = size - 1 if gig and size > 1 else size  # the last slot is the gig question
    drafts: list[_Draft] = []
    while len(drafts) < slots:
        progressed = False
        for kind in CYCLE:
            if len(drafts) >= slots:
                break
            pool = pools[kind]
            while cursor[kind] < len(pool):
                draft = planner.build(kind, pool[cursor[kind]])
                cursor[kind] += 1
                if draft:
                    drafts.append(draft)
                    if kind != "name_lane":  # a lane's anchors are context, not asked about
                        planner.used.update(t.id for t in draft.tracks)
                    progressed = True
                    break
        if not progressed:
            break
    if gig and (size > 1 or not drafts):
        drafts.append(gig)
    total = len(drafts)
    questions = tuple(
        Question(
            n=n, total=total, kind=d.kind, key=d.key, prompt=d.prompt, options=d.options, chips=d.chips,
            tracks=d.tracks, context=d.context, subject=d.subject, file=f"taste/{FILES[d.kind][0]}",
        )
        for n, d in enumerate(drafts, 1)
    )  # fmt: skip
    return Session(day=day, questions=questions, source=source)


# -- answers ------------------------------------------------------------------------------


def parse_answer(q: Question, answer: Any) -> str:
    """The answer as it is recorded: "skip", one of `q.options`, or the DJ's free text.

    A chip question takes the option ("A", "never"), its number ("1", "2"), its chip text, and
    for ab the track's own "Artist - Title". Anything else -> BarberError (nothing recorded)."""
    text = _norm(answer) if isinstance(answer, str) else ""
    if not text:
        raise BarberError(f"Question {q.n} needs an answer: {_expected(q)}.")
    folded = text.casefold()
    if folded == SKIP:
        return SKIP
    if q.options:
        for number, (option, chip) in enumerate(zip(q.options, q.chips), 1):
            if folded in (option.casefold(), str(number), _norm(chip).casefold()):
                return option
        if q.kind == "ab":
            for option, t in zip(q.options, q.tracks):
                if folded == t.label.casefold():
                    return option
        raise BarberError(f"{text!r} is not an answer to question {q.n}: {_expected(q)}.")
    limit = NAME_MAX if q.kind == "name_lane" else FEEDBACK_MAX
    if len(text) > limit:
        raise BarberError(f"Question {q.n} takes at most {limit} characters, got {len(text)}.")
    return text


def _expected(q: Question) -> str:
    if q.options:
        return " or ".join(f"{o} ({n})" for n, o in enumerate(q.options, 1)) + ", or skip"
    return "one line of text, or skip"


def entry_for(q: Question, value: str) -> Entry:
    """The taste-file line an answer becomes (see the module docstring)."""
    if q.kind == "ab":
        a, b = q.tracks if value == q.options[0] else q.tracks[::-1]
        return Entry(q.key, f"prefers {a.label} over {b.label} for {q.subject}")
    if q.kind == "name_lane":
        return Entry(q.key, f"named lane {q.subject}: {value}")
    if q.kind == "veto":
        label = q.tracks[0].label
        return Entry(q.key, f"never propose: {label}" if value == "never" else f"keep proposing: {label}")
    if q.kind == "pair":
        a, b = q.tracks
        return Entry(q.key, f"{'never pair' if value == 'never' else 'good pair'}: {a.label} + {b.label}")
    if q.kind == "gig":
        return Entry(q.key, f"what worked at {q.subject or 'the last gig'}: {value}")
    raise BarberError(f"unknown question kind {q.kind!r}")


def provenance_line(source: str, day: date) -> str:
    """The section-0 line under the title of a file the barber creates; "" without a usable
    source (an absolute or empty path never goes into the library folder)."""
    try:
        return measured_line(MODULE, source, day)
    except ValueError:
        return ""


def _folder(folder: LibraryFolder | str | Path) -> LibraryFolder:
    return library_folder(folder)


def record(
    folder: LibraryFolder | str | Path,
    session: Session,
    n: int,
    answer: str,
    *,
    today: date | None = None,
) -> list[str]:
    """Record the answer to question `n`: one dated line appended to its taste file (never a
    rewrite), the answer saved in `.cache/barber.json`, and a `log.md` line when a taste line
    was added. Returns the added lines: [] for "skip" and for an answer recorded before.
    An unknown answer -> BarberError, and nothing is written."""
    return _record(_folder(folder), session, n, answer, today=today)[0]


def _record(
    folder: LibraryFolder, session: Session, n: int, answer: str, *, today: date | None
) -> tuple[list[str], str | None]:
    """`record`, returning (added lines, the log.md line or None)."""
    day = today or date.today()
    q = question(session, n)
    value = parse_answer(q, answer)
    added: list[str] = []
    if value != SKIP:
        name, title = FILES[q.kind]
        path = folder.taste / name
        folder.taste.mkdir(exist_ok=True)
        provenance = "" if path.exists() else provenance_line(session.source, day)
        added = append_entries(path, title, [entry_for(q, value)], today=day, provenance=provenance)
    previous = session.answers.get(q.n, {})
    session.answers[q.n] = {
        "status": "skipped" if value == SKIP else "answered",
        "answer": value,
        "added": list(previous.get("added", [])) + added,
    }
    save_session(folder, session)
    log = None
    if added:
        when = datetime.combine(today, time()) if today else None
        counts = {"line added" if len(added) == 1 else "lines added": len(added)}
        log = append_log(folder.root, "barber", counts, file=q.file, now=when)
    return added, log


# -- state and the folder -----------------------------------------------------------------


def state_path(folder: LibraryFolder) -> Path:
    return folder.cache / STATE_FILE


def load_session(folder: LibraryFolder | str | Path, *, today: date | None = None) -> Session | None:
    """Today's session from `.cache/barber.json`; None when there is none, it was planned on
    another day, or the file does not read (a new plan then replaces it)."""
    folder = folder if isinstance(folder, LibraryFolder) else LibraryFolder(Path(folder))
    path = state_path(folder)
    if not path.is_file():
        return None
    try:
        session = Session.from_json(json.loads(path.read_bytes().decode("utf-8")))
    except (BarberError, UnicodeDecodeError, ValueError):
        return None
    return session if session.day == (today or date.today()) else None


def save_session(folder: LibraryFolder, session: Session) -> bool:
    """Write `.cache/barber.json` (atomic). False when it already holds exactly this."""
    path = state_path(folder)
    text = json.dumps(session.to_json(), sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    if path.is_file() and path.read_bytes() == text.encode("utf-8"):
        return False
    folder.cache.mkdir(exist_ok=True)
    write_text(path, text)
    return True


def known_keys(folder: LibraryFolder) -> set[str]:
    """Canonical keys already in the taste files a question writes to (answered before): every
    keyed line, dated or not, as `read_vetoes` reads them."""
    keys: set[str] = set()
    for name in KNOWN_FILES:
        keys.update(read_keys(folder.taste / name))
    return keys


def _source_of(folder: LibraryFolder, path: Path) -> str:
    try:
        return folder.relative(path)
    except LibraryFolderError:
        return path.name


def start(folder: LibraryFolder | str | Path, *, today: date | None = None) -> tuple[Session, bool]:
    """(today's session, resumed?). Resumes `.cache/barber.json` when it is today's; else plans
    a new session from the latest export and saves it."""
    folder = _folder(folder)
    day = today or date.today()
    session = load_session(folder, today=day)
    if session is not None:
        return session, True
    export = latest_export(folder.root)
    lib = read_xml(export)
    facts = taste_analysis.facts(lib, today=day)
    session = plan_session(
        lib, facts, today=day, skip=known_keys(folder), vetoes=read_vetoes(folder.taste / "vetoes.md"),
        source=_source_of(folder, export),
    )  # fmt: skip
    save_session(folder, session)
    return session, False


def next_step(folder: LibraryFolder | str | Path, *, today: date | None = None) -> dict[str, Any]:
    """`barber next`: plan or resume today's session; counts first, then the next question
    (None when the session is done) and the taste files it added lines to so far."""
    session, resumed = start(folder, today=today)
    q = session.next_question()
    return {
        "counts": session.counts(),
        "date": session.day.isoformat(),
        "source": session.source,
        "resumed": resumed,
        "done": q is None,
        "question": q.to_dict() if q else None,
        "files": session.files(),
    }


def answer(folder: LibraryFolder | str | Path, n: int, text: str, *, today: date | None = None) -> dict[str, Any]:
    """`barber record`: record the answer to question `n` of today's session; counts first,
    then the added lines per file, the log line, and the next question or "done".
    No session planned today -> BarberError (run next first)."""
    folder = _folder(folder)
    day = today or date.today()
    session = load_session(folder, today=day)
    if session is None:
        raise BarberError("No Style Barber session today. Run `barber next` first; nothing was written.")
    q = question(session, n)
    added, log = _record(folder, session, n, text, today=today)
    following = session.next_question()
    status = session.answers[q.n]
    return {
        "counts": {**session.counts(), "lines_added": len(added)},
        "recorded": {"n": q.n, "kind": q.kind, "answer": status["answer"], "status": status["status"], "file": q.file},
        "added": {q.file: added} if added else {},
        "log": log,
        "done": following is None,
        "next": following.to_dict() if following else "done",
        "files": session.files(),
    }
