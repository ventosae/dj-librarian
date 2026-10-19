"""Hygiene and equipment rules. Pure: takes facts, returns findings. No I/O.

Each Finding has a stable `code` (what the README documents), a severity, where the fact came
from (`db` = rekordbox row, `file` = the audio file, `both`) and, for equipment rules, the
profile from tidy.yaml that produced it.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Collection, Sequence

from dj.library import TrackInfo
from dj.match import normalise, normalise_artist
from dj.tidy import names
from dj.tidy.config import Profile, TidyConfig, expected_bpm_from_name
from dj.tidy.tags import ArtInfo, StreamInfo, Tags

ERROR, WARN, INFO = "error", "warn", "info"
SEVERITY_ORDER = {ERROR: 0, WARN: 1, INFO: 2}
FILETYPE_NAMES = {1: "mp3", 4: "m4a", 5: "flac", 11: "wav", 12: "aiff"}
_CONTROL = set(chr(c) for c in range(0x20)) | {chr(0x7F)}


@dataclass(frozen=True)
class Finding:
    code: str
    severity: str
    source: str
    message: str
    profile: str | None = None
    data: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"code": self.code, "severity": self.severity, "source": self.source,
                               "message": self.message}
        if self.profile:
            out["profile"] = self.profile
        if self.data:
            out["data"] = self.data
        return out


@dataclass(frozen=True)
class FileFacts:
    path: Path
    exists: bool
    size: int = 0
    mtime: float = 0.0
    sha256: str | None = None
    container: str | None = None
    stream: StreamInfo | None = None
    tags: Tags | None = None
    art: ArtInfo | None = None
    read_error: str | None = None

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def readable(self) -> bool:
        return self.exists and self.read_error is None and self.tags is not None


@dataclass(frozen=True, eq=False)  # identity semantics: an Item is one file on disk
class Item:
    file: FileFacts
    rb: TrackInfo | None
    crate: str | None
    in_roots: bool
    parsed: names.Parsed | None = None
    local_art: Path | None = None

    @property
    def label(self) -> str:
        if self.rb and (self.rb.artist or self.rb.title):
            return self.rb.label_line
        return self.file.path.stem

    @property
    def tag_artist(self) -> str:
        return " / ".join(self.file.tags.artist) if self.file.tags else ""

    @property
    def tag_title(self) -> str:
        return self.file.tags.title if self.file.tags else ""

    @property
    def duration_s(self) -> float:
        if self.file.stream and self.file.stream.duration_s:
            return self.file.stream.duration_s
        return float(self.rb.duration_s) if self.rb else 0.0


def _f(code: str, severity: str, source: str, message: str, profile: str | None = None, **data: Any) -> Finding:
    return Finding(code, severity, source, message, profile, {k: v for k, v in data.items() if v is not None})


# -- profile-dependent -----------------------------------------------------------------------


def check_format(item: Item, profile: Profile) -> list[Finding]:
    out: list[Finding] = []
    f, rb, p = item.file, item.rb, profile.name
    container = f.container or (FILETYPE_NAMES.get(rb.file_type) if rb else None)
    if container and container not in profile.formats:
        out.append(_f("FMT_UNSUPPORTED", ERROR, "file" if f.container else "db",
                      f"{container} is not playable on {p} (allowed: {', '.join(profile.formats)})", p,
                      container=container))
    s = f.stream
    depth = (s.bit_depth if s and s.bit_depth else None) or (rb.bit_depth if rb and rb.bit_depth else None)
    if depth and depth > profile.max_bit_depth:
        out.append(_f("BITDEPTH_TOO_HIGH", ERROR, "file" if s and s.bit_depth else "db",
                      f"{depth}-bit exceeds {profile.max_bit_depth}-bit on {p}", p, bit_depth=depth))
    rate = (s.sample_rate if s and s.sample_rate else None) or (rb.sample_rate if rb and rb.sample_rate else None)
    if rate and rate not in profile.sample_rates:
        out.append(_f("SAMPLERATE_UNSUPPORTED", ERROR, "file" if s and s.sample_rate else "db",
                      f"{rate} Hz is not in {p}'s list {list(profile.sample_rates)}", p, sample_rate=rate))
    if container == "mp3":
        kbps = (s.bitrate_kbps if s and s.bitrate_kbps else None) or (rb.bitrate if rb and rb.bitrate else None)
        if profile.mp3_min_kbps and kbps and kbps < profile.mp3_min_kbps:
            out.append(_f("MP3_BITRATE_LOW", WARN, "file" if s and s.bitrate_kbps else "db",
                          f"{kbps} kbps is under the {profile.mp3_min_kbps} kbps floor of {p}", p, kbps=kbps))
        if s and s.vbr:
            sev = INFO if profile.mp3_allow_vbr else WARN
            out.append(_f("MP3_VBR", sev, "file", f"variable bitrate MP3 ({p}: {'ok' if profile.mp3_allow_vbr else 'avoid'})", p))
    return out


def check_art_rules(item: Item, profile: Profile) -> list[Finding]:
    art, p, rules = item.file.art, profile.name, profile.art
    if art is None:
        return []
    out = []
    if art.format not in rules.formats:
        out.append(_f("ART_NOT_JPEG", WARN, "file", f"embedded art is {art.format}, {p} wants {'/'.join(rules.formats)}", p,
                      format=art.format))
    if (art.width and art.width > rules.max_px) or (art.height and art.height > rules.max_px) or art.nbytes > rules.max_bytes:
        out.append(_f("ART_TOO_LARGE", WARN, "file",
                      f"art {art.width}x{art.height}, {art.nbytes // 1024} KB; {p} limit {rules.max_px}px / {rules.max_bytes // 1024} KB",
                      p, width=art.width, height=art.height, nbytes=art.nbytes))
    if art.width and art.height and (art.width < rules.min_px or art.height < rules.min_px):
        out.append(_f("ART_TOO_SMALL", INFO, "file", f"art only {art.width}x{art.height} (under {rules.min_px}px)", p,
                      width=art.width, height=art.height))
    return out


def check_path_length(item: Item, profile: Profile, planned_name: str | None = None) -> list[Finding]:
    out = []
    full = str(item.file.path)
    if len(full) > profile.max_path:
        out.append(_f("PATH_TOO_LONG", WARN, "file", f"path is {len(full)} chars, {profile.name} limit {profile.max_path}",
                      profile.name, length=len(full)))
    if planned_name:
        planned = str(item.file.path.with_name(planned_name))
        if len(planned) > profile.max_path:
            out.append(_f("PATH_TOO_LONG", WARN, "file", f"planned name would be {len(planned)} chars (limit {profile.max_path})",
                          profile.name, length=len(planned), planned=planned_name))
    return out


# -- profile-independent ---------------------------------------------------------------------


def check_consistency(item: Item) -> list[Finding]:
    out = []
    f, rb = item.file, item.rb
    if rb and f.container and FILETYPE_NAMES.get(rb.file_type) and FILETYPE_NAMES[rb.file_type] != f.container:
        out.append(_f("FMT_DB_MISMATCH", WARN, "both",
                      f"rekordbox says {FILETYPE_NAMES[rb.file_type]}, the file is {f.container}",
                      db=FILETYPE_NAMES[rb.file_type], file=f.container))
    return out


def check_art_presence(item: Item) -> list[Finding]:
    tags = item.file.tags
    if tags is None or tags.has_art:
        return []
    rb_note = ""
    if item.rb is not None:
        rb_note = "; rekordbox has artwork for it (ImagePath set)" if item.rb.image_path else "; rekordbox shows none either"
    out = [_f("ART_MISSING", WARN, "both" if item.rb else "file", f"no embedded picture{rb_note}")]
    if item.local_art is not None:
        out.append(_f("ART_LOCAL_AVAILABLE", INFO, "file", f"{item.local_art.name} sits next to the file (plan --art local uses it)",
                      local_art=str(item.local_art)))
    return out


def check_name(item: Item, forbidden: str, cfg: TidyConfig) -> list[Finding]:
    out = []
    name = item.file.name
    bad = sorted({c for c in name if c in forbidden or c in _CONTROL})
    problems = []
    if bad:
        problems.append(f"characters {bad}")
    if name != name.rstrip(". "):
        problems.append("trailing dot/space")
    if cfg.naming.nfc and unicodedata.normalize("NFC", name) != name:
        problems.append("not NFC-normalised")
    if problems:
        out.append(_f("PATH_BAD_CHARS", WARN, "file", "file name has " + ", ".join(problems)))
    tags = item.file.tags
    if tags and tags.artist and tags.title:
        base, mix_in_title, feat = names.split_title(tags.title)
        mix = tags.mix or mix_in_title
        expected = names.build_filename(names.join_artists(tags.artist, cfg.naming), base, mix,
                                        item.file.path.suffix, cfg.naming, feat=feat)
        if not names.same_name(expected, name):
            out.append(_f("NAME_OFF_CONVENTION", INFO, "file", f"convention would name it {expected!r}", expected=expected))
    return out


def check_tags(item: Item, cfg: TidyConfig) -> list[Finding]:
    tags, rb, s = item.file.tags, item.rb, item.file.stream
    if tags is None:
        return []
    out = []
    hint = f"; filename says {item.parsed.artist!r}" if item.parsed and item.parsed.artist else ""
    if not any(a.strip() for a in tags.artist):
        out.append(_f("TAG_ARTIST_MISSING", WARN, "file", f"artist tag empty{hint}"))
    if not tags.title.strip():
        t_hint = f"; filename says {item.parsed.title!r}" if item.parsed and item.parsed.title else ""
        out.append(_f("TAG_TITLE_MISSING", WARN, "file", f"title tag empty{t_hint}"))
    if not tags.genre.strip():
        out.append(_f("TAG_GENRE_MISSING", INFO, "file", "genre tag empty"))
    if rb and tags.title and rb.title and (
        normalise(tags.title) != normalise(rb.title)
        or (tags.artist and rb.artist and normalise_artist(" ".join(tags.artist)) != normalise_artist(rb.artist))
    ):
        out.append(_f("TAG_DB_FILE_MISMATCH", INFO, "both",
                      f"rekordbox shows {rb.label_line!r}, file tags say {item.tag_artist!r} - {tags.title!r} (Reload Tag?)"))
    if s and s.id3_version and s.id3_version[:2] != (2, cfg.id3_version):
        out.append(_f("TAG_ENCODING_ODD", INFO, "file",
                      f"ID3v{s.id3_version[0]}.{s.id3_version[1]} tag; tidy.yaml wants v2.{cfg.id3_version} "
                      "(an apply rewrites the whole tag in that version)", version=list(s.id3_version)))
    return out


def expected_bpm(item: Item, cfg: TidyConfig) -> tuple[float | None, str]:
    """(expected BPM, where it came from): the TBPM tag first, then the crate / folder name."""
    tags = item.file.tags
    if tags and tags.bpm:
        try:
            value = float(tags.bpm.replace(",", "."))
            if value > 0:
                return value, "tbpm"
        except ValueError:
            pass
    for source in (item.crate or "", item.file.path.parent.name):
        bpm, rule = expected_bpm_from_name(source, cfg)
        if bpm:
            return float(bpm), f"name:{rule}"
    return None, ""


def check_bpm(item: Item, cfg: TidyConfig) -> list[Finding]:
    rb = item.rb
    if rb is None:
        return []
    out = []
    if not rb.analysed or not rb.bpm_raw:
        out.append(_f("NOT_ANALYSED", INFO, "db", "rekordbox has not analysed this track (no BPM/grid yet)"))
        return out
    if 0 < rb.bpm_raw < 400:
        out.append(_f("BPM_SCALE_UNEXPECTED", INFO, "db",
                      f"DB BPM column holds {rb.bpm_raw}; tidy assumes x100 (12000 = 120 BPM). Check rules.BPM_SCALE.",
                      bpm_raw=rb.bpm_raw))
        return out
    expected, src = expected_bpm(item, cfg)
    if not expected:
        return out
    ratio = rb.bpm / expected
    if 0.47 <= ratio <= 0.53 or 1.9 <= ratio <= 2.1:
        out.append(_f("BPM_HALF_DOUBLE", WARN, "both",
                      f"rekordbox BPM {rb.bpm:g} vs expected {expected:g} ({src}): half/double. Fix the grid in rekordbox.",
                      db_bpm=rb.bpm, expected=expected, expected_from=src))
    elif src == "tbpm" and abs(rb.bpm - expected) > 1:
        out.append(_f("BPM_DB_TAG_DIFFER", INFO, "both", f"rekordbox BPM {rb.bpm:g}, TBPM tag {expected:g}",
                      db_bpm=rb.bpm, tag_bpm=expected))
    return out


def check_swap(item: Item, known_artists: Collection[str]) -> list[Finding]:
    if item.parsed is None:
        return []
    if names.swap_suspected(item.parsed, item.tag_artist, item.tag_title, known_artists):
        return [_f("SWAP_SUSPECTED", WARN, "both",
                   f"filename may be 'Title - Artist' ({item.parsed.artist!r} / {item.parsed.title!r}); nothing proposed")]
    return []


def check_item(item: Item, profiles: Sequence[Profile], cfg: TidyConfig,
               known_artists: Collection[str] = frozenset(), planned_name: str | None = None) -> list[Finding]:
    f = item.file
    out: list[Finding] = []
    if item.rb is None:
        out.append(_f("NOT_IN_REKORDBOX", INFO, "both", "no rekordbox row points at this file"))
    if not f.exists:
        if item.rb is not None:
            out.append(_f("FILE_MISSING", ERROR, "db", f"rekordbox points at {item.rb.path!r}, which does not exist"))
        return out
    if f.read_error:
        out.append(_f("FILE_UNREADABLE", ERROR, "file", f.read_error))
        return out
    forbidden = "".join(sorted({c for p in profiles for c in p.forbidden_chars})) or '<>:"/\\|?*'
    for profile in profiles:
        out += check_format(item, profile)
        out += check_art_rules(item, profile)
        out += check_path_length(item, profile, planned_name)
    out += check_consistency(item)
    out += check_art_presence(item)
    out += check_name(item, forbidden, cfg)
    out += check_tags(item, cfg)
    out += check_bpm(item, cfg)
    out += check_swap(item, known_artists)
    return sorted(out, key=lambda x: (SEVERITY_ORDER[x.severity], x.code, x.profile or ""))


def severity_counts(findings: Sequence[Finding]) -> dict[str, int]:
    counts = {ERROR: 0, WARN: 0, INFO: 0}
    for f in findings:
        counts[f.severity] += 1
    return counts


def code_counts(findings: Sequence[Finding]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for f in findings:
        counts[f.code] = counts.get(f.code, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))
