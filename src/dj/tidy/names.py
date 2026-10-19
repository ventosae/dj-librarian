"""Filename <-> tag fields. Pure functions, no I/O.

`parse_filename` turns a stem such as `Artist - Title (Remixer Remix)` into fields with a
confidence level and a note of every heuristic that fired, so the plan can show its work.
`build_filename` does the reverse from tags, following tidy.yaml's naming rules.
Case is preserved everywhere: these values end up in tags, unlike `dj.match`'s normalised
forms, which are only used here for comparisons.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Collection, Sequence

from dj.match import ORIGINAL, VERSION_WORDS, normalise, normalise_artist
from dj.tidy.config import NamingRules

HIGH, MEDIUM, LOW = "high", "medium", "low"
_STEP_DOWN = {HIGH: MEDIUM, MEDIUM: LOW, LOW: LOW}

_SEP = re.compile(r"\s+[-–—]+(?:\s+[-–—]+)*\s+")  # " - ", " – ", " - - ", " –– "
_TRAILING_BRACKET = re.compile(r"\s*[\(\[]([^\)\]]*)[\)\]]\s*$")
_TRACK_NO = re.compile(r"^(?:\d{1,3}|[A-Da-d]\d{1,2})[\s._-]+(?=\S)")
_LEADING_NO = re.compile(r"^\d{1,3}\s+(?=\S)")
_CATALOG = re.compile(r"\s*\[[A-Z][A-Z0-9-]{2,}\]\s*$")
_NOISE = re.compile(
    r"\s*[\(\[]\s*(?:www\.[^\)\]]*|free download|\d{3}\s*kbps|320|hq|hd|"
    r"official(?:\s+(?:audio|video|music video))?|lyrics?)\s*[\)\]]\s*",
    re.I,
)
_FEAT = re.compile(r"\s*[\(\[]?\s*\b(?:feat\.?|ft\.?|featuring)\s+([^\)\]]+?)\s*[\)\]]?\s*$", re.I)
_FEAT_INNER = re.compile(r"^\s*(?:feat\.?|ft\.?|featuring)\s+(.+?)\s*$", re.I)
_REMIX_KINDS = r"remix|rework|re-?edit|edit|bootleg|rerub|remake|refix|flip|reprise"
_MIX_TAIL = re.compile(rf"^(?P<who>.+?)\s+(?P<kind>{_REMIX_KINDS})$", re.I)
_GENERIC_WHO = {
    "original", "extended", "club", "radio", "instrumental", "vocal", "dub", "album", "short",
    "long", "main", "full", "single", "the", "a", "re", "dj", "vip", "alt", "alternative",
}  # fmt: skip
_FORBIDDEN = '<>:"/\\|?*'
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_WS = re.compile(r"\s+")


@dataclass(frozen=True)
class Parsed:
    artist: str | None
    title: str | None
    mix: str | None = None
    remixer: str | None = None
    feat: str | None = None
    album: str | None = None
    confidence: str = LOW
    pattern: str = ""
    notes: tuple[str, ...] = ()

    @property
    def title_for_tag(self) -> str:
        """TIT2 base text: the title, with `(feat. X)` kept inside it."""
        if not self.title:
            return ""
        if self.feat and "feat" not in self.title.lower():
            return f"{self.title} (feat. {self.feat})"
        return self.title


def has_version_word(segment: str) -> bool:
    return bool(set(normalise(segment).split()) & VERSION_WORDS)


def is_original(mix: str | None) -> bool:
    return normalise(mix) in ORIGINAL if mix else False


def _clean(text: str) -> str:
    return _WS.sub(" ", text).strip()


def _strip_noise(text: str, notes: list[str]) -> str:
    before = text
    while True:
        text2 = _NOISE.sub(" ", text)
        text2 = _CATALOG.sub("", text2)
        if text2 == text:
            break
        text = text2
    if _clean(text) != _clean(before):
        notes.append("stripped download/catalogue noise")
    return _clean(text)


def _pull_brackets(title: str, notes: list[str]) -> tuple[str, str | None, str | None]:
    """Trailing (...) / [...] groups: a version word -> mix, feat. -> feat, else kept."""
    mix: str | None = None
    feat: str | None = None
    while True:
        m = _TRAILING_BRACKET.search(title)
        if not m or not m.group(1).strip():
            break
        inner = m.group(1).strip()
        fm = _FEAT_INNER.match(inner)
        if fm and feat is None:
            feat = fm.group(1).strip()
            title = title[: m.start()].rstrip()
            continue
        if has_version_word(inner) and mix is None:
            mix = inner
            title = title[: m.start()].rstrip()
            continue
        break
    if feat is None:
        fm = _FEAT.search(title)
        if fm and fm.start() > 0:
            feat = fm.group(1).strip()
            title = title[: fm.start()].rstrip()
            notes.append("moved 'feat.' out of the title")
    return _clean(title), mix, feat


def _artist_bag(text: str) -> set[str]:
    return set(normalise_artist(text).split())


def parse_filename(stem: str) -> Parsed:
    """Best-effort fields from a file stem. Never raises; low confidence instead."""
    notes: list[str] = []
    text = unicodedata.normalize("NFC", stem or "")
    lowered = False
    if "_" in text and " " not in text:
        text = text.replace("_", " ")
        notes.append("underscores read as spaces")
        lowered = True
    text = _clean(text)
    m = _TRACK_NO.match(text)
    if m and _SEP.search(text[m.end():]):
        notes.append(f"stripped leading '{m.group(0).strip()}'")
        text = text[m.end():]
        lowered = True
    text = _strip_noise(text, notes)
    text = text.rstrip(" -–—")
    if not text:
        return Parsed(None, None, confidence=LOW, pattern="empty", notes=tuple(notes))

    raw_parts = [p.strip() for p in _SEP.split(text)]
    parts = [p for p in raw_parts if p]
    if len(parts) != len(raw_parts):
        notes.append("dropped empty segment")

    if len(parts) == 1:
        title, mix, feat = _pull_brackets(parts[0], notes)
        return Parsed(None, title or None, mix, remixer_from_mix(mix), feat,
                      confidence=LOW, pattern="title-only", notes=tuple(notes))

    artist = parts[0]
    rest = parts[1:]
    # "Artist - Artist - Title" and "A, B, C - A & B - Title": a repeated artist credit.
    if len(rest) >= 2 and _artist_bag(rest[0]) and _artist_bag(rest[0]) <= _artist_bag(artist):
        notes.append("dropped repeated artist segment")
        rest = rest[1:]

    album: str | None = None
    confidence = HIGH
    pattern = "artist-dash-title"
    if len(rest) >= 2 and _LEADING_NO.match(rest[-1]):
        # Bandcamp: Artist - Album - NN Title
        album = " - ".join(rest[:-1])
        title_part = _LEADING_NO.sub("", rest[-1])
        notes.append("album form: Artist - Album - NN Title")
        confidence, pattern = MEDIUM, "artist-album-track"
    elif len(rest) >= 2 and has_version_word(rest[-1]) and not _TRAILING_BRACKET.search(rest[-1]):
        # Artist - Title - Mix
        title_part = " - ".join(rest[:-1]) + f" ({rest[-1]})"
        confidence, pattern = MEDIUM, "artist-title-dash-mix"
    elif len(rest) >= 2:
        title_part = " - ".join(rest)
        confidence, pattern = MEDIUM, "artist-title-extra"
        notes.append("extra ' - ' segments kept in the title")
    else:
        title_part = rest[0]

    title, mix, feat = _pull_brackets(title_part, notes)
    if mix and pattern == "artist-dash-title":
        pattern = "artist-dash-title-paren-mix"
    if not title or not artist:
        confidence = LOW
    if lowered:
        confidence = _STEP_DOWN[confidence]
    if has_version_word(artist):
        notes.append("artist segment contains a version word")
        confidence = LOW
    return Parsed(
        artist=artist or None,
        title=title or None,
        mix=mix,
        remixer=remixer_from_mix(mix),
        feat=feat,
        album=album,
        confidence=confidence,
        pattern=pattern,
        notes=tuple(notes),
    )


def split_title(title: str) -> tuple[str, str | None, str | None]:
    """'ode to rahsaan (Original Mix)' -> ('ode to rahsaan', 'Original Mix', None). Case kept."""
    return _pull_brackets(_clean(title or ""), [])


def remixer_from_mix(mix: str | None) -> str | None:
    """'Fantastic Man Remix' -> 'Fantastic Man'; 'Original Mix', 'Sunset Mix' -> None."""
    if not mix:
        return None
    m = _MIX_TAIL.match(mix.strip())
    if not m:
        return None
    who = m.group("who").strip()
    words = set(normalise(who).split())
    if not words or words <= _GENERIC_WHO:
        return None
    return who


def swap_suspected(parsed: Parsed, tag_artist: str, tag_title: str, known_artists: Collection[str]) -> bool:
    """Does the filename look like `Title - Artist`? Then nothing is proposed from it."""
    if not parsed.artist or not parsed.title:
        return False
    a, t = normalise_artist(parsed.artist), normalise(parsed.title)
    if tag_title and a == normalise(tag_title) and a != normalise(tag_artist or ""):
        return True
    if tag_artist and t == normalise_artist(tag_artist) and t != normalise(tag_title or ""):
        return True
    title_as_artist = normalise_artist(parsed.title)
    if known_artists and title_as_artist in known_artists and a not in known_artists:
        return True
    return has_version_word(parsed.artist)


# -- building ------------------------------------------------------------------------------


def join_artists(values: Sequence[str], rules: NamingRules) -> str:
    values = [v.strip() for v in values if v and v.strip()]
    if not values:
        return ""
    if len(values) == 1:
        return values[0]
    return rules.artist_join_many.join(values[:-1]) + rules.artist_join_two + values[-1]


def split_feat(artist: str) -> tuple[str, str | None]:
    """'Ben Sun feat. Jon Sable' -> ('Ben Sun', 'Jon Sable')."""
    m = _FEAT.search(artist or "")
    if m and m.start() > 0:
        return artist[: m.start()].strip(), m.group(1).strip()
    return (artist or "").strip(), None


def sanitize(name: str, nfc: bool = True) -> str:
    """A Windows-safe file name: no forbidden or control characters, no trailing dot/space."""
    text = unicodedata.normalize("NFC", name) if nfc else name
    text = _CONTROL.sub("", text)
    text = text.replace(":", " -").replace('"', "'")
    for ch in "/\\|":
        text = text.replace(ch, "-")
    for ch in "<>?*":
        text = text.replace(ch, "")
    text = _WS.sub(" ", text).strip()
    return text.rstrip(". ").strip()


def build_filename(artist: str, title: str, mix: str | None, ext: str, rules: NamingRules,
                   feat: str | None = None) -> str:
    """`{artist} - {title}{mix}.{ext}` per tidy.yaml. 'Original Mix' is dropped from the name."""
    artist_part, feat_in_artist = split_feat(artist)
    feat = feat or feat_in_artist
    title_part = title.strip()
    if feat and "feat" not in title_part.lower():
        title_part = f"{title_part} (feat. {feat})"
    omit = {normalise(m) for m in rules.omit_mixes}
    mix_part = f" ({mix.strip()})" if mix and normalise(mix) not in omit else ""
    stem = rules.template.format(artist=artist_part, title=title_part, mix=mix_part)
    stem = sanitize(stem, nfc=rules.nfc)
    ext = ext if ext.startswith(".") else f".{ext}"
    return f"{stem}{ext.lower()}"


def collision_free(name: str, taken: Collection[str]) -> str:
    """Append ' [2]', ' [3]', ... before the extension until the name is free (casefold)."""
    taken_cf = {t.casefold() for t in taken}
    if name.casefold() not in taken_cf:
        return name
    dot = name.rfind(".")
    stem, ext = (name[:dot], name[dot:]) if dot > 0 else (name, "")
    n = 2
    while f"{stem} [{n}]{ext}".casefold() in taken_cf:
        n += 1
    return f"{stem} [{n}]{ext}"


def same_name(a: str, b: str) -> bool:
    return unicodedata.normalize("NFC", a).casefold() == unicodedata.normalize("NFC", b).casefold()
