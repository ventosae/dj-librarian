"""Taste files: Markdown the tool, Claude and the DJ append to across sessions (R-332).

Door 1 core: stdlib only (+ `dj.libfolder` for the atomic write), so skill scripts run it in
Cowork's sandbox.

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
`- [2026-11-01] lifted: Kestrel Unit - Ferrous <!-- key:veto:16 -->`).

`taste/feedback.md` holds what the DJ said about picks, one dated line each, the key optional:

    - [2026-10-22] too dark for a warm-up: Kestrel Unit - Ballast <!-- key:feedback:18 -->
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable, NamedTuple, Sequence

from dj.libfolder import write_text
from dj.model import LibraryError

NOW_LIMIT = 5
NOW_HEADING = "## Now"
LOG_HEADING = "## Log"
UPDATED = "updated: "
VETO_TEXT = "never propose:"
PAIR_TEXT = "never pair:"

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
    path = Path(path)
    if not path.is_file():
        return []
    lines, _ = _split(_read(path))
    out: list[LogEntry] = []
    for line in _outside_now(lines):
        m = _ENTRY.match(line.rstrip("\r"))
        if not m:
            continue
        try:
            day = date.fromisoformat(m.group(1))
        except ValueError:
            continue
        out.append(LogEntry(day, _SPACE.sub(" ", m.group(2)).strip(), m.group(3) or None))
    return out


def read_feedback(path: str | Path) -> list[LogEntry]:
    """`taste/feedback.md`: the DJ's dated remarks, (date, text, key or None), in file order."""
    return read_entries(path)


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
