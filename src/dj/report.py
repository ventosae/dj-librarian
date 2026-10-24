"""dj-report, part 2: the one-file HTML report on the DJ's library (R-401 ... R-409, R-1405).

Door 1 core: stdlib + PyYAML only (contract section 0). Reads only files in the library folder
and writes one new file, `reports/<YYYY-MM-DD>-library.html` (create only: `-2`, `-3` ... when
the name is taken). Never touches rekordbox, Spotify or audio files.

    render(folder, today=None)      -> Path of the new report
    run_render(folder, today=None)  -> render + one log.md line ("report")
    run_report(folder, today=None)  -> proposals (dj.analysis.proposals) + render + one log line

The page follows docs/design.md (R-408): colour tokens on `:root`, Day (light) and Booth (dark)
both selected, Booth the default (`<html data-theme="dark">`); two buttons in the header switch
them and remember the choice in localStorage (inside try/catch); `#day` or `#booth` in the URL
wins (the screenshots use it). The charts are dj.report_charts: thin marks, 2 px gaps, a lane
keeps the slot colour profile/identity.json gives it everywhere (the four biggest lanes have one,
the rest are Other, and the page says so once where it happens: Q-30, D-27; at most 4 colours per
chart, D-26; an identity.json from before Q-30, slots 1..8 by BPM, still draws 4 colours at most,
and the page then says only that and how to colour the four biggest, since its grey lanes are the
fastest), at most 4 direct labels per chart, a tooltip on every mark
(hover and keyboard focus), a "table" link per chart to the file it was drawn from.

What the page is made of (numbers from code, words from Claude, R-302):
- id="who", the hero (R-402, R-1405), two columns on a wide screen: left the sleeve (dj.sleeve,
  inline, ids prefixed "hero-", its small print left out) with a tooltip on every fingerprint
  cell, and the six axes under it; right the DJ's handle, the archetype, the liner notes from
  `profile/identity.md` (Claude's; the archetype's one-line meaning stands in, with one line
  saying how to get the notes, when the file is missing) and exactly 5 stats, the `headline` of
  `profile/facts.json`, as a 3 + 2 grid. Narrower, the parts stack: the words, the sleeve and the
  axes, the stats. Then, full width, the narrative from `profile/habits.md` (Claude's; one line
  saying how to get it when missing). No `profile/identity.json`: the handle from `library.yaml` and one line saying how
  to get the sleeve. Claude's two files are shown without their "> Words by Claude, from ..."
  line: the colophon is the one place that credits them (W-30b); the "table" links stay.
- id="structure" (R-403): the first dj-structure reveal as the point, the crate wall (one row per
  top-level folder, a bar per playlist in the folder's lane colour, which the legend and the
  tooltips say, dumps hatched, empty playlists as outlines, the top overlaps as arcs; its table
  link is `structure/graph.json`, which holds every playlist's tracks) and "What it reveals":
  <= 5 lines (dumps, duplicates, orphans) from `structure/facts.json` and `profile/facts.json`.
- id="proposals" (R-404): the 2 or 3 entries of `structure/proposals.yaml` as cards, each with six
  parts marked `data-part`: name, principle, tree (a mini sleeve recoloured by where the
  proposal puts each BPM band, and the top-level branches with what is inside, <= 5), lands
  (<= 5 lines, then "and N more"), cost ("About N minutes"), trigger (a copy box). The colouring
  rule is in dj.report_charts.proposal_colours (reads `taste/facts.json` `bpm_playlists`): a
  colour names the same lane as everywhere on the page; the section says once what grey means.
- id="next" (R-406): a sticky footer with exactly one action under two minutes: say the first
  proposal's trigger (with a copy button). It sits after <main>, so its band runs the width of
  the window. On a phone it is one row: the trigger (up to two lines) and the button.
The colophon names only the files this render read.
A file that is missing leaves its part out with one line saying what is missing; a facts file
that does not read (broken JSON, or not in the shape the code that writes it writes:
`profile_ok`, `structure_ok`, `graph_ok`, `identity_ok`, `taste_ok`) is left out the same way,
with one line naming it. The report still renders (breadboard P4: finish with what there is).
Only a broken `structure/proposals.yaml` stops it (ProposalsError, nothing written): the trigger
blocks must be the ones the DJ or Claude wrote.

A second report on the same day is `<YYYY-MM-DD>-library-2.html`, then `-3` ...: the newest is
the one with the highest number (dj.onboarding.folder_state picks it that way), and the `report`
path in the JSON of every run names the file that run wrote.

Self-contained (R-401): inline CSS, inline SVG, one inline script (theme toggle, tooltips, copy
buttons; under 200 lines, no library), no external font, image, script or link. Every library
string is HTML-escaped, and "://" and "http" inside one are written with character references,
so the page holds no "http" at all; the only `url(` is the `url(#...)` of the dump hatch
pattern. The check before writing (`_check`) reads the page as HTML: the tags, the attribute
names, the CSS and the attributes that can load something, never the text or the data-* and
aria-* values a library name ends up in, so a name like "Curl(ed) Up", "Bass src=dub" or
"@import edits" never stops a report. Every list on the page has 5 items or fewer (R-407, R-1002 rule 9).
"""

from __future__ import annotations

import json
import math
import re
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from dj import design
from dj import report_charts as charts
from dj import sleeve as sleeve_mod
from dj.analysis import identity as identity_mod
from dj.analysis import proposals as proposals_mod
from dj.analysis.common import library_folder
from dj.analysis.profile import FIELD_NAMES
from dj.libfolder import (
    LibraryFolder,
    LibraryFolderError,
    append_log,
    load_meta,
    write_new_text,
)
from dj.model import LibraryError

MODULE = "dj.report"
PROFILE_FACTS = "profile/facts.json"
HABITS_MD = "profile/habits.md"
IDENTITY_JSON = identity_mod.IDENTITY_JSON
IDENTITY_MD = identity_mod.IDENTITY_MD
STRUCTURE_FACTS = "structure/facts.json"
GRAPH_JSON = "structure/graph.json"
TASTE_FACTS = "taste/facts.json"
LIST_MAX = 5
STATS = 5
KIDS_IN_LINE = 3  # names of a branch's children spelled out on a card, then "and N more"
SCRIPT_LINES_MAX = 200

# Links from reports/<file>.html to the file each chart was drawn from.
TABLE_LINKS = {
    "sleeve": "../profile/identity.json",
    "axes": "../profile/identity.json",
    "stats": "../profile/stats.md",
    "wall": "../structure/graph.json",
    "proposals": "../structure/proposals.yaml",
}

esc = charts.esc  # HTML-escaped, quotes too; "://" and "http" as character references
_plural = charts.plural


class ReportError(LibraryError):
    """The report could not be rendered. Nothing was written."""


# -- small helpers -----------------------------------------------------------------------------


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


# -- the shape of the facts files: a file the page cannot use is treated as missing -------------


def _maps(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, Mapping) for item in value)


def _whole(value: Any) -> bool:
    return value is None or (isinstance(value, int) and not isinstance(value, bool))


def _number(value: Any) -> bool:
    return value is None or (isinstance(value, (int, float)) and not isinstance(value, bool))


def _key(value: Any) -> bool:
    return value is None or isinstance(value, (str, int))


def profile_ok(data: Mapping[str, Any]) -> bool:
    """profile/facts.json holds the parts the page reads, in the shapes dj-profile writes."""
    headline, prov = data.get("headline", []), data.get("provenance", {})
    missing, dup = data.get("not_in_source", []), data.get("duplicates", {})
    return (
        _maps(headline)
        and isinstance(prov, Mapping)
        and isinstance(missing, list)
        and all(isinstance(f, str) for f in missing)
        and isinstance(dup, Mapping)
        and _whole(dup.get("groups"))
        and _whole(dup.get("tracks"))
    )


def structure_ok(data: Mapping[str, Any]) -> bool:
    """structure/facts.json holds the parts the page reads, in the shapes dj-structure writes."""
    reveals, dumps, overlap = data.get("reveals", []), data.get("dumps", {}), data.get("overlap", {})
    if not (isinstance(reveals, list) and isinstance(dumps, Mapping) and isinstance(overlap, Mapping)):
        return False
    tops, pairs = dumps.get("top", []), overlap.get("top", [])
    return (
        _maps(tops)
        and all(_key(d.get("path")) and _number(d.get("share")) for d in tops)
        and _maps(pairs)
        and all(_number(p.get("jaccard")) and _whole(p.get("shared")) for p in pairs)
    )


def graph_ok(data: Mapping[str, Any]) -> bool:
    """structure/graph.json holds nodes and edges in the shapes dj-structure writes."""
    nodes, edges = data.get("nodes", []), data.get("edges", [])
    if not (isinstance(nodes, list) and isinstance(edges, list)):
        return False
    return all(
        _key(n.get("id")) and _whole(n.get("depth")) and _whole(n.get("tracks")) for n in nodes if isinstance(n, Mapping)
    ) and all(_key(e.get("source")) and _key(e.get("target")) for e in edges if isinstance(e, Mapping))


def identity_ok(data: Mapping[str, Any]) -> bool:
    """profile/identity.json holds the parts the page reads, in the shapes dj-identity writes."""
    arch, axes = data.get("archetype"), data.get("axes")
    fp, lanes = data.get("fingerprint", {}), data.get("lanes", [])
    if not (isinstance(arch, Mapping) and isinstance(arch.get("name"), str) and isinstance(axes, Mapping)):
        return False
    if not all(isinstance(v, Mapping) and _whole(v.get("score")) for v in axes.values()):
        return False
    if not (isinstance(fp, Mapping) and _maps(fp.get("bands", [])) and _maps(fp.get("rings", []))):
        return False
    counts = fp.get("counts", [])
    if not (isinstance(counts, list) and all(isinstance(r, list) and all(_whole(c) for c in r) for r in counts)):
        return False
    if not all(_number(b.get("lo")) and _number(b.get("hi")) and _whole(b.get("tracks")) for b in fp.get("bands", [])):
        return False
    return _maps(lanes) and all(isinstance(lane.get("playlists", []), list) for lane in lanes)


def taste_ok(data: Mapping[str, Any]) -> bool:
    """taste/facts.json: the page reads only `bpm_playlists` (path, tracks, lo, hi)."""
    rows = data.get("bpm_playlists", [])
    return _maps(rows) and all(_number(r.get("lo")) and _number(r.get("hi")) and _number(r.get("tracks")) for r in rows)


_SHAPES = {PROFILE_FACTS: profile_ok, STRUCTURE_FACTS: structure_ok, GRAPH_JSON: graph_ok,
           IDENTITY_JSON: identity_ok, TASTE_FACTS: taste_ok}  # fmt: skip


def read_facts(folder: LibraryFolder, name: str) -> tuple[dict[str, Any] | None, bool]:
    """(the facts file, True when it exists but does not read or is not in the shape the page
    needs). A file that does not read is left out like a missing one, and named on the page."""
    path = folder.root / name
    if not path.is_file():
        return None, False
    data = _read_json(path)
    if data is None or not _SHAPES[name](data):
        return None, True
    return data, False


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _cut(text: str, chars: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= chars else text[: max(1, chars - 1)].rstrip() + "…"


def _list(items: Sequence[str], *, cls: str = "", more_where: str | None = None, ordered: bool = False) -> str:
    """At most LIST_MAX items as <li>; the rest counted in a line after the list."""
    tag = "ol" if ordered else "ul"
    attr = f' class="{cls}"' if cls else ""
    body = "".join(f"<li>{item}</li>" for item in items[:LIST_MAX])
    out = f"<{tag}{attr}>{body}</{tag}>"
    rest = len(items) - min(len(items), LIST_MAX)
    if rest:
        where = f" in {esc(more_where)}" if more_where else ""
        out += f'<p class="more">and {rest} more{where}</p>'
    return out


def _table(kind: str, label: str = "table") -> str:
    return f'<a class="table-link" href="{TABLE_LINKS[kind]}">{label}</a>'


# -- Markdown written by Claude (habits.md, identity.md) ---------------------------------------


def _inline(text: str) -> str:
    out = esc(text)
    out = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", out)  # a link keeps its text, never its target
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    out = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", out)
    return out


_LIST_LINE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.*)$")
_PROVENANCE = re.compile(r"^>\s*(?:Words by|Measured by)\b", re.IGNORECASE)


def markdown(text: str, more_where: str = HABITS_MD, *, provenance: bool = True) -> str:
    """The Markdown Claude wrote as HTML: paragraphs, ## headings, lists (<= 5 shown), "> " lines
    as a muted provenance line. The "# " title is left out (the page has its own headings).
    `provenance=False` also leaves out the file's own "> Words by ..." line: the hero and "How
    you work" credit Claude in the colophon only (W-30b)."""
    out: list[str] = []
    para: list[str] = []
    items: list[str] = []

    def flush() -> None:
        if para:
            out.append(f"<p>{_inline(' '.join(para))}</p>")
            para.clear()
        if items:
            out.append(_list([_inline(i) for i in items], more_where=more_where))
            items.clear()

    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw.strip()
        listed = _LIST_LINE.match(raw)
        if not line:
            flush()
        elif line.startswith("# "):
            flush()
        elif re.match(r"^#{2,6} ", line):
            flush()
            out.append(f"<h3>{_inline(line.lstrip('#').strip())}</h3>")
        elif line.startswith(">"):
            flush()
            if provenance or not _PROVENANCE.match(line):
                out.append(f'<p class="prov">{_inline(line.lstrip(">").strip())}</p>')
        elif listed:
            if para:
                flush()
            items.append(listed.group(1))
        else:
            if items:
                flush()
            para.append(line)
    flush()
    return "\n".join(out)


# -- section 1: the hero (R-402, R-1405) -------------------------------------------------------


def _handle_style(handle: str) -> str:
    """Display size for the handle: as large as fits its own column (56-96 px by docs/design.md,
    down to 40 px for a long name, which then wraps). The column is a size container, so the
    name is measured against the column it sits in, never the whole window."""
    em = max(sleeve_mod.text_em(handle), 1.0)
    size = max(40, min(96, int(560 / em)))
    return f"font-size:min({size}px, calc(100cqi / {em:.2f}))"


SAY_SLEEVE = "Say \u201cdraw my sleeve\u201d and I run it and rebuild this report (about 2 minutes)."


OTHER_LANES = "only your four biggest lanes get a colour"  # Q-30, D-27: said where an Other lane turns grey
# an identity.json from before Q-30 (slots 1..8 by BPM): its grey lanes are the fastest, not the smallest
OLD_SLOTS = "a chart colours four lanes at most; say “draw my sleeve” to colour your four biggest"
OLD_OWNER = "a chart colours four lanes at most"  # the same, in a mini sleeve's tooltip


def _has_other_lanes(identity: Mapping[str, Any] | None) -> bool:
    """True when identity.json has lanes without a colour (outside the four biggest): every chart
    draws them grey."""
    return bool(charts.other_lanes(identity))


def _why_grey(identity: Mapping[str, Any] | None) -> str:
    """Why lanes are grey, said once where it happens: the four biggest lanes get a colour (Q-30),
    or, for an identity.json written before Q-30, only that a chart colours four at most and how
    to colour the four biggest (its grey lanes are the fastest ones, which can be the biggest)."""
    return OLD_SLOTS if charts.stale_slots(identity) else OTHER_LANES


def _sleeve_figure(identity: Mapping[str, Any] | None) -> str:
    if identity:
        try:
            art = sleeve_mod.sleeve_svg(identity, inline=True, uid="hero-", small_print=False)
            hits = charts.sleeve_hits(identity)
        except (ValueError, TypeError, KeyError, IndexError, ZeroDivisionError):
            art = ""
        if art:
            grey = "grey for tracks outside your lanes"
            # only the grey lanes that own a band the disc draws grey; an Other lane that owns no
            # band (its neighbours overlap every band more) leaves no grey on the sleeve
            others = {str(lane.get("label")) for lane in charts.other_lanes(identity)}
            grey_lanes = len(others & {str(b.get("lane")) for b in charts.fingerprint_bands(identity)
                                       if design.chart_slot(b.get("slot")) is None})  # fmt: skip
            if grey_lanes:
                which = f"{grey_lanes} of your lanes" if charts.stale_slots(identity) else "your smaller lanes"
                grey += f" and in {which} ({_why_grey(identity)})"
            sparse = f"; {sleeve_mod.SPARSE_NOTE}" if sleeve_mod.sparse_rings(identity) else ""
            return (
                '<figure class="sleeve">'
                f'<div class="sleeve-wrap">{charts.defang(art.strip())}{hits}</div>'
                "<figcaption>Your sleeve, drawn from the collection: rings are decades, oldest inside; "
                f"segments are BPM bands in the colour of your lanes, {grey}; "
                f"the brighter the cell, the more tracks{sparse}. {_table('sleeve')}</figcaption>"
                "</figure>"
            )
    return '<figure class="sleeve"><div class="sleeve-empty"><p>No sleeve yet.</p></div></figure>'


def _axes_figure(identity: Mapping[str, Any] | None) -> str:
    if not identity:
        return ""
    svg = charts.axes_chart(identity, uid="ax-")
    if not svg:
        return ""
    axes = identity.get("axes") or {}
    top = [f"{axes[a].get('name', a.title())} {axes[a].get('score')}" for a in identity.get("top") or [] if a in axes]
    pick = f"The two strongest pick the archetype: {' and '.join(top)}." if len(top) == 2 else ""
    return (
        '<figure class="chart card axes-card">'
        f'<div class="chart-head"><h3>Six axes, 0 to 100</h3>{_table("axes")}</div>'
        f"{svg}<figcaption>{esc(pick)}</figcaption></figure>"
    )


def _stats(profile: Mapping[str, Any] | None, broken: bool) -> str:
    headline = list((profile or {}).get("headline") or [])[:STATS]
    if headline:
        tiles = "".join(
            '<li class="stat">'
            f'<span class="stat-label">{esc(h.get("label", ""))}</span>\n'
            f'<span class="stat-value">{esc(h.get("value", ""))}</span>\n'
            f'<span class="stat-note">{esc(h.get("note", ""))}</span>'
            "</li>\n"
            for h in headline
        )
        return (f'<div class="stats-row"><div class="stats-head"><h3>Your numbers</h3>{_table("stats")}</div>'
                f'<ul class="stats">{tiles}</ul></div>')  # fmt: skip
    if broken:
        return (f'<div class="stats-row"><p class="missing">No numbers: {PROFILE_FACTS} does not read as '
                "dj-profile writes it. Run dj-profile again.</p></div>")  # fmt: skip
    return ('<div class="stats-row"><p class="missing">No profile yet: dj-profile did not run, so the numbers '
            "are missing.</p></div>")  # fmt: skip


def _who(profile: Mapping[str, Any] | None, habits: str | None, identity: Mapping[str, Any] | None,
         liner: str | None, handle: str, broken: Sequence[str] = ()) -> str:  # fmt: skip
    archetype = (identity or {}).get("archetype") or {}
    # Claude's words without their "Words by Claude, from ..." line: the colophon credits them
    notes = markdown(liner, more_where=IDENTITY_MD, provenance=False) if liner and liner.strip() else ""
    text = ['<div class="hero-text">', f'<h2 class="handle" style="{_handle_style(handle)}">{esc(handle)}</h2>']
    if identity and archetype.get("name"):
        text.append(f'<p class="lead">{esc(archetype["name"])}</p>')
        if notes:  # the liner notes say what the archetype means for this DJ: no second line for it
            text.append(f'<div class="liner">{notes}</div>')
        else:
            if archetype.get("meaning"):
                text.append(f'<p class="meaning">{esc(archetype["meaning"])}</p>')
            text.append('<p class="liner placeholder">No liner notes yet. Say \u201cwrite my liner notes\u201d and '
                        f"I write {esc(IDENTITY_MD)} from your six axes (about 2 minutes).</p>")  # fmt: skip
    elif IDENTITY_JSON in broken:
        text.append(f'<p class="lead missing">No sleeve: {IDENTITY_JSON} does not read as dj-identity writes it. '
                    f"{SAY_SLEEVE}</p>")  # fmt: skip
    else:
        text.append(f'<p class="lead missing">No sleeve yet: dj-identity has not run. {SAY_SLEEVE}</p>')
        if notes:
            text.append(f'<div class="liner">{notes}</div>')
    text.append("</div>")
    narrative = markdown(habits, provenance=False) if habits and habits.strip() else ""
    if narrative:
        story = f'<div class="narrative card"><h3>How you work</h3>{narrative}</div>'
    else:
        story = ('<div class="narrative card"><h3>How you work</h3><p class="placeholder">No words on how you work '
                 "yet. Say \u201cwrite my habits\u201d and I write "
                 f"{esc(HABITS_MD)} from your numbers (about 2 minutes).</p></div>")  # fmt: skip
    # Wide: the art column (sleeve, then the six axes) left, the words (handle, archetype, liner
    # notes, then the five stats) right. Narrower, the two columns open up (display:contents)
    # and the parts stack: the words, the sleeve and the axes, the stats.
    return "\n".join([
        '<section id="who">',
        '<div class="hero">',
        '<div class="hero-main">',
        *text,
        _stats(profile, PROFILE_FACTS in broken),
        "</div>",
        '<div class="hero-art">',
        _sleeve_figure(identity),
        _axes_figure(identity),
        "</div>",
        "</div>",
        story,
        "</section>",
    ])  # fmt: skip


# -- section 2: how it's built (R-403) ---------------------------------------------------------


def _reveals(structure: Mapping[str, Any], profile: Mapping[str, Any] | None) -> list[str]:
    """dj-structure's reveals after the first (the section's point), then duplicates."""
    lines = [str(r) for r in (structure.get("reveals") or [])[1:]]
    dup = (profile or {}).get("duplicates") or {}
    groups = int(dup.get("groups") or 0)
    if groups:
        verb = "shares" if groups == 1 else "share"
        lines.insert(min(2, len(lines)), f"{_plural(groups, 'group')} of duplicate candidates: "
                                         f"{int(dup.get('tracks') or 0)} tracks {verb} an artist and title.")  # fmt: skip
    return lines[:LIST_MAX]


_LEGEND_MARKS = {"dump": "sw hatched", "empty": "sw outline", "arc": "sw arc-key"}


def _legend(entries: Sequence[tuple[str, str]]) -> str:
    if not entries:
        return ""
    keys = []
    for kind, label in entries:
        if kind == "head":  # what the colours mean, before the swatches
            keys.append(f'<span class="legend-head">{esc(label)}</span>')
            continue
        cls = _LEGEND_MARKS.get(kind, f"sw {kind}")
        keys.append(f'<span class="key"><span class="{cls}"></span>{esc(label)}</span>')
    return f'<div class="legend" aria-label="Legend">{"".join(keys)}</div>'


def _wall_figure(structure: Mapping[str, Any], graph: Mapping[str, Any] | None,
                 identity: Mapping[str, Any] | None) -> str:  # fmt: skip
    wall = charts.crate_wall(graph or {}, structure, identity, uid="cw-") if graph else None
    if not wall:
        return ""
    if charts.lane_rows(identity):
        colour = "Every bar in a row takes the colour of the folder\u2019s main BPM lane."
    else:
        colour = "One colour: no BPM lanes yet."
    return (
        '<figure class="chart card wall-card">'
        f'<div class="chart-head"><h3>Crate wall</h3>{_table("wall")}</div>'
        '<p class="chart-sub">One row per top-level folder, one bar per playlist; the longer the bar, the more '
        f"tracks. {colour} A track in two playlists counts in both bars, so a row can run longer than the "
        "folder\u2019s own track count.</p>"
        f"{wall.svg}{_legend(wall.legend)}</figure>"
    )


def _structure(structure: Mapping[str, Any] | None, graph: Mapping[str, Any] | None,
               profile: Mapping[str, Any] | None, identity: Mapping[str, Any] | None,
               broken: bool = False) -> str:  # fmt: skip
    parts = ['<section id="structure">', "<h2>How it's built</h2>"]
    if not structure and broken:
        parts += [f'<p class="lead">No structure data: {STRUCTURE_FACTS} does not read as dj-structure '
                  "writes it. Run dj-structure again.</p>", "</section>"]  # fmt: skip
        return "\n".join(parts)
    if not structure:
        parts += ['<p class="lead">No structure data yet: dj-structure did not run.</p>', "</section>"]
        return "\n".join(parts)
    reveals = list(structure.get("reveals") or [])
    parts.append(f'<p class="lead">{esc(reveals[0]) if reveals else "Your playlist tree, as rekordbox holds it."}</p>')
    found = _reveals(structure, profile)
    side = ""
    if found:
        side = f'<div class="reveals-box card"><h3>What it reveals</h3>{_list([esc(x) for x in found], cls="reveals")}</div>'
    parts += ['<div class="built">', _wall_figure(structure, graph, identity), side, "</div>", "</section>"]
    return "\n".join(parts)


# -- section 3: proposals (R-404) --------------------------------------------------------------


def _lands(rows: Sequence[Mapping[str, str]]) -> str:
    if not rows:
        return "<p>No playlist with tracks to move yet.</p>"
    items = []
    for row in rows:
        if row["to"] == proposals_mod.STAYS:
            items.append(f'{esc(row["from"])} <span class="muted">stays where it is</span>')
        else:
            items.append(f'{esc(row["from"])} <span class="arrow">→</span> <span class="to">{esc(row["to"])}</span>')
    return _list(items, cls="lands", more_where="structure/proposals.yaml")


def _kids(names: Sequence[str]) -> str:
    shown = ", ".join(names[:KIDS_IN_LINE])
    rest = len(names) - min(len(names), KIDS_IN_LINE)
    return shown + (f" and {rest} more" if rest else "")


def _mini(n: int, nodes: Sequence[Any], identity: Mapping[str, Any] | None,
          taste: Mapping[str, Any] | None) -> tuple[str, list[charts.Branch]]:  # fmt: skip
    """The mini sleeve of a card, recoloured by where the proposal puts each BPM band, and the
    proposal's branches (top-level nodes, each with the slot of the lane that fills it most)."""
    slots, branches = charts.proposal_colours(nodes, identity, taste)
    if not (identity and charts.fingerprint_bands(identity)):
        return "", branches
    try:
        art = sleeve_mod.mini_sleeve_svg(identity, slots, size=240, uid=f"p{n}-")
    except (ValueError, TypeError, KeyError, IndexError, ZeroDivisionError):
        return "", branches
    old = charts.stale_slots(identity)
    owners = {band: _owner(b, old) for b in branches for band in b.bands}
    return (f'<div class="mini"><div class="sleeve-wrap">{charts.defang(art.strip())}'
            f"{charts.mini_hits(identity, owners)}</div></div>"), branches  # fmt: skip


def _owner(b: charts.Branch, old: bool = False) -> str:
    """Where a band lands, for the mini sleeve's tooltip: the branch, and why it is grey when it is
    (`old`: identity.json is from before Q-30, so its grey lanes are not the smaller ones)."""
    if design.chart_slot(b.slot):
        return b.name
    if b.lane:
        why = OLD_OWNER if old else "not one of your four biggest"
        return f"{b.name} (lane {b.lane} BPM, Other: {why})"
    return f"{b.name} (no lane colour of its own)"


def _bpm_line(b: charts.Branch) -> str:
    """The BPM line under a branch: the lane its swatch keys first (the label the sleeve and the
    crate wall legend give that colour; "(Other)" for a lane identity.json leaves grey), then the
    tempo bands it takes on the mini sleeve. Each part is kept on one line (a range never breaks
    at its hyphen); the line wraps at the dot."""
    bands = charts.band_ranges(b.bands)
    parts = [f"bands {bands}"]
    if b.lane:
        lane = f"lane {b.lane} BPM" + ("" if design.chart_slot(b.slot) else " (Other)")
        parts = [lane, f"bands {bands.removesuffix(' BPM')}"]
    return " · ".join(f"<span>{esc(part)}</span>" for part in parts)


def _tree_part(branches: Sequence[charts.Branch], coloured: bool) -> str:
    """The tree part of a card: the top-level branches, each with its colour on the mini
    sleeve, what is inside it (two levels, names cut after KIDS_IN_LINE) and its BPM bands. A
    branch that holds no band of the mini sleeve gets a hollow swatch: a filled one always keys
    a colour on the sleeve."""
    items = []
    for b in branches:
        swatch = f"sw {charts.slot_class(b.slot)}" if coloured and b.bands else "sw outline"
        name = f"{b.name}/" if b.kind == "folder" else b.name
        if b.kind == "folder":
            inside = _kids(b.children) if b.children else "empty for now"
        else:
            inside = f"from {_plural(b.sources, 'playlist')}" if b.sources else "new, empty"
        bpm = f'<span class="bpm">{_bpm_line(b)}</span>' if b.bands and coloured else ""
        items.append(f'<span class="{swatch}"></span><span class="branch"><strong>{esc(name)}</strong> '
                     f'<span class="muted">{esc(inside)}</span>{bpm}</span>')  # fmt: skip
    branch_list = _list(items, cls="branches", more_where="structure/proposals.yaml")
    return (f'<div data-part="tree"><div class="part-head"><h4>The new tree</h4>{_table("proposals")}</div>'
            f"{branch_list}</div>")  # fmt: skip


def _proposal(n: int, total: int, p: Mapping[str, Any], identity: Mapping[str, Any] | None,
              taste: Mapping[str, Any] | None) -> str:  # fmt: skip
    cost = int(p["cost_minutes"])
    best = " · best fit" if n == 1 else ""
    mini, branches = _mini(n, list(p["tree"].nodes), identity, taste)
    return "\n".join([
        f'<article class="proposal card{" best" if n == 1 else ""}" data-slug="{esc(p["slug"])}" '
        f'data-family="{esc(p["family"])}">',
        f'<div class="card-head{" with-mini" if mini else ""}">{mini}<div class="card-title">',
        f'<p class="option">Option {n} of {total}{best}</p>',
        f'<h3 data-part="name">{esc(p["name"])}</h3>',
        "</div></div>",
        f'<p data-part="principle">{esc(p["principle"])}</p>',
        _tree_part(branches, bool(mini)),
        f'<div data-part="lands"><h4>Where your playlists land</h4>{_lands(p["lands"])}</div>',
        f'<p data-part="cost" class="cost">About {_plural(cost, "minute")} in rekordbox, from the import to the '
        "last playlist checked.</p>",
        f'<div data-part="trigger"><h4>To build it, say</h4><div class="copybox" id="trigger-{n}">'
        f'<pre class="trigger">{esc(p["trigger"])}</pre>'
        f'<button type="button" class="copy" data-copy="trigger-{n}">Copy</button></div></div>',
        "</article>",
    ])  # fmt: skip


def _proposals(entries: Sequence[Mapping[str, Any]], identity: Mapping[str, Any] | None,
               taste: Mapping[str, Any] | None) -> str:  # fmt: skip
    parts = ['<section id="proposals">', "<h2>Ways to rebuild it</h2>"]
    if not entries:
        parts += ['<p class="lead">No proposals yet: structure/proposals.yaml is missing.</p>', "</section>"]
        return "\n".join(parts)
    ways = _plural(len(entries), "way")
    parts.append(
        f'<p class="lead">{ways} to rebuild your tree, the best fit first. Each one is built as a copy: '
        "your playlists stay where they are in rekordbox.</p>"
    )
    if identity and charts.fingerprint_bands(identity):
        own = "a branch with no lane colour of its own"
        if _has_other_lanes(identity):
            own += f" ({_why_grey(identity)})"
        parts.append(
            '<p class="mini-note">On each mini sleeve, a tempo band takes the colour of the branch it lands in, '
            "and a branch wears the colour of the BPM lane that fills most of it. Grey: tracks no copied "
            f"playlist carries (they stay where they are), or {own}. Outline: "
            "a branch no tempo band lands in, so it has no colour on the sleeve.</p>"
        )
    parts.append(f'<div class="cards cards-{len(entries)}">')
    parts += [_proposal(i, len(entries), p, identity, taste) for i, p in enumerate(entries, 1)]
    parts += ["</div>", "</section>"]
    return "\n".join(parts)


# -- section 4: next (R-406) -------------------------------------------------------------------


def _next(entries: Sequence[Mapping[str, Any]]) -> str:
    if entries:
        action = (f'<span class="long">Pick one: say </span><q>{esc(entries[0]["trigger"])}</q>'
                  '<span class="long">, or the trigger of another option (under 2 minutes).</span>')  # fmt: skip
        extra = ['<button type="button" class="copy" data-copy="trigger-1">Copy</button>',
                 '<p class="after">I show you the new tree before anything gets written.</p>']  # fmt: skip
    else:
        action = "Say run the report again and I build the proposals (under 2 minutes)."
        extra = []
    return "\n".join(['<section id="next">', '<div class="next-in">', "<h2>Next</h2>",
                      f'<p class="action">{action}</p>', *extra, "</div>", "</section>"])  # fmt: skip


# -- the page ----------------------------------------------------------------------------------


def _tokens(mode: str) -> str:
    """The colour tokens of one theme as CSS declarations, from dj.design (= docs/design.md)."""
    pairs = [("surface", design.SURFACE[mode]), ("page", design.PAGE[mode]), ("text", design.TEXT[mode]),
             ("text-2", design.TEXT_2[mode]), ("muted", design.MUTED[mode]), ("grid", design.GRID[mode]),
             ("other", design.OTHER[mode])]  # fmt: skip
    pairs += [(f"c{i}", hexa) for i, hexa in enumerate(design.CATEGORICAL[mode], 1)]
    pairs += list(design.STATUS.items())
    scheme = "dark" if mode == "dark" else "light"
    return f"color-scheme:{scheme};" + ";".join(f"--{k}:{v}" for k, v in pairs)


def token_css() -> str:
    """`:root` light, dark twice (the OS preference unless the page says light; the toggle), and
    the print tokens (Day, whatever the toggle says). See docs/design.md, Tokens."""
    light, dark = _tokens("light"), _tokens("dark")
    return (
        f":root{{{light}}}\n"
        f'@media (prefers-color-scheme:dark){{:root:where(:not([data-theme="light"])){{{dark}}}}}\n'
        f':root[data-theme="dark"]{{{dark}}}\n'
        f'@media print{{:root,:root[data-theme]{{{light}}}}}'
    )


SLOT_CSS = "".join(f".s{i}{{--lane:var(--c{i})}}" for i in range(1, design.SLOTS + 1)) + ".s0{--lane:var(--other)}"

# The hero sleeve's decade labels (dj.sleeve, W-30b): at least DECADE_PX px tall wherever the hero
# draws the sleeve. DECADE_SIZE units reach that from a sleeve DECADE_FULL px wide up (the hero of a
# 1100 px page draws it 456 px wide); narrower (a two-column hero at mid width, a phone) the size in
# units must grow as DECADE_PX x 1000 / width. The rule below is the chord of that curve from
# DECADE_FULL down to DECADE_NARROW px (the hero on a 360 px phone: 360 - 2 x 16); the curve bends
# under its chord, so the labels stay at least DECADE_PX px across that range. In an inline SVG a
# CSS px is a user unit, and 1cqi is 1% of the .sleeve-wrap's width (its query container); a
# browser without container units keeps the attribute's DECADE_SIZE.
DECADE_PX = 11
DECADE_NARROW = 328
DECADE_FULL = math.ceil(DECADE_PX * sleeve_mod.VIEW / sleeve_mod.DECADE_SIZE)


def decade_css() -> str:
    """The CSS rule that keeps the hero sleeve's decade labels at least DECADE_PX px (see above)."""
    narrow = math.ceil(DECADE_PX * sleeve_mod.VIEW / DECADE_NARROW * 10) / 10
    slope = (narrow - sleeve_mod.DECADE_SIZE) / (DECADE_FULL - DECADE_NARROW)  # units per px of width
    base = math.ceil((sleeve_mod.DECADE_SIZE + slope * DECADE_FULL) * 100) / 100
    per_cqi = math.floor(slope * 100 * 100) / 100  # rounded so the line only rises
    return (f".sleeve .sleeve-wrap{{container-type:inline-size}}\n.sleeve .decades{{font-size:"
            f"max({sleeve_mod._num(sleeve_mod.DECADE_SIZE)}px,calc({base:.2f}px - {per_cqi:.2f}cqi))}}")  # fmt: skip


CSS = """
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%;background:var(--page)}
body{margin:0;background:var(--page);color:var(--text);overflow-wrap:break-word;
font:16px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif}
a{color:inherit}
.top,main{max-width:1100px;margin:0 auto;padding-left:32px;padding-right:32px}
.top{display:flex;align-items:center;justify-content:space-between;gap:16px;padding-top:18px;padding-bottom:18px}
.brand{margin:0;font-size:12px;font-weight:600;letter-spacing:.12em;text-transform:uppercase;color:var(--text-2)}
.toggle{display:inline-flex;gap:2px;padding:3px;border:1px solid var(--grid);border-radius:999px;background:var(--surface)}
.toggle button{font:inherit;font-size:13px;font-weight:600;letter-spacing:.01em;border:0;border-radius:999px;
padding:5px 14px;background:transparent;color:var(--text-2);cursor:pointer}
.toggle button[aria-pressed="true"]{background:var(--text);color:var(--surface)}
section{padding:44px 0 8px}
h2{font-size:22px;font-weight:700;letter-spacing:-.01em;line-height:1.25;margin:0 0 6px}
h3{font-size:16px;font-weight:700;margin:0 0 8px}
h4{font-size:12px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:var(--text-2);margin:18px 0 6px}
.lead{font-size:18px;margin:0 0 20px}
.prov,.muted,.more,.placeholder,.missing{color:var(--text-2)}
.prov{font-size:13px;margin:0 0 10px}
.more{font-size:13px;margin:4px 0 0}
ul,ol{margin:6px 0;padding-left:20px}
li{margin:3px 0}
.card{background:var(--surface);border:1px solid var(--grid);border-radius:14px}
.chart-head,.stats-head,.part-head{display:flex;align-items:baseline;justify-content:space-between;gap:12px}
.chart-head h3,.stats-head h3{margin:0;font-size:12px;font-weight:600;letter-spacing:.12em;text-transform:uppercase;
color:var(--text-2)}
.part-head h4{margin:0}
.table-link{font-size:12px;font-weight:600;color:var(--text-2);text-decoration:underline;text-underline-offset:3px;
text-decoration-color:var(--grid)}
.table-link:hover{color:var(--text)}
figure{margin:0}
figcaption,.chart-sub{font-size:13px;color:var(--text-2);margin:8px 0 0}
.chart-sub{margin:4px 0 12px}
/* hero */
#who{padding-top:12px}
.hero{display:grid;grid-template-columns:minmax(0,46fr) minmax(0,54fr);grid-template-areas:"art main";
column-gap:44px;row-gap:22px;align-items:start}
.hero-main{grid-area:main;min-width:0}
.hero-art{grid-area:art;min-width:0;display:flex;flex-direction:column;gap:22px}
.hero-text{grid-area:text;min-width:0;padding-top:6px;container-type:inline-size}
.sleeve{grid-area:sleeve;min-width:0}
.axes-card{grid-area:axes;min-width:0;padding:16px 18px 14px}
.axes-card svg.axes{max-width:340px}
.sleeve-wrap{position:relative;line-height:0}
.sleeve-wrap>svg:first-child{display:block;width:100%;height:auto}
.sleeve .sleeve-wrap{border-radius:6px;overflow:hidden;outline:1px solid var(--grid)}
.sleeve-wrap .hits{position:absolute;inset:0;width:100%;height:100%}
.sleeve-empty{aspect-ratio:1;display:flex;align-items:center;justify-content:center;padding:32px;text-align:center;
background:var(--surface);border:1px solid var(--grid);border-radius:6px;color:var(--text-2)}
.handle{font-weight:900;letter-spacing:-.04em;line-height:.92;margin:0 0 18px;overflow-wrap:anywhere}
.hero .lead{font-size:26px;font-weight:700;letter-spacing:-.015em;line-height:1.2;margin:0 0 4px}
.hero .lead.missing{font-size:18px;font-weight:400;letter-spacing:0;line-height:1.45;color:var(--text-2);margin:0 0 20px}
.meaning{font-size:17px;color:var(--text-2);margin:0 0 22px;max-width:36em}
.liner{border-left:2px solid var(--grid);padding-left:16px;margin:0 0 26px;max-width:38em}
.liner p{margin:0 0 10px}
p.liner{margin:0 0 26px}
.stats-row{grid-area:stats;margin-top:8px}
.stats-head{border-top:1px solid var(--grid);padding-top:12px}
.stats{list-style:none;padding:0;margin:10px 0 0;display:grid;grid-template-columns:repeat(5,minmax(min-content,1fr));
grid-template-rows:auto auto auto;column-gap:2px}
.stat{margin:0;padding:0 14px 0 0;display:grid;grid-row:span 3;grid-template-rows:subgrid;align-content:start}
.stat+.stat{border-left:1px solid var(--grid);padding-left:14px}
.stat-label{display:block;font-size:12px;font-weight:600;letter-spacing:.04em;color:var(--text-2)}
.stat-value{display:block;font-size:28px;font-weight:700;letter-spacing:-.02em;line-height:1.1;margin:4px 0 6px;
white-space:nowrap}
.stat-note{display:block;font-size:12px;line-height:1.35;color:var(--text-2)}
@media (min-width:960px){
.hero .stats{grid-template-columns:repeat(3,minmax(0,1fr));grid-template-rows:repeat(6,auto);row-gap:0}
.hero .stat:nth-child(-n+3){padding-bottom:16px}
.hero .stat:nth-child(3n+1){border-left:0;padding-left:0}
.hero .stat-value{font-size:22px;white-space:normal}
}
.narrative{margin-top:28px;padding:20px 24px;max-width:none;columns:2 22em;column-gap:40px}
.narrative h3{column-span:all;margin:0 0 10px;font-size:12px;font-weight:600;letter-spacing:.12em;
text-transform:uppercase;color:var(--text-2)}
.narrative p{margin:0 0 10px;break-inside:avoid}
/* charts */
svg.chart{display:block;width:100%;height:auto;overflow:visible}
svg.chart text{font-family:inherit}
.gridline{stroke:var(--grid);stroke-width:1;fill:none}
.t-tick{fill:var(--muted);font-size:11px}
.t-name{fill:var(--text);font-size:13px;font-weight:700}
.t-sub{fill:var(--text-2);font-size:11px}
.t-label{fill:var(--text-2);font-size:11px;font-weight:500}
.t-arc{fill:var(--text);font-weight:600}
.t-axis{fill:var(--text-2);font-size:13px}
.t-axis.strong{fill:var(--text);font-weight:700}
.t-value{fill:var(--text);font-size:12px;font-weight:700}
.t-icon{fill:var(--text);font-size:9px;font-weight:800}
.status .ring{fill:none;stroke:var(--warning);stroke-width:1.6}
.lane{fill:var(--lane)}
.outline{fill:none;stroke:var(--lane);stroke-width:1.5}
.hatch-line{fill:var(--surface)}
.emph{fill:var(--text)}
.rest{fill:var(--other)}
.arc{fill:none;stroke:var(--text);stroke-width:2;stroke-linecap:round;opacity:.85}
.arc-end{fill:var(--text);stroke:var(--surface);stroke-width:2}
.hit-area{fill:transparent}
.hit-line{fill:none;stroke:transparent;stroke-width:16}
.hits .cell{fill:transparent}
.hit{outline:none;cursor:default}
.hit:hover .mark,.hit:focus-visible .mark{filter:brightness(1.2)}
.hit:focus-visible .hit-area,.hits .cell:focus-visible{stroke:var(--text);stroke-width:1.5}
.hits .cell:hover{fill:var(--text);fill-opacity:.12}
svg.wall-narrow{display:none}
svg.wall-wide{max-width:640px}svg.wall-narrow{max-width:420px}
.names text,.labels text,.axes .t-value{paint-order:stroke;stroke:var(--surface);stroke-width:3px;stroke-linejoin:round}
.legend{display:flex;flex-wrap:wrap;gap:6px 16px;margin-top:12px;font-size:12px;color:var(--text-2)}
.legend-head{flex-basis:100%;font-weight:600}
.key{display:inline-flex;align-items:center;gap:6px}
.sw{display:inline-block;flex:none;width:10px;height:10px;border-radius:2px;background:var(--lane)}
.sw.hatched{background:repeating-linear-gradient(45deg,var(--text-2) 0 3px,transparent 3px 6px)}
.sw.outline{background:none;border:1.5px solid var(--text-2)}
.sw.arc-key{width:18px;height:8px;border:2px solid var(--text);border-bottom:0;border-radius:9px 9px 0 0;background:none}
/* section 2 */
.built{display:grid;grid-template-columns:minmax(0,1.75fr) minmax(0,1fr);gap:20px;align-items:stretch}
.wall-card{padding:16px 20px 18px}
.reveals-box{padding:16px 20px}
.reveals-box h3{font-size:12px;font-weight:600;letter-spacing:.12em;text-transform:uppercase;color:var(--text-2)}
.reveals{padding-left:18px;margin:0}
.reveals li{margin:0 0 10px}
/* section 3 */
.cards{display:grid;gap:18px;align-items:stretch}
.cards-3{grid-template-columns:repeat(3,minmax(0,1fr))}
.cards-2{grid-template-columns:repeat(2,minmax(0,1fr))}
.cards-3,.cards-2{grid-template-rows:repeat(6,auto)}
.proposal{padding:18px 20px 20px;display:grid;grid-row:span 6;grid-template-rows:subgrid;row-gap:0;align-content:start}
.proposal.best{border-color:var(--text-2)}
.option{margin:0;font-size:12px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:var(--text-2)}
.proposal h3{font-size:22px;letter-spacing:-.01em;margin:4px 0 6px}
.proposal [data-part="principle"]{margin:0;font-size:15px;color:var(--text-2)}
.card-head.with-mini{display:grid;grid-template-columns:112px minmax(0,1fr);gap:16px;align-items:center;margin-bottom:12px}
.mini .sleeve-wrap{border-radius:8px;overflow:hidden;outline:1px solid var(--grid)}
.mini svg:first-child{width:100%;height:auto}
.part-head{margin:18px 0 8px}
.branches{list-style:none;padding:0;margin:0;font-size:14px}
.branches li{display:grid;grid-template-columns:10px minmax(0,1fr);column-gap:9px;align-items:baseline;margin:0 0 6px;
line-height:1.35}
.branches .sw{position:relative;top:1px}
.branches .bpm{display:block;font-size:12px;color:var(--text-2)}
.branches .bpm span{white-space:nowrap}
.mini-note{font-size:13px;color:var(--text-2);margin:-8px 0 18px;max-width:62em}
.lands{list-style:none;padding:0;margin:0;font-size:13px}
.lands li{margin:0 0 6px;line-height:1.35}
.lands .arrow{color:var(--muted)}
.lands .to{color:var(--text-2)}
.cost{font-size:14px;margin:0;padding-top:18px;font-weight:600}
.copybox{display:flex;gap:8px;align-items:stretch}
pre.trigger{flex:1;min-width:0;white-space:pre-wrap;margin:0;padding:9px 12px;background:var(--page);
border:1px solid var(--grid);border-radius:8px;font:14px/1.4 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
user-select:all;-webkit-user-select:all}
button.copy{flex:none;font:inherit;font-size:13px;font-weight:600;padding:6px 14px;border-radius:8px;cursor:pointer;
border:1px solid var(--text);background:var(--text);color:var(--surface)}
.proposal button.copy{background:transparent;color:var(--text);border-color:var(--grid)}
.proposal button.copy:hover{border-color:var(--text-2)}
button.copy:focus-visible,.toggle button:focus-visible{outline:2px solid var(--text);outline-offset:2px}
/* colophon and the sticky next action */
.colophon{border-top:1px solid var(--grid);margin-top:40px;padding:14px 0 18px;color:var(--text-2);font-size:12px}
.colophon p{margin:3px 0}
#next{position:sticky;bottom:0;z-index:5;padding:0;background:var(--surface);border-top:1px solid var(--grid)}
:root:not([data-theme="dark"]) #next{box-shadow:0 -6px 20px rgb(0 0 0 / .08)}
.next-in{max-width:1100px;margin:0 auto;padding:14px 32px;display:flex;align-items:center;flex-wrap:wrap;gap:6px 16px}
#next h2{margin:0;font-size:12px;font-weight:600;letter-spacing:.12em;text-transform:uppercase;color:var(--text-2)}
#next .action{flex:1 1 360px;margin:0;font-size:16px;font-weight:600}
#next .action q{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:15px}
#next .after{flex-basis:100%;margin:0;font-size:12px;color:var(--text-2)}
#tip{position:fixed;z-index:20;left:0;top:0;max-width:300px;padding:8px 11px;border-radius:8px;pointer-events:none;
background:var(--text);color:var(--surface);font-size:12px;line-height:1.35}
#tip strong{display:block;font-size:15px;font-weight:700}
#tip span{display:block;opacity:.8}
#tip[hidden]{display:none}
@media (min-width:960px) and (max-width:1180px){.card-head.with-mini{grid-template-columns:88px minmax(0,1fr)}}
@media (min-width:960px) and (max-width:1060px){.card-head.with-mini{grid-template-columns:72px minmax(0,1fr);gap:12px}
.proposal h3{font-size:20px}}
@media (max-width:959px){
.cards-3,.cards-2{grid-template-columns:minmax(0,1fr)}
.cards-3,.cards-2{grid-template-rows:none}
.proposal{display:block;grid-row:auto}
.hero{grid-template-columns:repeat(2,minmax(0,1fr));grid-template-areas:"text text" "sleeve axes" "stats stats";
column-gap:20px}
.hero-main,.hero-art{display:contents}
.built{grid-template-columns:minmax(0,1fr)}
.stats{grid-template-columns:repeat(3,minmax(0,1fr));grid-template-rows:none;row-gap:16px}
.stat{display:block}
.stat+.stat{border-left:0;padding-left:0}
}
@media (max-width:820px){
.stats{grid-template-columns:repeat(2,minmax(0,1fr))}
.narrative{columns:auto}
}
@media (max-width:719px){.hero{grid-template-columns:minmax(0,1fr);grid-template-areas:"text" "sleeve" "axes" "stats"}}
@media (max-width:600px){
.top,main{padding-left:16px;padding-right:16px}
.stat-value{white-space:normal;text-wrap:balance}
.next-in{padding:12px 16px}
.top{flex-wrap:wrap}
.wall-card,.reveals-box,.proposal,.axes-card,.narrative{padding-left:14px;padding-right:14px}
svg.wall-wide{display:none}svg.wall-narrow{display:block}
.next-in{flex-wrap:nowrap;gap:10px}
#next .long,#next .after{display:none}
#next h2{flex:none}
#next .action{flex:1 1 auto;min-width:0;white-space:normal;display:-webkit-box;-webkit-line-clamp:2;
-webkit-box-orient:vertical;overflow:hidden;font-size:15px}
}
@media (max-width:400px){.axes .t-axis{font-size:15px}.axes .t-value{font-size:14px}.axes .t-tick{font-size:13px}}
@media print{
.toggle,button.copy,#tip,.hits{display:none}
.top,main{max-width:none;padding:0}
.hero,.built,.cards-3,.cards-2{display:block}
.sleeve{max-width:420px;margin-bottom:16px}
.card,.proposal{break-inside:avoid;margin-bottom:16px}
#next{position:static;margin:24px 0 0;padding:12px 0;border-top:1px solid var(--grid);box-shadow:none}
.next-in{max-width:none;padding:0}
section{padding-top:24px}
}
""".strip()

SCRIPT = """
(function () {
  var root = document.documentElement, KEY = "djl-theme";
  function apply(theme, save) {
    root.setAttribute("data-theme", theme);
    var buttons = document.querySelectorAll("[data-set-theme]");
    for (var i = 0; i < buttons.length; i++) {
      var on = buttons[i].getAttribute("data-set-theme") === theme;
      buttons[i].setAttribute("aria-pressed", on ? "true" : "false");
    }
    if (save) { try { localStorage.setItem(KEY, theme); } catch (e) { /* storage refused: still works */ } }
  }
  function chosen() {
    var hash = (location.hash || "").slice(1).toLowerCase();
    if (hash === "day") { return "light"; }
    if (hash === "booth") { return "dark"; }
    var stored = null;
    try { stored = localStorage.getItem(KEY); } catch (e) { stored = null; }
    return stored === "light" || stored === "dark" ? stored : "dark";
  }
  apply(chosen(), false);
  window.addEventListener("hashchange", function () { apply(chosen(), false); });

  document.addEventListener("DOMContentLoaded", function () {
    apply(root.getAttribute("data-theme"), false);
    var buttons = document.querySelectorAll("[data-set-theme]");
    for (var i = 0; i < buttons.length; i++) {
      buttons[i].addEventListener("click", function () { apply(this.getAttribute("data-set-theme"), true); });
    }

    var tip = document.getElementById("tip"), current = null;
    function target(node) { return node && node.closest ? node.closest("[data-tip]") : null; }
    function place(x, y) {
      var w = tip.offsetWidth, h = tip.offsetHeight;
      var left = x + 14, top = y + 16;
      if (left + w > window.innerWidth - 8) { left = Math.max(8, x - w - 14); }
      if (top + h > window.innerHeight - 8) { top = Math.max(8, y - h - 12); }
      tip.style.left = left + "px";
      tip.style.top = top + "px";
    }
    function show(el, x, y) {
      var parts = el.getAttribute("data-tip").split(" · ");
      tip.textContent = "";
      var value = document.createElement("strong");
      value.textContent = parts.shift();
      tip.appendChild(value);
      if (parts.length) {
        var rest = document.createElement("span");
        rest.textContent = parts.join(" · ");
        tip.appendChild(rest);
      }
      tip.hidden = false;
      current = el;
      place(x, y);
    }
    function hide() { tip.hidden = true; current = null; }
    document.addEventListener("pointerover", function (e) {
      var el = target(e.target);
      if (el) { show(el, e.clientX, e.clientY); }
    });
    document.addEventListener("pointermove", function (e) {
      if (current) { place(e.clientX, e.clientY); }
    });
    document.addEventListener("pointerout", function (e) {
      var el = target(e.target);
      if (el && el === current && !(e.relatedTarget && el.contains(e.relatedTarget))) { hide(); }
    });
    document.addEventListener("focusin", function (e) {
      var el = target(e.target);
      if (!el) { return; }
      var box = el.getBoundingClientRect();
      show(el, box.left + box.width / 2, box.top + box.height / 2);
    });
    document.addEventListener("focusout", hide);
    document.addEventListener("keydown", function (e) { if (e.key === "Escape") { hide(); } });

    document.addEventListener("click", function (e) {
      var button = e.target.closest ? e.target.closest("[data-copy]") : null;
      if (!button) { return; }
      var box = document.getElementById(button.getAttribute("data-copy"));
      var source = box ? box.querySelector("pre") || box : null;
      if (!source) { return; }
      var text = source.textContent;
      function said(word) {
        button.textContent = word;
        setTimeout(function () { button.textContent = "Copy"; }, 1600);
      }
      function select() {
        var range = document.createRange();
        range.selectNodeContents(source);
        var selection = window.getSelection();
        selection.removeAllRanges();
        selection.addRange(range);
        var done = false;
        try { done = document.execCommand("copy"); } catch (err) { done = false; }
        said(done ? "Copied" : "Selected");
      }
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(function () { said("Copied"); }, select);
      } else {
        select();
      }
    });
  });
})();
""".strip()


def _source(profile: Mapping[str, Any] | None) -> str:
    prov = (profile or {}).get("provenance") or {}
    return str(prov.get("source") or "")


def _and(names: Sequence[str]) -> str:
    """"a", "a and b", "a, b and c"."""
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


_LOADS = ("link", "iframe", "img", "object", "embed", "base", "frame", "image", "audio", "video", "source")
_LOADING_ATTRS = ("src", "srcset", "poster", "background", "action", "formaction", "data")
_SCHEME = re.compile(r"^\s*(?:[a-z][a-z0-9+.-]*:|//)", re.IGNORECASE)
_OUTSIDE_URL = re.compile(r"url\((?!#[A-Za-z0-9_-]+\))", re.IGNORECASE)


class _Scan(HTMLParser):
    """What `_check` reads of a page: its tags, attribute names, CSS and the attributes that can
    load something. Text and data-* / aria-* values (where library names end up) are not read."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.problems: list[str] = []
        self.scripts = 0
        self.css: list[str] = []
        self._in_style = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._tag(tag, attrs)
        self._in_style = tag == "style"

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._tag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if tag == "style":
            self._in_style = False

    def handle_data(self, data: str) -> None:
        if self._in_style:
            self.css.append(data)

    def _tag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script":
            self.scripts += 1
            if attrs:
                self.problems.append("a script with attributes")
        if tag in _LOADS:
            self.problems.append(f"<{tag}>")
        for name, value in attrs:
            value = value or ""
            if name in _LOADING_ATTRS:
                self.problems.append(f"a {name} attribute")
            elif name.startswith("on"):
                self.problems.append(f"an {name} handler")
            elif name in ("href", "xlink:href") and _SCHEME.match(value):
                self.problems.append("a link out of the library folder")
            elif name == "style":
                self.css.append(value)
            elif not name.startswith(("data-", "aria-")) and _OUTSIDE_URL.search(value):
                self.problems.append("url() to anything but the page itself")


def _check(doc: str) -> None:
    """The page holds no URL and loads nothing: by construction, checked before anything is
    written. "http" anywhere is refused (a library name cannot hold one: `esc` writes it with a
    character reference); the rest is read from the page's HTML (`_Scan`)."""
    scan = _Scan()
    scan.feed(doc)
    scan.close()
    problems = list(dict.fromkeys(scan.problems))
    if "http" in doc.lower():
        problems.insert(0, "http")
    if scan.scripts != 1:
        problems.append("a script other than the page's own")
    css = "\n".join(scan.css)
    if "@import" in css.lower():
        problems.append("@import")
    if _OUTSIDE_URL.search(css):
        problems.append("url() to anything but the page itself")
    if problems:
        raise ReportError(f"the report would hold {', '.join(dict.fromkeys(problems))}; nothing was written")


def page(
    *,
    day: date,
    profile: Mapping[str, Any] | None,
    habits: str | None,
    structure: Mapping[str, Any] | None,
    graph: Mapping[str, Any] | None,
    entries: Sequence[Mapping[str, Any]],
    broken: Sequence[str] = (),
    identity: Mapping[str, Any] | None = None,
    liner: str | None = None,
    taste: Mapping[str, Any] | None = None,
    handle: str | None = None,
) -> str:
    """The whole report as one HTML document (no I/O). `broken`: the facts files that exist but
    do not read; their part is left out with one line saying so."""
    name = str((identity or {}).get("handle") or handle or identity_mod.DEFAULT_HANDLE)
    source = _source(profile)
    missing = [FIELD_NAMES.get(f, f) for f in (profile or {}).get("not_in_source") or []]
    read = f"read from {source}" if source else "read from your export"
    measured = [name for name, data in ((PROFILE_FACTS, profile), (IDENTITY_JSON, identity),
                                        (STRUCTURE_FACTS, structure), (GRAPH_JSON, graph), (TASTE_FACTS, taste),
                                        (proposals_mod.PROPOSALS_YAML, entries)) if data]  # fmt: skip
    words = [name for name, data in ((IDENTITY_MD, liner), (HABITS_MD, habits)) if data and data.strip()]
    credit = f"Measured by code: {MODULE}" + (f" from {_and(measured)}" if measured else "") + f", {day.isoformat()}."
    if words:
        credit += f" Words about you by Claude, from {_and(words)}."
    colophon = [f"<p>{credit}</p>", f"<p>Your library was {esc(read)}. Nothing here changed rekordbox.</p>"]
    if missing:
        colophon.append(f"<p>Not in this source: {esc(', '.join(missing))}.</p>")
    if broken:
        colophon.append(f"<p>Left out, does not read: {esc(', '.join(broken))}.</p>")
    body = [
        '<header class="top">',
        f'<h1 class="brand">dj-librarian · library report · {day.isoformat()}</h1>',
        '<div class="toggle" role="group" aria-label="Theme">'
        '<button type="button" data-set-theme="dark" aria-pressed="true">Booth</button>'
        '<button type="button" data-set-theme="light" aria-pressed="false">Day</button></div>',
        "</header>",
        "<main>",
        _who(profile, habits, identity, liner, name, broken),
        _structure(structure, graph, profile, identity, STRUCTURE_FACTS in broken),
        _proposals(entries, identity, taste),
        '<footer class="colophon">' + "".join(colophon) + "</footer>",
        "</main>",
        _next(entries),  # after <main>: the sticky band runs the full width of the window
        '<div id="tip" role="tooltip" hidden></div>',
    ]
    doc = "\n".join([
        "<!doctype html>",
        '<html lang="en" data-theme="dark">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{esc(name)} · library report {day.isoformat()}</title>",
        f"<style>\n{token_css()}\n{SLOT_CSS}\n{CSS}\n{decade_css()}\n</style>",
        f"<script>\n{SCRIPT}\n</script>",
        "</head>",
        "<body>",
        *body,
        "</body>",
        "</html>",
        "",
    ])  # fmt: skip
    _check(doc)
    return doc


def _report_names(folder: LibraryFolder, day: date) -> Iterator[Path]:
    stem = f"{day.isoformat()}-library"
    yield folder.reports / f"{stem}.html"
    n = 2
    while True:
        yield folder.reports / f"{stem}-{n}.html"
        n += 1


def _handle(folder: LibraryFolder) -> str:
    """The DJ's handle from library.yaml (`dj_name`), "You" without one."""
    try:
        return identity_mod.handle_of(load_meta(folder.root))
    except LibraryFolderError:
        return identity_mod.DEFAULT_HANDLE


def render(folder: LibraryFolder | str | Path, *, today: date | None = None) -> Path:
    """Write reports/<YYYY-MM-DD>-library.html (or -2, -3 ...; never over an existing file)
    from the files in the library folder. Returns its path. A broken structure/proposals.yaml
    -> ProposalsError (nothing written); other missing files leave their part out."""
    folder = library_folder(folder)
    day = today or date.today()
    path = folder.root / proposals_mod.PROPOSALS_YAML
    entries = proposals_mod.load(path) if path.is_file() else []
    names = (PROFILE_FACTS, IDENTITY_JSON, STRUCTURE_FACTS, GRAPH_JSON, TASTE_FACTS)
    facts = {name: read_facts(folder, name) for name in names}
    text = page(
        day=day,
        profile=facts[PROFILE_FACTS][0],
        habits=_read_text(folder.root / HABITS_MD),
        structure=facts[STRUCTURE_FACTS][0],
        graph=facts[GRAPH_JSON][0],
        entries=entries,
        broken=[name for name, (_data, bad) in facts.items() if bad],
        identity=facts[IDENTITY_JSON][0],
        liner=_read_text(folder.root / IDENTITY_MD),
        taste=facts[TASTE_FACTS][0],
        handle=_handle(folder),
    )
    folder.reports.mkdir(parents=True, exist_ok=True)
    for candidate in _report_names(folder, day):  # ends: some -N is always free
        if write_new_text(candidate, text):
            return candidate
    raise AssertionError("unreachable")  # pragma: no cover


def run_render(folder: LibraryFolder | str | Path, *, today: date | None = None) -> dict[str, Any]:
    """render + one log.md line. Returns counts first, then the report path (relative)."""
    folder = library_folder(folder)
    report = render(folder, today=today)
    path = folder.root / proposals_mod.PROPOSALS_YAML
    shown = len(proposals_mod.load(path)) if path.is_file() else 0
    line = append_log(folder.root, "report", {"proposals": shown, "files": 1}, report, today=today)
    return {"counts": {"proposals": shown, "files": 1}, "report": folder.relative(report), "log": line}


def run_report(
    folder: LibraryFolder | str | Path, *, xml: str | Path | None = None, today: date | None = None
) -> dict[str, Any]:
    """Proposals from the latest export (or `xml`) into structure/proposals.yaml, then the HTML
    report, then one log.md line. Returns counts first, the report, the proposals, the files
    written and kept (a copy of a proposals.yaml the DJ or Claude edited)."""
    folder = library_folder(folder)
    lib, source = proposals_mod.read_export(folder, xml)
    found = proposals_mod.candidates(lib)
    paths = proposals_mod.write_proposals(folder, found, today, source=source)
    report = render(folder, today=today)
    counts = {"proposals": len(found), "files": len(paths) + 1}
    line = append_log(folder.root, "report", counts, report, today=today)
    return {
        "counts": counts,
        "source": source,
        "report": folder.relative(report),
        "proposals": [p.summary() for p in found],
        "written": [folder.relative(paths[0]), folder.relative(report)],
        "kept": [folder.relative(p) for p in paths[1:]],
        "log": line,
    }
