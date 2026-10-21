"""Taste files: Markdown the tool, Claude and the DJ append to across sessions (R-332).

Door 1 core: stdlib only (+ `dj.libfolder` for the atomic write, `dj.analysis.common.dup_key`
for the copies of a vetoed track), so skill scripts run it in Cowork's sandbox.

Layout of a taste file (`taste/lanes.md`, `labels-artists.md`, `anchors.md`, `vocabulary.md`)::

    # <Title>

    > Measured by code: dj.analysis.taste from exports/2026-10-20-collection.xml, 2026-10-20.

    ## Now

    - <one current top item>

    ## Log

    - [2026-10-20] <text> <!-- key:<stable key> -->
    - [2026-11-02] updated: <new text> <!-- key:<stable key> -->
    - [2026-11-03] <a line the DJ wrote by hand; a key is optional>

- `## Now` holds at most 5 bullet lines. It is a summary, so it is rewritten on every run that
  passes `now_lines`; a call without `now_lines` (a Style Barber answer) leaves it as it is. Only
  the plain `- ` bullets and blank lines right under the heading are Now: the block ends at any
  heading (`###` too), at a dated or keyed line and at any other text, so a line the DJ wrote
  below it is never replaced, even when the `## Log` heading was renamed or deleted. A Now line
  never starts with a date (one that would is written as `\\[...`).
- `## Log` is the record. An entry line is `- [YYYY-MM-DD] <text> <!-- key:<stable key> -->`.
  The key names the thing the line is about (`lane:<slug>`, `label:<name>`, `artist:<name>`,
  `anchor:<track id>`, `word:<token>`, `veto:<track id>`, `pair:<id1>,<id2>`), so a later run
  can tell a new item from a changed one. The latest line for a key holds its current text. A
  later line for a key that starts with `updated: ` marks a change (the prefix is not part of the
  text); the first line for a key is taken as it is, so a text that itself starts with
  "updated: " stays stable. A key is one line without `--` (it sits in an HTML comment); comment
  markers in the text are defused (`-->` becomes `->`).
- Keys are compared in a canonical form (`canonical_key`): spaces collapsed; for `veto:` and
  `pair:` keys the spaces around the ids dropped and the two pair ids sorted, since a pair has no
  order. `key:pair:17,1`, `key:pair: 1 , 17` and `key:pair:1,17` are the same key. A line keeps
  its key as written.

`append_entries` never rewrites (R-332): every existing line stays byte for byte where it is,
including lines the DJ wrote by hand (with or without a key or a date) and any section the DJ
added. It appends a line for each new key, appends an `updated:` line when a key's latest text
changed, and never deletes or reorders. Only the `## Now` lines and the provenance line under
the title are replaced (both describe the latest run). `rebuild=True` writes the file from
scratch; callers pass it only on `--rebuild`, after the DJ said yes. `plan_entries` does the same
work without writing, so a caller with several files can check them all before it writes any.

`taste/vetoes.md` (written by Style Barber and the DJ, read by Crate me) holds lines

    - [2026-10-21] never propose: Kestrel Unit - Ferrous <!-- key:veto:16 -->
    - [2026-10-21] never pair: Grid Saint - Pressure Vessel + Okoro Lane - Sunday Sermon <!-- key:pair:17,1 -->

The key carries the track ids; the text is for people. The date and the leading `- ` are
optional. The latest line for a key (in canonical form) decides: to lift a veto, append a line
with the same key whose text does not start with `never propose:` / `never pair:` (for example
`- [2026-11-01] lifted: Kestrel Unit - Ferrous <!-- key:veto:16 -->`). A veto names the song:
`Vetoes.with_copies(tracks)` extends it to every copy (same artist and title) in the library,
and Crate me (`dj.crate.select`) and dj-build (`dj.build_structure`) apply vetoes that way.

`taste/feedback.md` holds what the DJ said about a gig, one dated line each, the key optional. Two
line shapes are scored (R-702, Q-19): the text after the date starts with a sign, `+` for a track
that worked, `-` for one that flopped, then `Artist - Title`, then `: note` (the note optional)::

    - [2026-10-22] + Kestrel Unit - Ballast: packed the floor at 1am <!-- key:gig:saturday-gig -->
    - [2026-10-22] - Grid Saint - Pressure Vessel: cleared the floor
    - [2026-10-22] what worked at Saturday Gig: the rooftop closers    (a remark: not scored)

The leading `- [date] ` is the dated bullet every taste file uses (`append_entries` writes it), so
the sign sits right after the date. A line typed by hand with the sign as its bullet,
`+ [2026-10-22] Kestrel Unit - Ballast: packed the floor`, counts as worked too. `- [date] Artist -
Title` stays a remark: `-` is the bullet of every dated line, so a flop needs the sign after the
date. `read_gig_feedback` reads the signed lines (a keyed line counts only while it is the latest
line for its key; a later one's `updated: ` prefix is dropped). `feedback_scores` matches each to
the library's songs as vetoes do (`dj.analysis.common.dup_key`: artist and title, so every copy of
the song; a remix named only in the Remixer field is another track, which a line names by adding
the remixer to the title: `Brass Tide (Dub Atelier Remix)`) and gives +1 (worked) or -1 (flopped)
per track, the latest line for a song deciding. A line that names no track in the library counts
for nothing. Crate me adds that to a track's score and never takes a flopped track as a spare
(`dj.crate.select`). The barber writes a gig answer as one unit (`dj.barber.entries_for`): a later
answer for the same gig replaces the earlier one whole.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterable, NamedTuple, Sequence

from dj.analysis.common import dup_key, norm_key
from dj.libfolder import write_text
from dj.model import LibraryError

NOW_LIMIT = 5
NOW_HEADING = "## Now"
LOG_HEADING = "## Log"
UPDATED = "updated: "
VETO_TEXT = "never propose:"
PAIR_TEXT = "never pair:"
WORKED, FLOPPED = 1, -1  # a signed feedback line: + worked, - flopped (Crate me: +1 / -1)
FEEDBACK_SIGNS = {"+": WORKED, "-": FLOPPED}
_SIGNED = re.compile(r"^([+-])\s+(\S.*)$")
# Words a title may add after a remixer's name to name that remix: "(Dub Atelier Remix)".
_VERSION_WORDS = frozenset(
    {"remix", "mix", "edit", "dub", "rework", "version", "extended", "club", "vip", "bootleg", "refix", "re",
     "radio", "instrumental", "reprise", "flip"}
)  # fmt: skip

# `- [YYYY-MM-DD] text <!-- key:k -->`; lenient on the bullet and on spaces, so lines the DJ
# typed by hand parse too. The key comment is optional.
_ENTRY = re.compile(
    r"^\s*[-*+]\s+\[(\d{4}-\d{2}-\d{2})\]\s*(.*?)(?:\s*<!--\s*key:\s*(.*?)\s*-->)?\s*$"
)
# Any line that ends in a key comment (vetoes may be written without the dated bullet).
_KEYED = re.compile(r"^\s*(?:[-*+]\s+)?(?:\[(\d{4}-\d{2}-\d{2})\]\s*)?(.*?)\s*<!--\s*key:\s*(.*?)\s*-->\s*$")
_DATED = re.compile(r"^[-*+]\s+\[\d{4}-\d{2}-\d{2}\]")  # on a stripped line
_DATE_FIRST = re.compile(r"^\[\d{4}-\d{2}-\d{2}\]")
_HEADING = re.compile(r"^#{1,2}\s+\S")  # a level-1 or level-2 heading ends a section
_SPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class Entry:
    """One thing to record: a stable key and the text that describes it now."""

    key: str
    text: str


class LogEntry(NamedTuple):
    """A dated line read back from a taste file. `key` is None for a line without one."""

    date: date
    text: str
    key: str | None


class AppendPlan(NamedTuple):
    """What `append_entries` would do to one file: its new text (None = nothing changes) and
    the log lines it would add."""

    path: Path
    text: str | None
    added: list[str]


@dataclass(frozen=True)
class Vetoes:
    """What Crate me must never do: propose a track, or put two tracks in one crate."""

    never_propose: frozenset[str] = frozenset()
    never_pair: frozenset[frozenset[str]] = frozenset()

    def blocks(self, track_id: str) -> bool:
        return str(track_id) in self.never_propose

    def blocks_pair(self, a: str, b: str) -> bool:
        return frozenset((str(a), str(b))) in self.never_pair

    def with_copies(self, tracks: Iterable[Any]) -> Vetoes:
        """These vetoes for every copy too (R-702). A copy is a track with the same non-empty
        `dj.analysis.common.dup_key` (artist and title; a remix named only in the Remixer field
        is another track), so the song the DJ vetoed by name stays out whichever file holds it:
        "never propose" holds for each copy of a vetoed track, and "never pair" between every
        copy of one side and every copy of the other. `tracks`: the library's tracks (anything
        with `id`, `artist`, `title` and `remixer`)."""
        groups: dict[str, list[str]] = {}
        key_of: dict[str, str] = {}
        for t in tracks:
            key = dup_key(t.artist, t.title, t.remixer)
            if key:
                groups.setdefault(key, []).append(str(t.id))
                key_of[str(t.id)] = key

        def copies(tid: str) -> set[str]:
            return {tid, *groups.get(key_of.get(tid, ""), ())}

        propose = {c for tid in self.never_propose for c in copies(tid)}
        pairs: set[frozenset[str]] = set()
        for pair in self.never_pair:
            if len(pair) != 2:  # read_vetoes never makes one; keep a hand-made one as it is
                pairs.add(pair)
                continue
            a, b = sorted(pair)
            pairs.update(frozenset((x, y)) for x in copies(a) for y in copies(b) if x != y)
        return Vetoes(frozenset(propose), frozenset(pairs))


def canonical_key(key: str) -> str:
    """The form keys are compared in (see the module docstring). Lines keep the key as written."""
    text = _SPACE.sub(" ", key).strip()
    kind, sep, rest = text.partition(":")
    kind = kind.strip().casefold()
    if sep and kind == "veto":
        return f"veto:{rest.strip()}"
    if sep and kind == "pair":
        ids = [part.strip() for part in rest.split(",")]
        if len(ids) == 2:
            ids.sort(key=_id_order)
        return "pair:" + ",".join(ids)
    return text


def _id_order(track_id: str) -> tuple[int, int, str]:
    """Numeric ids in numeric order ("2" before "10"), any other id after them, by text."""
    return (0, int(track_id), track_id) if track_id.isascii() and track_id.isdigit() else (1, 0, track_id)


# -- writing -------------------------------------------------------------------------------


def append_entries(
    path: str | Path,
    title: str,
    entries: Iterable[Entry],
    *,
    today: date | None = None,
    now_lines: Sequence[str] = (),
    provenance: str = "",
    rebuild: bool = False,
) -> list[str]:
    """Append what is new or changed to a taste file; return the log lines added.

    A missing file is created (`# title`, the provenance line, `## Now`, `## Log`). An existing
    file keeps every line; see the module docstring. `now_lines` (at most 5) replace the Now
    lines; empty leaves them as they are. `provenance` replaces the line under the title that
    starts the same way (`> Measured by code`, `> Words by Claude`); empty leaves it.
    `rebuild=True` writes the file from scratch with only these entries: callers pass it only on
    `--rebuild`. Nothing is written when nothing changed. Writes are atomic (temp file, then
    os.replace).
    """
    plan = plan_entries(
        path, title, entries, today=today, now_lines=now_lines, provenance=provenance, rebuild=rebuild
    )
    write_plan(plan)
    return plan.added


def plan_entries(
    path: str | Path,
    title: str,
    entries: Iterable[Entry],
    *,
    today: date | None = None,
    now_lines: Sequence[str] = (),
    provenance: str = "",
    rebuild: bool = False,
) -> AppendPlan:
    """What `append_entries` would write, without writing: reads and checks the file and the
    entries (ValueError, LibraryError) and returns the new text and the added lines."""
    path = Path(path)
    day = (today or date.today()).isoformat()
    items = _checked_entries(entries)
    now = [_now_text(line) for line in now_lines]
    if len(now) > NOW_LIMIT:
        raise ValueError(f"the Now section holds at most {NOW_LIMIT} lines, got {len(now)}")
    provenance = _one_line(provenance, "provenance") if provenance.strip() else ""

    if rebuild or not path.exists():
        added = [_entry_line(day, entry.text, entry.key) for entry in items]
        return AppendPlan(path, _new_file(_one_line(title, "title"), provenance, now, added), added)

    old = _read(path)
    lines, final_newline = _split(old)
    if now:
        lines = _replace_now(lines, now)
    if provenance:
        lines = _replace_provenance(lines, provenance)

    latest = _latest_texts(lines)
    added: list[str] = []
    for entry in items:
        key = canonical_key(entry.key)
        if key not in latest:
            added.append(_entry_line(day, entry.text, entry.key))
        elif latest[key] != entry.text:
            added.append(_entry_line(day, UPDATED + entry.text, entry.key))
        latest[key] = entry.text
    if added:
        lines = _append_to_log(lines, added)

    text = "\n".join(lines) + ("\n" if final_newline or added else "")
    return AppendPlan(path, text if text != old else None, added)


def write_plan(plan: AppendPlan) -> bool:
    """Write a planned file (atomic). False when the plan changes nothing."""
    if plan.text is None:
        return False
    write_text(plan.path, plan.text)
    return True


def _new_file(title: str, provenance: str, now: list[str], log: list[str]) -> str:
    parts = [f"# {title}", ""]
    if provenance:
        parts += [provenance, ""]
    if now:
        parts += [NOW_HEADING, ""] + [f"- {line}" for line in now] + [""]
    parts += [LOG_HEADING, ""] + log
    if not log:
        parts.pop()  # no blank line after an empty Log heading
    return "\n".join(parts) + "\n"


def _entry_line(day: str, text: str, key: str) -> str:
    return f"- [{day}] {text} <!-- key:{key} -->"


def _checked_entries(entries: Iterable[Entry]) -> list[Entry]:
    out: list[Entry] = []
    seen: set[str] = set()
    for entry in entries:
        key = _one_line(entry.key, "key")
        if "--" in key:  # it would end its HTML comment early ('-->') or break it in some renderers
            raise ValueError(f"a key cannot hold '--' (so no '-->' or '<!--'): {key!r}")
        if canonical_key(key) in seen:
            raise ValueError(f"key {key!r} given twice in one call")
        seen.add(canonical_key(key))
        out.append(Entry(key, _clean_text(entry.text, "entry text")))
    return out


def _one_line(text: str, what: str) -> str:
    if not isinstance(text, str):
        raise ValueError(f"{what} must be text, got {text!r}")
    line = _SPACE.sub(" ", text).strip()
    if not line:
        raise ValueError(f"{what} must not be empty")
    return line


def _clean_text(text: str, what: str) -> str:
    """One line; comment markers defused so the key comment stays the only one. Repeated,
    because one pass leaves a marker behind in `--->` or `<!---`."""
    line = _one_line(text, what)
    while "<!--" in line or "-->" in line:
        line = line.replace("<!--", "<!-").replace("-->", "->")
    return line


def _now_text(text: str) -> str:
    """A Now line: never dated-looking, so a later run cannot take it for a log line."""
    line = _clean_text(text, "Now line")
    return "\\" + line if _DATE_FIRST.match(line) else line


# -- reading and editing the lines ---------------------------------------------------------


def _read(path: Path) -> str:
    try:
        return path.read_bytes().decode("utf-8")
    except UnicodeDecodeError as exc:
        raise LibraryError(
            f"{path.name} is not UTF-8 text ({exc.reason}). Save it as UTF-8; nothing was written."
        ) from None


def _split(text: str) -> tuple[list[str], bool]:
    """Lines without their LF (a CR from a Windows editor stays, so lines keep their bytes)."""
    final_newline = text.endswith("\n")
    lines = text.split("\n")
    if final_newline:
        lines.pop()
    return lines, final_newline


def _bare(line: str) -> str:
    return line.rstrip("\r").strip()


def _heading_at(lines: list[str], heading: str) -> int | None:
    want = heading.casefold()
    return next((i for i, line in enumerate(lines) if _SPACE.sub(" ", _bare(line)).casefold() == want), None)


def _section(lines: list[str], heading: str) -> tuple[int, int] | None:
    """(index of the heading, index where its section ends) for the first such heading."""
    i = _heading_at(lines, heading)
    if i is None:
        return None
    end = next((j for j in range(i + 1, len(lines)) if _HEADING.match(_bare(lines[j]))), len(lines))
    return i, end


def _now_span(lines: list[str]) -> tuple[int, int] | None:
    """(index of the `## Now` heading, end of the Now lines under it): the blank lines and plain
    `- ` bullets right below the heading, up to the first other line (see the module docstring)."""
    i = _heading_at(lines, NOW_HEADING)
    if i is None:
        return None
    end = i + 1
    while end < len(lines) and _is_now_line(lines[end]):
        end += 1
    return i, end


def _is_now_line(line: str) -> bool:
    bare = _bare(line)
    if not bare:
        return True
    return bare.startswith("- ") and not _DATED.match(bare) and not _KEYED.match(bare)


def _replace_now(lines: list[str], now: list[str]) -> list[str]:
    body = [""] + [f"- {line}" for line in now] + [""]
    found = _now_span(lines)
    if found:
        start, end = found
        if end == len(lines):
            body.pop()  # the end of the file: no blank line after the last Now line
        return lines[: start + 1] + body + lines[end:]
    # No Now section yet: put one before the Log (or before the first section, or at the end).
    log = _section(lines, LOG_HEADING)
    at = log[0] if log else next((i for i, line in enumerate(lines) if _bare(line).startswith("## ")), None)
    if at is None:
        lead = [""] if lines and _bare(lines[-1]) else []
        return lines + lead + [NOW_HEADING] + body[:-1]
    return lines[:at] + [NOW_HEADING] + body + lines[at:]


def _replace_provenance(lines: list[str], provenance: str) -> list[str]:
    prefix = re.split(r"[:,]", provenance, maxsplit=1)[0]
    head_end = next((i for i, line in enumerate(lines) if _bare(line).startswith("## ")), len(lines))
    for i in range(head_end):
        if _bare(lines[i]).startswith(prefix):
            if _bare(lines[i]) == provenance:
                return lines
            return lines[:i] + [provenance] + lines[i + 1 :]
    title = next((i for i in range(head_end) if _bare(lines[i]).startswith("# ")), None)
    at = 0 if title is None else title + 1
    return lines[:at] + ["", provenance] + lines[at:]


def _outside_now(lines: list[str]) -> list[str]:
    found = _now_span(lines)
    if not found:
        return lines
    start, end = found
    return lines[:start] + lines[end:]


def _keyed_lines(lines: list[str]) -> Iterable[tuple[str, str]]:
    """(canonical key, text) of every line outside the Now lines that ends in a key comment,
    dated or not, in file order."""
    for line in _outside_now(lines):
        m = _KEYED.match(line.rstrip("\r"))
        if m and m.group(3):
            yield canonical_key(m.group(3)), _SPACE.sub(" ", m.group(2)).strip()


def _latest_texts(lines: list[str]) -> dict[str, str]:
    """canonical key -> its latest text. A later line loses its `updated: ` prefix; the first
    line for a key is taken as it is (its own text may start with "updated: ")."""
    latest: dict[str, str] = {}
    for key, text in _keyed_lines(lines):
        latest[key] = _strip_updated(text) if key in latest else text
    return latest


def _strip_updated(text: str) -> str:
    return text[len(UPDATED) :] if text.casefold().startswith(UPDATED) else text


def _append_to_log(lines: list[str], added: list[str]) -> list[str]:
    found = _section(lines, LOG_HEADING)
    if not found:
        lead = [""] if lines and _bare(lines[-1]) else []
        return lines + lead + [LOG_HEADING, ""] + added
    start, end = found
    last = max((i for i in range(start + 1, end) if _bare(lines[i])), default=None)
    if last is None:  # an empty Log: one blank line after the heading
        insert = [""] + added
        at = start + 1
        rest = lines[at:]
        if rest and not _bare(rest[0]):
            rest = rest[1:]  # reuse the blank line that was already there
        out = lines[:at] + insert + rest
        tail = start + 1 + len(insert)
    else:
        at = last + 1
        out = lines[:at] + added + lines[at:]
        tail = at + len(added)
    if tail < len(out) and _bare(out[tail]):
        out.insert(tail, "")  # keep a blank line before the next section
    return out


# -- parsers -------------------------------------------------------------------------------


def read_entries(path: str | Path) -> list[LogEntry]:
    """Every dated line outside the Now lines, in file order: (date, text, key or None).

    Undated lines and lines with an impossible date are skipped. A missing file -> [].
    """
    return [entry for _bullet, entry in _dated_entries(path)]


def _dated_entries(path: str | Path) -> list[tuple[str, LogEntry]]:
    """`read_entries`, each with the bullet its line starts with (`-`, `*` or `+`)."""
    path = Path(path)
    if not path.is_file():
        return []
    lines, _ = _split(_read(path))
    out: list[tuple[str, LogEntry]] = []
    for line in _outside_now(lines):
        m = _ENTRY.match(line.rstrip("\r"))
        if not m:
            continue
        try:
            day = date.fromisoformat(m.group(1))
        except ValueError:
            continue
        entry = LogEntry(day, _SPACE.sub(" ", m.group(2)).strip(), m.group(3) or None)
        out.append((line.lstrip()[:1], entry))
    return out


def read_keys(path: str | Path) -> set[str]:
    """The canonical keys of every keyed line outside the Now lines, dated or not: the lines
    `read_vetoes` reads (a hand-written `lifted: ... <!-- key:veto:16 -->` counts). A missing
    file -> set()."""
    path = Path(path)
    if not path.is_file():
        return set()
    lines, _ = _split(_read(path))
    return {key for key, _text in _keyed_lines(lines)}


def read_feedback(path: str | Path) -> list[LogEntry]:
    """`taste/feedback.md`: the DJ's dated remarks, (date, text, key or None), in file order."""
    return read_entries(path)


class GigFeedback(NamedTuple):
    """A signed line of `taste/feedback.md` (see the module docstring)."""

    date: date
    sign: int  # WORKED (+1) or FLOPPED (-1)
    text: str  # what follows the sign: "Artist - Title: note"
    key: str | None


def signed_feedback(text: str) -> tuple[int, str] | None:
    """`+ Artist - Title: note` -> (+1, "Artist - Title: note"), `- ...` -> (-1, ...); anything else
    (a remark, a sign without "Artist - Title") -> None."""
    m = _SIGNED.match(_SPACE.sub(" ", text).strip())
    if not m or " - " not in m.group(2):
        return None
    return FEEDBACK_SIGNS[m.group(1)], m.group(2).strip()


def read_gig_feedback(path: str | Path) -> list[GigFeedback]:
    """The signed lines of `taste/feedback.md`, in file order. A keyed line counts only while it is
    the latest line for its key (an `updated:` gig answer replaces the earlier one; its prefix is
    dropped); every dated line without a key counts. A line whose bullet is `+` and whose text is
    `Artist - Title: note` without a sign counts as worked (typed by hand: `+ [date] ...`). A
    missing file -> []."""
    entries = _dated_entries(path)
    first: dict[str, int] = {}
    last: dict[str, int] = {}
    for n, (_bullet, entry) in enumerate(entries):
        if entry.key:
            key = canonical_key(entry.key)
            first.setdefault(key, n)
            last[key] = n
    out: list[GigFeedback] = []
    for n, (bullet, entry) in enumerate(entries):
        text = entry.text
        if entry.key:
            key = canonical_key(entry.key)
            if last[key] != n:
                continue
            if first[key] != n:
                text = _strip_updated(text)
        signed = signed_feedback(text)
        if signed is None and bullet == "+":
            signed = signed_feedback(f"+ {text}")
        if signed is not None:
            out.append(GigFeedback(entry.date, signed[0], signed[1], entry.key))
    return out


class _Songs(NamedTuple):
    """The library's songs as a signed line names them: `groups` = `dup_key` -> track ids (the
    copies of one song); `remixes` = `norm_key` -> (remixer words, `dup_key`) of each remix named
    only in its Remixer field."""

    groups: dict[str, list[str]]
    remixes: dict[str, list[tuple[list[str], str]]]


def _songs(tracks: Iterable[Any]) -> _Songs:
    groups: dict[str, list[str]] = {}
    remixes: dict[str, list[tuple[list[str], str]]] = {}
    for t in tracks:
        key = dup_key(t.artist, t.title, getattr(t, "remixer", "") or "")
        if not key:
            continue
        if key not in groups:
            base = norm_key(t.artist, t.title)
            if key != base:  # `dup_key` added the remixer: `<base>|<remixer>`
                remixes.setdefault(base, []).append((key[len(base) + 1:].split(), key))
        groups.setdefault(key, []).append(str(t.id))
    return _Songs(groups, remixes)


def _remix_of(name: str, songs: _Songs) -> str | None:
    """The remix (named only in its Remixer field) a `norm_key` names: the title is the remix's
    title, then the remixer's words, then version words only (`brass tide dub atelier remix`)."""
    artist, _, title = name.partition("|")
    words = title.split()
    for k in range(len(words) - 1, 0, -1):  # the longest base title first
        tail = words[k:]
        for mix, key in songs.remixes.get(f"{artist}|{' '.join(words[:k])}", ()):
            if tail[: len(mix)] == mix and all(w in _VERSION_WORDS for w in tail[len(mix):]):
                return key
    return None


def _song_key(text: str, songs: _Songs) -> str | None:
    """The `dup_key` of the song a signed line names, when the library holds it. `text` is
    "Artist - Title: note"; an artist or a title may hold " - " or ": " itself, so every split is
    tried: the first " - " first, and for each the longest title before a ": " first. A song named
    as it is (same `norm_key`) wins over a remix named only in a Remixer field, which is tried
    after every split."""
    names: list[str] = []
    dashes = [i for i in range(len(text)) if text.startswith(" - ", i)]
    for i in dashes:
        artist, rest = text[:i], text[i + 3:]
        cuts = [len(rest)] + sorted((j for j in range(len(rest)) if rest.startswith(": ", j)), reverse=True)
        names += [key for j in cuts if (key := norm_key(artist, rest[:j]))]
    hit = next((name for name in names if name in songs.groups), None)
    return hit or next((key for name in names if (key := _remix_of(name, songs))), None)


def feedback_scores(feedback: Iterable[GigFeedback], tracks: Iterable[Any]) -> dict[str, int]:
    """Track id -> WORKED (+1) or FLOPPED (-1) from the signed feedback lines, for every copy of the
    song a line names: the same `dup_key` (artist and title, as `Vetoes.with_copies` counts copies),
    so a remix named only in the Remixer field is another track; a line names it by adding the
    remixer to the title ("Brass Tide (Dub Atelier Remix)"). The latest line for a song decides (by
    date, then file order). A line that names no track counts for nothing. `tracks`: anything
    with `id`, `artist`, `title` and (optional) `remixer`."""
    songs = _songs(tracks)
    verdict: dict[str, tuple[date, int, int]] = {}
    for order, line in enumerate(feedback):
        key = _song_key(line.text, songs)
        if key is None:
            continue
        if key not in verdict or (line.date, order) >= verdict[key][:2]:
            verdict[key] = (line.date, order, line.sign)
    return {tid: sign for key, (_day, _order, sign) in verdict.items() for tid in songs.groups[key]}


def read_vetoes(path: str | Path) -> Vetoes:
    """`taste/vetoes.md` -> Vetoes. Keys `veto:<id>` and `pair:<id1>,<id2>`; the latest line
    for a key (canonical form) decides (see the module docstring). A missing file -> no vetoes."""
    path = Path(path)
    if not path.is_file():
        return Vetoes()
    lines, _ = _split(_read(path))
    latest: dict[str, str] = {}
    for key, text in _keyed_lines(lines):
        latest[key] = _strip_updated(text).casefold()
    propose: set[str] = set()
    pairs: set[frozenset[str]] = set()
    for key, text in latest.items():
        kind, _, rest = key.partition(":")
        if kind == "veto" and text.startswith(VETO_TEXT) and rest:
            propose.add(rest)
        elif kind == "pair" and text.startswith(PAIR_TEXT):
            ids = rest.split(",")
            if len(ids) == 2 and all(ids) and ids[0] != ids[1]:
                pairs.add(frozenset(ids))
    return Vetoes(frozenset(propose), frozenset(pairs))
