"""Track matching between rekordbox and Spotify. Pure functions, no I/O.

Normalise: lowercase, strip accents, "&" -> "and", drop "feat./ft./featuring ...",
drop bracketed text, collapse punctuation and whitespace.
Version words are never silently dropped: they are kept as a separate `version` string,
so an original against an "Extended Mix" is AMBIGUOUS, never a confident match.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from rapidfuzz import fuzz

VERSION_WORDS = {
    "edit", "extended", "remix", "remaster", "remastered", "mix", "version", "mono",
    "dub", "instrumental", "rework", "live",
}  # fmt: skip
# "Original Mix" is how DJ stores label the original: it is not a different version.
ORIGINAL = {"original mix", "original version", "original"}

CONFIDENT_SCORE = 90
POSSIBLE_SCORE = 75
DURATION_OK_S = 3

MATCH, AMBIGUOUS, MISSING = "MATCH", "AMBIGUOUS", "MISSING"

_BRACKETS = re.compile(r"[\(\[]([^\)\]]*)[\)\]]")
_DASH = re.compile(r"\s+[-–—]+\s+")
_FEAT = re.compile(r"\b(feat|ft|featuring)\b\.?.*$")


def normalise(text: str | None) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    text = text.replace("&", " and ")
    text = _BRACKETS.sub(" ", text)
    text = _FEAT.sub(" ", text)
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def normalise_artist(text: str | None) -> str:
    """Artists compare as a bag of names: 'A & B' == 'A, B'."""
    return " ".join(t for t in normalise(text).split() if t not in {"and", "x", "vs"})


def _has_version_word(segment: str) -> bool:
    return bool(set(normalise(segment).split()) & VERSION_WORDS)


def parse_title(title: str | None, artist: str | None = None) -> tuple[str, str]:
    """-> (normalised base title, normalised version string).

    Handles '(Sunset Mix)', '[2019 Remaster]' and Spotify's 'Title - Sunset Mix'.
    A leading 'Artist - ' in the title (common in local files) is dropped.
    """
    title = title or ""
    segments = _BRACKETS.findall(title)
    parts = _DASH.split(_BRACKETS.sub(" ", title))
    artist_n = normalise_artist(artist)
    if len(parts) > 1 and artist_n:
        if fuzz.token_set_ratio(normalise_artist(parts[0]), artist_n) >= 85:
            parts = parts[1:]
    head = [parts[0]]
    for tail in parts[1:]:
        (segments if _has_version_word(tail) else head).append(tail)
    version = " ".join(normalise(s) for s in segments if _has_version_word(s))
    if version in ORIGINAL:
        version = ""
    return normalise(" ".join(head)), version


def primary_artist(artist: str | None) -> str:
    first = re.split(r",|&|\band\b|\bfeat\b|\bft\b|\bx\b|\bvs\b", artist or "", flags=re.I)[0]
    return normalise(first)


@dataclass
class Local:
    """A rekordbox track."""

    content_id: str
    artist: str
    title: str
    album: str = ""
    duration_s: int = 0
    isrc: str = ""
    bitrate: int = 0
    path: str = ""

    @property
    def label(self) -> str:
        return f"{self.artist.strip(' -')} - {self.title}"


@dataclass
class Candidate:
    """A Spotify track."""

    uri: str
    title: str
    artists: list[str]
    album: str = ""
    duration_ms: int = 0
    isrc: str = ""
    url: str = ""

    @property
    def label(self) -> str:
        return f"{', '.join(self.artists)} - {self.title}"


@dataclass
class Scored:
    candidate: Candidate
    score: int
    isrc_match: bool
    duration_diff_s: int
    version_ok: bool

    @property
    def confident(self) -> bool:
        good = self.isrc_match or self.score >= CONFIDENT_SCORE
        return good and self.duration_diff_s <= DURATION_OK_S and self.version_ok


@dataclass
class Result:
    local: Local
    status: str
    pick: Scored | None = None
    reasons: list[str] = field(default_factory=list)
    top: list[Scored] = field(default_factory=list)


def versions_compatible(a: str, b: str) -> bool:
    if not a or not b:
        return a == b
    return fuzz.token_set_ratio(a, b) >= 90


def score(local: Local, cand: Candidate, ignore_duration: bool = False) -> Scored:
    """ignore_duration: for tracks that come from a text list and carry no length."""
    l_title, l_version = parse_title(local.title, local.artist)
    c_artists = ", ".join(cand.artists)
    c_title, c_version = parse_title(cand.title, c_artists)
    title_score = fuzz.token_set_ratio(l_title, c_title)
    artist_score = fuzz.token_set_ratio(normalise_artist(local.artist), normalise_artist(c_artists))
    isrc_match = bool(local.isrc) and local.isrc.strip().upper() == cand.isrc.strip().upper()
    return Scored(
        candidate=cand,
        score=int(min(title_score, artist_score)),
        isrc_match=isrc_match,
        duration_diff_s=0 if ignore_duration else abs(local.duration_s - round(cand.duration_ms / 1000)),
        version_ok=versions_compatible(l_version, c_version),
    )


def decide(local: Local, candidates: list[Candidate], ignore_duration: bool = False) -> Result:
    """MATCH: one confident pick. AMBIGUOUS: something plausible, a human decides. MISSING."""
    seen: set[str] = set()
    scored = []
    for cand in candidates:
        if cand.uri not in seen:
            seen.add(cand.uri)
            scored.append(score(local, cand, ignore_duration))
    scored.sort(key=lambda s: (not s.isrc_match, -s.score, s.duration_diff_s))
    top = scored[:3]

    confident = [s for s in scored if s.confident]
    if confident:
        return Result(local, MATCH, pick=confident[0], top=top)

    plausible = [s for s in scored if s.isrc_match or s.score >= POSSIBLE_SCORE]
    if not plausible:
        return Result(local, MISSING, top=top)
    best = plausible[0]
    reasons = []
    if not best.isrc_match and best.score < CONFIDENT_SCORE:
        reasons.append(f"score {best.score}")
    if best.duration_diff_s > DURATION_OK_S:
        reasons.append(f"duration differs {best.duration_diff_s}s")
    if not best.version_ok:
        reasons.append("version differs")
    return Result(local, AMBIGUOUS, pick=best, reasons=reasons, top=top)
