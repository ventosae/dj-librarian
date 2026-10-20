"""dj-report, part 2: the one-file HTML report on the DJ's library (R-401 ... R-407).

Door 1 core: stdlib + PyYAML only (contract section 0). Reads only files in the library folder
and writes one new file, `reports/<YYYY-MM-DD>-library.html` (create only: `-2`, `-3` ... when
the name is taken). Never touches rekordbox, Spotify or audio files.

    render(folder, today=None)      -> Path of the new report
    run_render(folder, today=None)  -> render + one log.md line ("report")
    run_report(folder, today=None)  -> proposals (dj.analysis.proposals) + render + one log line

What the page is made of (numbers from code, words from Claude, R-302):
- id="who" (R-402): a point line (collection size), the narrative from `profile/habits.md`
  (Claude's; a placeholder line when it is missing) and exactly 5 stats, the `headline` of
  `profile/facts.json`.
- id="structure" (R-403): the first dj-structure reveal as the point, an inline SVG of the
  current tree (top two levels from `structure/graph.json`, bars = tracks per playlist, a dump
  marked in the accent colour and by the word "dump"), the top <= 5 overlapping pairs as bars,
  and <= 5 reveals (dumps, duplicates, orphans) from `structure/facts.json` and
  `profile/facts.json`.
- id="proposals" (R-404): the 2 or 3 entries of `structure/proposals.yaml`, each with six parts
  marked `data-part`: name, principle, tree (sketch: two levels, <= 5 items per list), lands
  (<= 5 lines, then "and N more"), cost ("About N minutes"), trigger (a copyable block).
- id="next" (R-406): exactly one action under two minutes: say the first proposal's trigger.
A file that is missing leaves its part out with one line saying what is missing; a facts file
that does not read (broken JSON, or not in the shape the dj-profile / dj-structure code writes:
`profile_ok`, `structure_ok`, `graph_ok`) is left out the same way, with one line naming it. The
report still renders (breadboard P4: finish with what there is). Only a broken
`structure/proposals.yaml` stops it (ProposalsError, nothing written): the trigger blocks must
be the ones the DJ or Claude wrote.

A second report on the same day is `<YYYY-MM-DD>-library-2.html`, then `-3` ...: the newest is
the one with the highest number (dj.onboarding.folder_state picks it that way), and the `report`
path in the JSON of every run names the file that run wrote.

Self-contained (R-401): inline CSS with a light and a dark palette (prefers-color-scheme),
inline SVG, no script, no external font, image or link. Every library string is HTML-escaped,
and "://" inside one is written with entities, so the page holds no "http://" or "https://"
at all. Every list on the page has 5 items or fewer (R-407, R-1002 rule 9).
"""

from __future__ import annotations

import html
import json
import re
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from dj import treeschema
from dj.analysis import proposals as proposals_mod
from dj.analysis.common import library_folder
from dj.analysis.profile import FIELD_NAMES
from dj.libfolder import LibraryFolder, append_log, write_new_text
from dj.model import LibraryError

MODULE = "dj.report"
PROFILE_FACTS = "profile/facts.json"
HABITS_MD = "profile/habits.md"
STRUCTURE_FACTS = "structure/facts.json"
GRAPH_JSON = "structure/graph.json"
LIST_MAX = 5
STATS = 5

# The tree drawing: a 360-wide viewBox stays readable on a phone (12 px text at 360 px).
SVG_WIDTH = 360
ROW_H = 24
MAX_ROWS = 18  # rows before "+ N more at the top"
CHILD_ROWS = 4  # children drawn per top-level folder, then "+ N more"
INDENT = 18
BAR_X, BAR_W, BAR_H = 214, 104, 10
COUNT_X = 352
CHAR_W = 6.4  # average width of a 12 px character, for cutting long names

_URL_MARK = re.compile(r"https?://|<script", re.IGNORECASE)


class ReportError(LibraryError):
    """The report could not be rendered. Nothing was written."""


# -- small helpers -----------------------------------------------------------------------------


def esc(text: Any) -> str:
    """HTML-escaped text (quotes too). "://" is written with entities: no URL in the page."""
    return html.escape(str(text), quote=True).replace("://", ":&#47;&#47;")


def _plural(n: int, word: str, plural: str | None = None) -> str:
    return f"{n} {word if n == 1 else (plural or word + 's')}"


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
        and all(_key(d.get("path")) for d in tops)
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


_SHAPES = {PROFILE_FACTS: profile_ok, STRUCTURE_FACTS: structure_ok, GRAPH_JSON: graph_ok}


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


# -- section 1: who you are (R-402) ------------------------------------------------------------


def _inline(text: str) -> str:
    out = esc(text)
    out = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", out)  # a link keeps its text, never its target
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    out = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", out)
    return out


_LIST_LINE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.*)$")


def markdown(text: str) -> str:
    """The Markdown of profile/habits.md as HTML: paragraphs, ## headings, lists (<= 5 shown),
    "> " lines as a muted provenance line. The "# " title is left out (the section has one)."""
    out: list[str] = []
    para: list[str] = []
    items: list[str] = []

    def flush() -> None:
        if para:
            out.append(f"<p>{_inline(' '.join(para))}</p>")
            para.clear()
        if items:
            out.append(_list([_inline(i) for i in items], more_where=HABITS_MD))
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


def _who(profile: Mapping[str, Any] | None, habits: str | None, broken: bool = False) -> str:
    headline = list((profile or {}).get("headline") or [])[:STATS]
    parts = ['<section id="who">', "<h2>1 · Who you are</h2>"]
    if headline:
        first = headline[0]
        parts.append(f'<p class="lead">{esc(first.get("value", ""))}, {esc(first.get("note", ""))}.</p>')
    elif broken:
        parts.append(f'<p class="lead">No numbers: {PROFILE_FACTS} does not read as dj-profile writes it. '
                     "Run dj-profile again.</p>")  # fmt: skip
    else:
        parts.append('<p class="lead">No profile yet: dj-profile did not run, so the numbers are missing.</p>')
    narrative = markdown(habits) if habits and habits.strip() else ""
    if narrative:
        parts.append(f'<div class="narrative">{narrative}</div>')
    else:
        parts.append(
            '<p class="placeholder">The words about you come from dj-profile: it writes '
            f"{esc(HABITS_MD)} from the numbers below.</p>"
        )
    if headline:
        tiles = "".join(
            '<li class="stat">'
            f'<span class="stat-label">{esc(h.get("label", ""))}</span>\n'
            f'<span class="stat-value">{esc(h.get("value", ""))}</span>\n'
            f'<span class="stat-note">{esc(h.get("note", ""))}</span>'
            "</li>\n"
            for h in headline
        )
        parts.append(f'<ul class="stats">{tiles}</ul>')
    parts.append("</section>")
    return "\n".join(parts)


# -- section 2: how it's built (R-403) ---------------------------------------------------------


def _rows(graph: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The rows of the tree drawing: top level and one level below, capped (module constants)."""
    nodes = [n for n in graph.get("nodes") or [] if isinstance(n, Mapping) and "id" in n]
    by_id = {n["id"]: n for n in nodes}
    kids: dict[str, list[str]] = defaultdict(list)
    for edge in graph.get("edges") or []:
        if isinstance(edge, Mapping) and edge.get("target") in by_id:
            kids[edge.get("source")].append(edge["target"])
    roots = [n for n in nodes if n.get("depth") == 1]
    rows: list[dict[str, Any]] = []
    for i, root in enumerate(roots):
        if len(rows) >= MAX_ROWS:
            rows.append({"kind": "more", "depth": 1, "name": f"+ {len(roots) - i} more at the top"})
            break
        rows.append({**root, "depth": 1})
        children = [by_id[c] for c in kids.get(root["id"], [])]
        for child in children[:CHILD_ROWS]:
            rows.append({**child, "depth": 2})
        if len(children) > CHILD_ROWS:
            rows.append({"kind": "more", "depth": 2, "name": f"+ {len(children) - CHILD_ROWS} more"})
    return rows


def _bar_path(x: float, y: float, w: float, h: float, r: float = 4) -> str:
    """A bar square at its baseline (left) with a rounded data end (right)."""
    if w <= r:
        return f"M{x:.1f},{y:.1f}h{w:.1f}v{h:.1f}h{-w:.1f}z"
    return (f"M{x:.1f},{y:.1f}h{w - r:.1f}a{r},{r} 0 0 1 {r},{r}v{h - 2 * r:.1f}"
            f"a{r},{r} 0 0 1 {-r},{r}h{-(w - r):.1f}z")  # fmt: skip


def tree_svg(graph: Mapping[str, Any], dumps: Sequence[str] = ()) -> str:
    """The current tree as inline SVG: one row per folder or playlist, two levels deep."""
    rows = _rows(graph)
    if not rows:
        return ""
    dump_set = set(dumps)
    sized = [r.get("tracks") for r in rows if r.get("kind") in ("playlist", "smart") and isinstance(r.get("tracks"), int)]
    top = max(sized, default=0) or 1
    height = len(rows) * ROW_H + 8
    out = [
        f'<svg class="tree" viewBox="0 0 {SVG_WIDTH} {height}" role="img" '
        'aria-label="Your playlist tree, top two levels, with tracks per playlist">',
        "<title>Your playlist tree, top two levels</title>",
    ]
    for i, row in enumerate(rows):
        mid = 4 + i * ROW_H + ROW_H / 2
        depth = int(row.get("depth") or 1)
        x = 10 + (depth - 1) * INDENT
        kind = row.get("kind")
        if kind == "more":
            out.append(f'<text class="muted" x="{x + 18}" y="{mid + 4:.1f}">{esc(row["name"])}</text>')
            continue
        is_dump = row.get("id") in dump_set
        tracks = row.get("tracks")
        tip = f"{row.get('path', row.get('name', ''))}: " + (
            "smart playlist, tracks not listed" if tracks is None else _plural(int(tracks), "track"))  # fmt: skip
        if is_dump:
            tip += " (a dump)"
        out.append(f"<g><title>{esc(tip)}</title>")
        if depth > 1:
            out.append(f'<path class="line" d="M15,{mid - ROW_H + 7:.1f}V{mid:.1f}H{x - 2}"/>')
        if kind == "folder":
            out.append(f'<rect class="icon" x="{x}" y="{mid - 4:.1f}" width="12" height="9" rx="1.5"/>'
                       f'<rect class="icon" x="{x}" y="{mid - 6:.1f}" width="5" height="3" rx="1"/>')  # fmt: skip
        elif kind == "smart":
            out.append(f'<circle class="ring" cx="{x + 6}" cy="{mid:.1f}" r="3.5"/>')
        else:
            out.append(f'<circle class="icon" cx="{x + 6}" cy="{mid:.1f}" r="4"/>')
        label_x = x + 18
        chars = int((BAR_X - 8 - label_x) / CHAR_W)
        tag = " · dump" if is_dump else ""
        name = _cut(row.get("name", ""), max(4, chars - len(tag))) + tag
        weight = ' class="strong"' if kind == "folder" else ""
        out.append(f'<text{weight} x="{label_x}" y="{mid + 4:.1f}">{esc(name)}</text>')
        if kind in ("playlist", "smart") and isinstance(tracks, int) and tracks > 0:
            width = max(2.0, BAR_W * tracks / top)
            cls = "bar dump" if is_dump else "bar"
            out.append(f'<path class="{cls}" d="{_bar_path(BAR_X, mid - BAR_H / 2, width, BAR_H)}"/>')
        count = "smart" if tracks is None else str(tracks)
        muted = ' class="muted"' if kind != "playlist" else ""
        out.append(f'<text{muted} x="{COUNT_X}" y="{mid + 4:.1f}" text-anchor="end">{esc(count)}</text>')
        out.append("</g>")
    out.append("</svg>")
    return "".join(out)


def _overlap(structure: Mapping[str, Any]) -> str:
    top = list(((structure.get("overlap") or {}).get("top") or []))[:LIST_MAX]
    if not top:
        return "<p>No two playlists share half their tracks or more.</p>"
    items = []
    for pair in top:
        share = round(float(pair.get("jaccard") or 0) * 100)
        shared = int(pair.get("shared") or 0)
        label = f"{pair.get('a', '')} + {pair.get('b', '')}"
        items.append(
            f'<span class="pair">{esc(label)}</span>\n'
            f'<span class="meter" title="{esc(label)}: {share}% overlap"><span style="width:{share}%"></span></span>\n'
            f'<span class="val">{_plural(shared, "track")} shared, {share}% overlap</span>'
        )
    return _list(items, cls="bars")


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


def _structure(structure: Mapping[str, Any] | None, graph: Mapping[str, Any] | None,
               profile: Mapping[str, Any] | None, broken: bool = False) -> str:  # fmt: skip
    parts = ['<section id="structure">', "<h2>2 · How it's built</h2>"]
    if not structure and broken:
        parts += [f'<p class="lead">No structure data: {STRUCTURE_FACTS} does not read as dj-structure '
                  "writes it. Run dj-structure again.</p>", "</section>"]  # fmt: skip
        return "\n".join(parts)
    if not structure:
        parts += ['<p class="lead">No structure data yet: dj-structure did not run.</p>', "</section>"]
        return "\n".join(parts)
    reveals = list(structure.get("reveals") or [])
    parts.append(f'<p class="lead">{esc(reveals[0]) if reveals else "Your playlist tree, as rekordbox holds it."}</p>')
    dumps = [d.get("path") for d in ((structure.get("dumps") or {}).get("top") or []) if isinstance(d, Mapping)]
    svg = tree_svg(graph or {}, dumps)
    if svg:
        parts.append(
            f'<figure>{svg}<figcaption>Top two levels of your tree. Bars: tracks per playlist '
            f'(longest bar = the biggest playlist shown). A dump is marked "dump".</figcaption></figure>'
        )
    parts += ["<h3>Overlap</h3>", _overlap(structure)]
    found = _reveals(structure, profile)
    if found:
        parts += ["<h3>What it reveals</h3>", _list([esc(line) for line in found], cls="reveals")]
    parts.append("</section>")
    return "\n".join(parts)


# -- section 3: proposals (R-404) --------------------------------------------------------------


def _sketch(doc: treeschema.TreeDoc) -> str:
    """The new tree, two levels: top-level nodes and their children, <= 5 per list."""

    def label(node: treeschema.TreeNode) -> str:
        if node.kind == "folder":
            inside = f' <span class="muted">({_plural(len(node.children), "item")} inside)</span>' if node.children else ""
            return f"<strong>{esc(node.name)}/</strong>{inside}"
        fill = node.fill_from
        source = f' <span class="muted">from {_plural(len(fill), "playlist")}</span>' if fill else ""
        smart = ' <span class="muted">(smart, by hand)</span>' if node.kind == "smart" else ""
        return f"{esc(node.name)}{source}{smart}"

    items = []
    for node in doc.nodes:
        if node.kind == "folder" and node.children:
            kids = _list([label(child) for child in node.children])
            items.append(f"<strong>{esc(node.name)}/</strong>{kids}")
        else:
            items.append(label(node))
    return _list(items, cls="sketch", more_where="structure/proposals.yaml")


def _lands(rows: Sequence[Mapping[str, str]]) -> str:
    if not rows:
        return "<p>No playlist with tracks to move yet.</p>"
    items = []
    for row in rows:
        if row["to"] == proposals_mod.STAYS:
            items.append(f'{esc(row["from"])} <span class="muted">stays where it is</span>')
        else:
            items.append(f'{esc(row["from"])} → {esc(row["to"])}')
    return _list(items, cls="lands", more_where="structure/proposals.yaml")


def _proposal(n: int, total: int, p: Mapping[str, Any]) -> str:
    cost = int(p["cost_minutes"])
    return "\n".join([
        f'<article class="proposal" data-slug="{esc(p["slug"])}" data-family="{esc(p["family"])}">',
        f'<p class="option">Option {n} of {total}</p>',
        f'<h3 data-part="name">{esc(p["name"])}</h3>',
        f'<p data-part="principle">{esc(p["principle"])}</p>',
        f'<div data-part="tree"><h4>The new tree</h4>{_sketch(p["tree"])}</div>',
        f'<div data-part="lands"><h4>Where your playlists land</h4>{_lands(p["lands"])}</div>',
        f'<p data-part="cost">About {_plural(cost, "minute")} in rekordbox, from the import to the last '
        "playlist checked.</p>",
        f'<div data-part="trigger"><h4>To build it, say</h4><pre class="trigger">{esc(p["trigger"])}</pre></div>',
        "</article>",
    ])  # fmt: skip


def _proposals(entries: Sequence[Mapping[str, Any]]) -> str:
    parts = ['<section id="proposals">', "<h2>3 · Ways to rebuild it</h2>"]
    if not entries:
        parts += ['<p class="lead">No proposals yet: structure/proposals.yaml is missing.</p>', "</section>"]
        return "\n".join(parts)
    ways = _plural(len(entries), "way")
    parts.append(
        f'<p class="lead">{ways} to rebuild your tree, the best fit first. Each one is built as a copy: '
        "your playlists stay where they are in rekordbox.</p>"
    )
    parts += [_proposal(i, len(entries), p) for i, p in enumerate(entries, 1)]
    parts.append("</section>")
    return "\n".join(parts)


# -- section 4: next (R-406) -------------------------------------------------------------------


def _next(entries: Sequence[Mapping[str, Any]]) -> str:
    if entries:
        action = (f'Pick one: say <q>{esc(entries[0]["trigger"])}</q>, or the trigger of another option '
                  "(under 2 minutes).")  # fmt: skip
        after = "<p>I show you the new tree before anything gets written.</p>"
    else:
        action = "Say run the report again and I build the proposals (under 2 minutes)."
        after = ""
    return "\n".join(['<section id="next">', "<h2>4 · Next</h2>", f'<p class="action">{action}</p>', after,
                      "</section>"])  # fmt: skip


# -- the page ----------------------------------------------------------------------------------

CSS = """
:root{color-scheme:light;--bg:#fcfcfb;--panel:#f3f2ef;--ink:#0b0b0b;--ink-2:#52514e;--ink-3:#6b6a64;
--rule:#e2e1dc;--series:#2a78d6;--accent:#eb6834;--track:#e6e5e0}
@media (prefers-color-scheme:dark){:root{color-scheme:dark;--bg:#1a1a19;--panel:#242422;--ink:#f0efec;
--ink-2:#c3c2b7;--ink-3:#a3a298;--rule:#383835;--series:#3987e5;--accent:#d95926;--track:#30302d}}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);overflow-wrap:break-word;
font:16px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif}
main{max-width:760px;margin:0 auto;padding:24px 16px 48px}
.kicker{margin:0;color:var(--ink-2);font-size:13px}
h1{font-size:28px;line-height:1.2;margin:4px 0 8px}
h2{font-size:20px;line-height:1.3;margin:0 0 4px}
h3{font-size:16px;margin:20px 0 6px}
h4{font-size:13px;font-weight:600;color:var(--ink-2);margin:14px 0 4px}
section{border-top:1px solid var(--rule);padding:24px 0 8px}
.lead{font-size:18px;margin:4px 0 12px}
.prov,.muted,.more,.placeholder{color:var(--ink-2)}
.prov{font-size:13px}
.more{font-size:14px;margin:2px 0 8px}
ul,ol{margin:6px 0;padding-left:22px}
li{margin:2px 0}
.stats{list-style:none;padding:0;margin:16px 0 0;display:grid;gap:8px;
grid-template-columns:repeat(auto-fit,minmax(140px,1fr))}
.stat{background:var(--panel);border-radius:8px;padding:12px;margin:0}
.stat-label,.stat-note{display:block;font-size:13px;color:var(--ink-2)}
.stat-value{display:block;font-size:22px;font-weight:600;line-height:1.25;margin:2px 0}
figure{margin:12px 0}
svg.tree{width:100%;max-width:560px;height:auto;display:block}
svg text{fill:var(--ink);font:12px system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif}
svg text.muted{fill:var(--ink-2)}
svg text.strong{font-weight:600}
svg .line{stroke:var(--rule);stroke-width:1;fill:none}
svg .icon{fill:var(--ink-2)}
svg .ring{fill:none;stroke:var(--ink-2);stroke-width:1.5}
svg .bar{fill:var(--series)}
svg .bar.dump{fill:var(--accent)}
figcaption{font-size:13px;color:var(--ink-2);margin-top:4px}
.bars{list-style:none;padding:0}
.bars li{margin:0 0 12px}
.pair{display:block;font-size:14px}
.meter{display:block;height:8px;max-width:320px;background:var(--track);border-radius:0 4px 4px 0;margin:4px 0 2px}
.meter span{display:block;height:8px;background:var(--series);border-radius:0 4px 4px 0}
.val{font-size:13px;color:var(--ink-2)}
.proposal{background:var(--panel);border-radius:10px;padding:16px;margin:16px 0}
.option{margin:0;font-size:13px;color:var(--ink-2)}
.proposal h3{margin:2px 0 6px;font-size:18px}
.sketch ul{margin:2px 0 4px}
pre.trigger{white-space:pre-wrap;margin:4px 0 0;padding:10px 12px;background:var(--bg);border:1px solid var(--rule);
border-radius:8px;font:15px/1.4 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
user-select:all;-webkit-user-select:all}
.action{font-size:18px;font-weight:600}
footer{border-top:1px solid var(--rule);margin-top:24px;padding-top:12px;color:var(--ink-3);font-size:13px}
footer p{margin:4px 0}
""".strip()


def _source(profile: Mapping[str, Any] | None) -> str:
    prov = (profile or {}).get("provenance") or {}
    return str(prov.get("source") or "")


def page(
    *,
    day: date,
    profile: Mapping[str, Any] | None,
    habits: str | None,
    structure: Mapping[str, Any] | None,
    graph: Mapping[str, Any] | None,
    entries: Sequence[Mapping[str, Any]],
    broken: Sequence[str] = (),
) -> str:
    """The whole report as one HTML document (no I/O). `broken`: the facts files that exist but
    do not read; their part is left out with one line saying so."""
    headline = list((profile or {}).get("headline") or [])
    size = f": {headline[0].get('value', '')}" if headline else ""
    source = _source(profile)
    missing = [FIELD_NAMES.get(f, f) for f in (profile or {}).get("not_in_source") or []]
    read = f"read from {source}" if source else "read from your export"
    footer = [
        f"<p>Measured by code: {MODULE} from {PROFILE_FACTS}, {STRUCTURE_FACTS}, {GRAPH_JSON} and "
        f"{proposals_mod.PROPOSALS_YAML}, {day.isoformat()}. Words about you by Claude, from {HABITS_MD}.</p>",
        f"<p>Your library was {esc(read)}. Nothing here changed rekordbox.</p>",
    ]
    if missing:
        footer.append(f"<p>Not in this source: {esc(', '.join(missing))}.</p>")
    if broken:
        footer.append(f"<p>Left out, does not read: {esc(', '.join(broken))}.</p>")
    body = [
        "<header>",
        f'<p class="kicker">dj-librarian · library report · {day.isoformat()}</p>',
        f"<h1>Your library{esc(size)}</h1>",
        "</header>",
        _who(profile, habits, PROFILE_FACTS in broken),
        _structure(structure, graph, profile, STRUCTURE_FACTS in broken),
        _proposals(entries),
        _next(entries),
        "<footer>" + "".join(footer) + "</footer>",
    ]
    doc = "\n".join([
        "<!doctype html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>Library report {day.isoformat()}</title>",
        f"<style>\n{CSS}\n</style>",
        "</head>",
        "<body>",
        "<main>",
        *body,
        "</main>",
        "</body>",
        "</html>",
        "",
    ])  # fmt: skip
    if _URL_MARK.search(doc):  # every library string is escaped; this holds by construction
        raise ReportError("the report would hold a URL or a script; nothing was written")
    return doc


def _report_names(folder: LibraryFolder, day: date) -> Iterator[Path]:
    stem = f"{day.isoformat()}-library"
    yield folder.reports / f"{stem}.html"
    n = 2
    while True:
        yield folder.reports / f"{stem}-{n}.html"
        n += 1


def render(folder: LibraryFolder | str | Path, *, today: date | None = None) -> Path:
    """Write reports/<YYYY-MM-DD>-library.html (or -2, -3 ...; never over an existing file)
    from the files in the library folder. Returns its path. A broken structure/proposals.yaml
    -> ProposalsError (nothing written); other missing files leave their part out."""
    folder = library_folder(folder)
    day = today or date.today()
    path = folder.root / proposals_mod.PROPOSALS_YAML
    entries = proposals_mod.load(path) if path.is_file() else []
    facts = {name: read_facts(folder, name) for name in (PROFILE_FACTS, STRUCTURE_FACTS, GRAPH_JSON)}
    text = page(
        day=day,
        profile=facts[PROFILE_FACTS][0],
        habits=_read_text(folder.root / HABITS_MD),
        structure=facts[STRUCTURE_FACTS][0],
        graph=facts[GRAPH_JSON][0],
        entries=entries,
        broken=[name for name, (_data, bad) in facts.items() if bad],
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
    line = append_log(folder.root, "report", {"proposals": shown, "files": 1}, report,
                      now=proposals_mod.log_time(today))  # fmt: skip
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
    line = append_log(folder.root, "report", counts, report, now=proposals_mod.log_time(today))
    return {
        "counts": counts,
        "source": source,
        "report": folder.relative(report),
        "proposals": [p.summary() for p in found],
        "written": [folder.relative(paths[0]), folder.relative(report)],
        "kept": [folder.relative(p) for p in paths[1:]],
        "log": line,
    }
